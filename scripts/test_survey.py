"""Geometry, evidence, replay, concurrency and HTTP-boundary regression checks."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image, PngImagePlugin
from survey.core import (Conflict, FROM_MAP, Store, assess, boundary, canonical, digest,
                         gps_check, inspect_image)
from survey.server import make_server


def polygon(cx=826805.75, cy=6590622.25, radius=100):
    ring = [list(FROM_MAP.transform(x,y)) for x,y in
            [(cx-radius,cy-radius),(cx+radius,cy-radius),(cx+radius,cy+radius),(cx-radius,cy+radius)]]
    return {"type":"Polygon", "coordinates":[ring + [ring[0]]]}


def photo(metadata=True, comment=None, day="2023:09:26 13:47:22", lon=(4,39,2.5), lat=(46,24,13.0), offset=None):
    image = Image.new("RGB", (40, 30), (33, 112, 41))
    exif = Image.Exif()
    if metadata:
        exif[34853] = {1:"N",2:lat,3:"E",4:lon}
        exif[34665] = {36867:day}
        if offset:
            exif[34665][36881] = offset
    info = PngImagePlugin.PngInfo()
    if comment:
        info.add_text("Comment", comment)
    buf=io.BytesIO();image.save(buf,"PNG",exif=exif,pnginfo=info)
    return buf.getvalue()


class GeometryTests(unittest.TestCase):
    def test_valid_polygon_geodesic_area_and_projected_roundtrip(self):
        p=boundary(polygon())
        self.assertAlmostEqual(p["area_ha"],4,delta=.03)
        self.assertAlmostEqual(p["map_vertices"][0][0],826705.75,places=4)
        self.assertAlmostEqual(p["map_vertices"][0][1],6590522.25,places=4)

    def test_crossing_repeated_unclosed_holes_nonfinite_rejected(self):
        ring=polygon()["coordinates"][0]
        invalid=[{"type":"Polygon","coordinates":[[ring[0],ring[2],ring[1],ring[3],ring[0]]]},
                 {"type":"Polygon","coordinates":[ring[:-1]]},
                 {"type":"Polygon","coordinates":[ring,ring]},
                 {"type":"Polygon","coordinates":[[ring[0],ring[1],ring[1],ring[0]]]},
                 {"type":"Polygon","coordinates":[[[float('nan'),0],[1,1],[2,0],[float('nan'),0]]]},
                 {"type":"MultiPolygon","coordinates":[[ring]]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):boundary(value)

    def test_point_inside_outside_and_uncertainty_band(self):
        for easting,status in [(826805.75,"PASS"),(827105.75,"FAIL"),(826910.75,"INCONCLUSIVE"),(826900.75,"INCONCLUSIVE")]:
            lon,lat=FROM_MAP.transform(easting,6590622.25)
            self.assertEqual(gps_check({"longitude":lon,"latitude":lat},polygon())[0],status)

    def test_concave_polygon_does_not_use_bounding_box(self):
        ring=[[0,0],[.01,0],[.01,.003],[.003,.003],[.003,.01],[0,.01],[0,0]]
        p=boundary({"type":"Polygon","coordinates":[ring]})
        self.assertEqual(gps_check({"longitude":.008,"latitude":.008},p["geometry"])[0],"FAIL")


class EvidenceTests(unittest.TestCase):
    def test_real_dji_primary_with_embedded_thumbnail(self):
        path=Path(__file__).resolve().parents[1]/"validation/data/46472379c810.jpg"
        if not path.exists():self.skipTest("Local original photo is required")
        meta,_=inspect_image(path.read_bytes())
        self.assertEqual((meta["format"],meta["embedded_frames"]),("MPO",2))
        self.assertEqual((meta["width"],meta["height"]),(5280,3956))
        self.assertEqual(meta["captured_local"],"2023-09-26T13:47:22")
        self.assertAlmostEqual(meta["map_point"][0],826805.816,places=2)

    def test_metadata_changes_keep_pixel_fingerprint(self):
        a,_=inspect_image(photo());b,_=inspect_image(photo(day="2026:09:06 13:47:22",comment="renamed"))
        self.assertNotEqual(a["byte_sha256"],b["byte_sha256"])
        self.assertEqual(a["pixel_sha256"],b["pixel_sha256"])
        self.assertNotEqual(a["captured_local"],b["captured_local"])

    def test_metadata_read_from_file_and_preview_stripped(self):
        meta,preview=inspect_image(photo())
        self.assertEqual(meta["captured_local"],"2023-09-26T13:47:22")
        self.assertAlmostEqual(meta["gps"]["latitude"],46.40361111,places=7)
        self.assertIsNone(meta["captured_utc"])
        with Image.open(io.BytesIO(preview)) as image:self.assertFalse(image.getexif())

    def test_missing_metadata_remains_unknown(self):
        meta,_=inspect_image(photo(False))
        checks={r["code"]:r for r in assess(meta,boundary(polygon()),"2023-09-26",1788652800,[],[])}
        self.assertEqual(checks["boundary"]["status"],"INCONCLUSIVE")
        self.assertEqual(checks["capture_date"]["status"],"INCONCLUSIVE")
        self.assertEqual(checks["coverage"]["status"],"NOT TESTED")

    def test_date_conflict_and_future_time_with_explicit_offset(self):
        meta,_=inspect_image(photo(day="2026:09:08 13:47:22",offset="+02:00"))
        checks={r["code"]:r for r in assess(meta,boundary(polygon()),"2023-09-26",1788652800,[],[])}
        self.assertEqual(checks["capture_date"]["status"],"FAIL")
        self.assertEqual(checks["future_time"]["status"],"FAIL")
        self.assertEqual(meta["captured_utc"],"2026-09-08T11:47:22+00:00")

    def test_invalid_bytes_and_unsupported_format_rejected(self):
        gif=io.BytesIO();Image.new("RGB",(10,10)).save(gif,"GIF")
        for raw in (b"fake.jpg",b"",gif.getvalue(),photo()[:40]):
            with self.assertRaises(ValueError):inspect_image(raw)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1788652800.
        self.store=Store(self.tmp.name,lambda:self.now)
        self.parcel=self.store.save_parcel(polygon(),"Test field")
        self.raw=photo()

    def tearDown(self):self.tmp.cleanup()

    def issue(self,parcel=None,date="2023-09-26"):
        return self.store.issue((parcel or self.parcel)["id"],date)

    def submit(self,challenge=None,raw=None,key="request-1",filename="photo.png"):
        c=challenge or self.issue()
        return self.store.submit(raw or self.raw,c["token"],c["parcel_id"],c["capture_date"],key,filename)

    def test_complete_assessment_has_real_findings_and_immutable_boundary(self):
        report,retry=self.submit()
        codes={x["code"]:x["status"] for x in report["checks"]}
        self.assertFalse(retry)
        self.assertEqual(codes["boundary"],"PASS")
        self.assertEqual(codes["capture_date"],"PASS")
        changed=self.store.save_parcel(polygon(cx=830000),"Moved field")
        self.assertNotEqual(changed["sha256"],report["parcel"]["sha256"])
        self.assertEqual(self.store.report(report["id"])["parcel"],report["parcel"])

    def test_exact_and_metadata_only_reuse_across_submissions(self):
        first,_=self.submit()
        exact,_=self.submit(key="second",filename="renamed.png")
        modified,_=self.submit(raw=photo(comment="metadata only"),key="third")
        for r in (exact,modified):
            bycode={c["code"]:c for c in r["checks"]}
            self.assertEqual(bycode["pixel_reuse"]["status"],"FAIL")
            self.assertIn(first["id"],bycode["pixel_reuse"]["evidence"]["prior_submission_ids"])
        self.assertEqual(next(c for c in exact["checks"] if c["code"]=="exact_reuse")["status"],"FAIL")
        self.assertEqual(next(c for c in modified["checks"] if c["code"]=="exact_reuse")["status"],"PASS")

    def test_retry_is_idempotent_and_changed_retry_rejected(self):
        c=self.issue();a,_=self.submit(c);b,retry=self.submit(c)
        self.assertTrue(retry);self.assertEqual(a,b);self.assertEqual(len(self.store.reports()),1)
        with self.assertRaises(Conflict):self.submit(c,raw=photo(comment="changed"))

    def test_consumed_expired_and_wrong_bound_tokens_rejected(self):
        c=self.issue();self.submit(c)
        with self.assertRaisesRegex(Conflict,"consumed"):self.submit(c,key="again")
        expired=self.issue();self.now+=901
        with self.assertRaisesRegex(Conflict,"expired"):self.submit(expired,key="expired")
        other=self.store.save_parcel(polygon(cx=828000),"Other field");c=self.issue()
        with self.assertRaisesRegex(Conflict,"match"):
            self.store.submit(self.raw,c["token"],other["id"],c["capture_date"],"wrong","x.png")
        with self.assertRaisesRegex(Conflict,"match"):
            self.store.submit(self.raw,c["token"],c["parcel_id"],"2023-09-25","wrong-date","x.png")

    def test_invalid_image_does_not_consume_challenge(self):
        c=self.issue()
        with self.assertRaises(ValueError):self.submit(c,raw=b"not an image")
        self.submit(c)

    def test_two_consumers_cannot_reuse_one_token(self):
        c=self.issue()
        def attempt(i):
            try:return self.submit(c,key=str(i))[0]["id"]
            except Conflict:return "conflict"
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,[1,2]))
        self.assertEqual(results.count("conflict"),1);self.assertEqual(len(self.store.reports()),1)

    def test_simultaneous_retry_returns_original(self):
        c=self.issue()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.submit(c),[1,2]))
        self.assertEqual(results[0][0]["id"],results[1][0]["id"])
        self.assertEqual(sorted(r[1] for r in results),[False,True])

    def test_export_tampering_detected_even_after_attacker_rehashes(self):
        report,_=self.submit();self.assertEqual(self.store.verify(report)["status"],"PASS")
        tampered=json.loads(json.dumps(report));tampered["checks"][0]["status"]="FAIL"
        original_hash=tampered.pop("report_sha256");tampered["report_sha256"]=digest(canonical(tampered))
        self.assertNotEqual(tampered["report_sha256"],original_hash)
        self.assertEqual(self.store.verify(tampered)["status"],"FAIL")
        self.assertEqual(self.store.verify({"id":"unknown"})["status"],"INCONCLUSIVE")

    def test_persistence_survives_store_restart(self):
        report,_=self.submit()
        restarted=Store(self.tmp.name)
        self.assertEqual(restarted.report(report["id"]),report)
        self.assertEqual(restarted.parcels()[0]["id"],self.parcel["id"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.raw=photo()
        meta,preview=inspect_image(self.raw)
        media={"map":preview,"sample":self.raw,"preview":preview,
               "info":{"bounds":[826555.75,6590372.25,827055.75,6590872.25],"sample":{"filename":"sample.png"}}}
        self.server=make_server(0,self.tmp.name,media)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_port
        _,boot=self.request("GET","/api/survey/bootstrap")
        self.csrf=boot["csrf_token"]

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,method,path,data=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=10)
        combined={"Content-Type":"application/json","Origin":f"http://127.0.0.1:{self.port}"}
        if hasattr(self,"csrf"):combined["X-Demo-Token"]=self.csrf
        combined.update(headers or {})
        conn.request(method,path,json.dumps(data) if data is not None else None,combined)
        response=conn.getresponse();raw=response.read();status=response.status;mime=response.getheader("Content-Type","");conn.close()
        return status,json.loads(raw) if "json" in mime else raw

    def test_browser_flow_save_upload_reuse_export_verify(self):
        code,p=self.request("POST","/api/survey/parcels",{"name":"Browser field","geometry":polygon()});self.assertEqual(code,201)
        code,c=self.request("POST","/api/survey/challenges",{"parcel_id":p["id"],"capture_date":"2023-09-26"});self.assertEqual(code,201)
        request={"source":"upload","file_base64":base64.b64encode(self.raw).decode(),"filename":"actual.png","token":c["token"],"parcel_id":p["id"],"capture_date":"2023-09-26","idempotency":"browser-request"}
        code,result=self.request("POST","/api/survey/submissions",request);self.assertEqual(code,201)
        code,again=self.request("POST","/api/survey/submissions",request);self.assertEqual(code,200);self.assertTrue(again["retry"])
        code,report=self.request("GET","/api/survey/reports/"+result["report"]["id"]);self.assertEqual(code,200)
        code,export=self.request("GET","/api/survey/reports/"+result["report"]["id"]+"/export.json");self.assertEqual(code,200);self.assertEqual(export,report)
        code,parcel_export=self.request("GET","/api/survey/parcels/"+p["id"]+"/export.geojson");self.assertEqual(code,200)
        self.assertEqual(boundary(parcel_export)["sha256"],p["sha256"])
        code,v=self.request("POST","/api/survey/verify",{"report":report});self.assertEqual(v["status"],"PASS")
        report["declared_capture_date"]="2023-09-25"
        _,v=self.request("POST","/api/survey/verify",{"report":report});self.assertEqual(v["status"],"FAIL")
        code,raw=self.request("GET","/api/survey/reports/"+report["id"]+"/preview.jpg");self.assertEqual(code,200)
        with Image.open(io.BytesIO(raw)) as im:self.assertFalse(im.getexif())

    def test_host_origin_and_csrf_are_enforced(self):
        for method,path,headers in [("GET","/api/survey/bootstrap",{"Host":"evil.example"}),
                                    ("GET","/api/survey/bootstrap",{"Origin":"https://evil.example"}),
                                    ("POST","/api/survey/parcels",{"X-Demo-Token":"wrong"}),
                                    ("POST","/api/survey/parcels",{"Origin":"https://evil.example"}),
                                    ("GET","/api/survey/bootstrap",{"Sec-Fetch-Site":"cross-site"})]:
            with self.subTest(headers=headers):self.assertEqual(self.request(method,path,{},headers)[0],403)

    def test_private_files_and_path_traversal_are_not_served(self):
        for path in ("/../core.py","/%2e%2e/core.py","/evidence.sqlite3","/state/evidence.sqlite3","/api/survey/reports/../../core.py"):
            self.assertEqual(self.request("GET",path)[0],404)

    def test_public_project_evidence_is_allowlisted_without_private_artifact_paths(self):
        code, evidence = self.request("GET", "/project-evidence.json")
        self.assertEqual(code, 200)
        self.assertEqual(evidence["counting_example"]["estimated_unique_observed"], 18)
        self.assertFalse(evidence["counting_example"]["coverage_verified"])
        self.assertNotIn("/Users/", json.dumps(evidence))
        self.assertNotIn("artifacts", evidence["counting_example"])
        for path in ("/review-summary.js", "/overlap-evidence.jpg"):
            self.assertEqual(self.request("GET", path)[0], 200)
        self.assertEqual(self.request("GET", "/validation/counting/pipeline-smoke-20260906/result.json")[0], 404)

    def test_malformed_upload_and_body_do_not_crash_server(self):
        self.assertEqual(self.request("POST","/api/survey/submissions",{"source":"upload","file_base64":"notbase64"})[0],400)
        self.assertEqual(self.request("POST","/api/survey/parcels",[])[0],400)
        self.assertEqual(self.request("POST","/api/survey/parcels",{}, {"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.request("POST","/api/survey/challenges",{"parcel_id":[],"capture_date":"2023-09-26"})[0],400)
        self.assertEqual(self.request("GET","/api/survey/bootstrap")[0],200)


if __name__ == "__main__":unittest.main()
