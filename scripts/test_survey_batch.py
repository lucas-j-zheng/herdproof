"""Batch workflow, real alignment, transparent gaps and original-evidence checks."""
import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, PngImagePlugin
from shapely.geometry import shape

from survey.batch import Batches, compose, initial_placement
from survey.core import Conflict, FROM_MAP, GEOD, Store, digest, inspect_image
from test_survey import HTTPTests as ExistingHTTPTests, photo, polygon


def drone(yaw=0, pitch=-90, altitude=100, gps=True, orientation=1):
    image = Image.new("RGB", (480, 360), (35, 100, 45))
    exif = Image.Exif()
    exif[274] = orientation
    if gps:
        exif[34853] = {1: "N", 2: (46, 24, 13), 3: "E", 4: (4, 39, 2.5)}
    exif[34665] = {41989: 24, 36867: "2023:09:26 13:47:22"}
    info = PngImagePlugin.PngInfo()
    info.add_text("XMP", f'drone-dji:RelativeAltitude="{altitude}" drone-dji:GimbalYawDegree="{yaw}" drone-dji:GimbalPitchDegree="{pitch}" drone-dji:GimbalRollDegree="0"')
    output = io.BytesIO(); image.save(output, "PNG", exif=exif, pnginfo=info)
    return output.getvalue()


def frame(ident, rgb, corners, ordinal):
    output = io.BytesIO(); Image.fromarray(rgb).save(output, "PNG")
    return {"id": ident, "ordinal": ordinal, "preview": output.getvalue(),
            "meta": {"captured_local": f"2023-09-26T13:47:{22+ordinal:02}", "map_point": np.mean(corners, axis=0).tolist()},
            "placement": {"corners": corners, "initial_corners": corners, "status": "approximate"}}


class PlacementTests(unittest.TestCase):
    def test_north_and_east_headings_project_correct_corner_order_and_size(self):
        for yaw, bearing in [(0, -53.1301), (90, 36.8699)]:
            raw=drone(yaw=yaw); meta,_=inspect_image(raw); result=initial_placement(raw,meta)
            self.assertEqual(result["status"], "approximate")
            lon,lat=FROM_MAP.transform(*result["corners"][0])
            azimuth,_,distance=GEOD.inv(meta["gps"]["longitude"],meta["gps"]["latitude"],lon,lat)
            self.assertAlmostEqual(azimuth,bearing,places=3)
            self.assertAlmostEqual(distance,90.1388,places=3)

    def test_missing_or_unsupported_metadata_never_invents_footprints(self):
        for raw in [photo(),drone(gps=False),drone(pitch=-20),drone(altitude=-10),drone(altitude=float('nan')),drone(orientation=6)]:
            meta,_=inspect_image(raw); result=initial_placement(raw,meta)
            self.assertEqual(result["status"],"unplaced");self.assertIsNone(result["corners"])

    def test_composite_keeps_disconnected_gaps_transparent(self):
        rgb=np.full((100,100,3),120,np.uint8)
        items=[frame("one",rgb,[[0,100],[100,100],[100,0],[0,0]],0),
               frame("two",rgb,[[200,100],[300,100],[300,0],[200,0]],1)]
        result,png=compose(items)
        self.assertEqual(result["placed"],2);self.assertEqual(result["links"],[])
        self.assertEqual(result["coverage"]["type"],"MultiPolygon")
        self.assertEqual(shape(result["coverage"]).area,20000)
        image=np.asarray(Image.open(io.BytesIO(png)))
        self.assertEqual(image[image.shape[0]//2,image.shape[1]//2,3],0)
        self.assertEqual(image[image.shape[0]//2,image.shape[1]//6,3],255)

    def test_overlapping_real_pixels_are_registered_and_union_not_double_counted(self):
        rng=np.random.default_rng(45)
        texture=cv2.GaussianBlur(rng.integers(0,256,(500,850,3),dtype=np.uint8),(3,3),0)
        first=texture[60:420,30:510];second=texture[60:420,170:650]
        items=[frame("one",first,[[0,72],[96,72],[96,0],[0,0]],0),
               frame("two",second,[[28,72],[124,72],[124,0],[28,0]],1)]
        result,png=compose(items)
        self.assertEqual(len(result["links"]),1)
        self.assertGreater(result["links"][0]["inliers"],40)
        self.assertAlmostEqual(shape(result["coverage"]).area,124*72,delta=30)
        self.assertLess(shape(result["coverage"]).area,96*72*2)
        self.assertIsNotNone(png)


class BatchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.batches=Batches(self.store)

    def tearDown(self):self.tmp.cleanup()

    def ready(self, ident):
        deadline=time.monotonic()+10
        while (value:=self.batches.get(ident))["status"]=="building" and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(value["status"],"ready",value["message"])
        return value

    def test_batch_upload_original_retention_deduplication_limit_and_closed_state(self):
        batch=self.batches.create();raw=drone();ident=batch['id']
        added=self.batches.add(ident,raw,"../label-only.png")
        self.assertTrue(self.batches.add(ident,raw,"renamed.png")["duplicate"])
        self.assertEqual(len(self.batches.get(ident)["photos"]),1)
        self.assertEqual(self.batches.photo(ident,added["photo_id"])[0],raw)
        with patch("survey.batch.MAX_PHOTOS",1),self.assertRaises(ValueError):self.batches.add(ident,photo(),"extra.png")
        self.batches.build(ident);self.ready(ident)
        with self.assertRaises(Conflict):self.batches.add(ident,photo(),"new.png")
        # A lost upload response can still be recovered after the batch is closed.
        self.assertTrue(self.batches.add(ident,raw,"renamed.png")["duplicate"])
        self.assertEqual(Batches(Store(self.tmp.name)).get(ident)["photos"][0]["meta"]["byte_sha256"],digest(raw))

    def test_unplaced_photos_finish_without_fake_mosaic_and_remain_checkable(self):
        batch=self.batches.create();raw=photo(metadata=False)
        added=self.batches.add(batch["id"],raw,"no-gps.png")
        self.batches.build(batch["id"]);result=self.ready(batch["id"])
        self.assertEqual(result["result"]["placed"],0)
        with self.assertRaises(KeyError):self.batches.mosaic(batch["id"])
        parcel=self.store.save_parcel(polygon(),"Farm")
        token=self.store.issue(parcel["id"],"2023-09-26")
        report,_=self.store.submit(*self.batches.photo(batch["id"],added["photo_id"])[:1],token["token"],parcel["id"],"2023-09-26","batch-evidence","no-gps.png")
        self.assertEqual(next(c["status"] for c in report["checks"] if c["code"]=="boundary"),"INCONCLUSIVE")
        self.assertEqual(report["media"]["byte_sha256"],digest(raw))

    def test_coverage_uses_polygon_intersection_and_empty_build_is_rejected(self):
        batch=self.batches.create()
        with self.assertRaises(ValueError):self.batches.build(batch["id"])
        self.batches.add(batch["id"],drone(),"survey.png");self.batches.build(batch["id"]);value=self.ready(batch["id"])
        corners=value["photos"][0]["placement"]["corners"]
        coords=[list(FROM_MAP.transform(*p)) for p in corners]
        parcel=self.store.save_parcel({"type":"Polygon","coordinates":[coords+[coords[0]]]},"Footprint test")
        coverage=self.batches.coverage(batch["id"],parcel["id"])
        self.assertEqual(coverage["percent"],100)
        outside=self.store.save_parcel(polygon(cx=827805.75),"Other field")
        self.assertEqual(self.batches.coverage(batch["id"],outside["id"])["percent"],0)
        self.assertIn("unverified",coverage["message"])


class BatchHTTPTests(unittest.TestCase):
    setUp=ExistingHTTPTests.setUp
    tearDown=ExistingHTTPTests.tearDown
    request=ExistingHTTPTests.request

    def test_batch_before_boundary_build_preview_and_original_evidence_roundtrip(self):
        code,batch=self.request("POST","/api/survey/batches",{});self.assertEqual(code,201)
        base="/api/survey/batches/"+batch["id"]
        raw=drone();body={"source":"upload","filename":"camera.png","file_base64":base64.b64encode(raw).decode()}
        code,added=self.request("POST",base+"/photos",body);self.assertEqual(code,201)
        code,again=self.request("POST",base+"/photos",body);self.assertTrue(again["duplicate"])
        self.assertEqual(self.request("POST",base+"/build",{})[0],202)
        deadline=time.monotonic()+10
        while (value:=self.request("GET",base)[1])["status"]=="building" and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(value["status"],"ready")
        self.assertEqual(self.request("GET",base+"/mosaic.png")[0],200)
        code,preview=self.request("GET",base+"/photos/"+added["photo_id"]+"/preview.jpg");self.assertEqual(code,200)
        self.assertFalse(Image.open(io.BytesIO(preview)).getexif())
        _,parcel=self.request("POST","/api/survey/parcels",{"name":"After upload","geometry":polygon()})
        code,cov=self.request("POST",base+"/coverage",{"parcel_id":parcel["id"]});self.assertEqual(code,200);self.assertGreater(cov["percent"],0)
        _,challenge=self.request("POST","/api/survey/challenges",{"parcel_id":parcel["id"],"capture_date":"2023-09-26"})
        request={"source":"batch","batch_id":batch["id"],"photo_id":added["photo_id"],"parcel_id":parcel["id"],"capture_date":"2023-09-26","token":challenge["token"],"idempotency":"batch-original"}
        code,result=self.request("POST","/api/survey/submissions",request);self.assertEqual(code,201)
        self.assertEqual(result["report"]["media"]["byte_sha256"],digest(raw))
        self.assertEqual(self.request("POST","/api/survey/submissions",request)[0],200)
        _,other=self.request("POST","/api/survey/batches",{})
        self.assertEqual(self.request("GET","/api/survey/batches/"+other["id"]+"/photos/"+added["photo_id"]+"/preview.jpg")[0],404)

    def test_new_endpoints_enforce_tokens_payloads_and_private_media_routes(self):
        self.assertEqual(self.request("POST","/api/survey/batches",{}, {"X-Demo-Token":"wrong"})[0],403)
        _,batch=self.request("POST","/api/survey/batches",{});base="/api/survey/batches/"+batch["id"]
        self.assertEqual(self.request("POST",base+"/photos",{"file_base64":"?"})[0],400)
        self.assertEqual(self.request("POST",base+"/photos",{"source":"example_batch","index":True})[0],400)
        self.assertEqual(self.request("POST",base+"/coverage",{"parcel_id":[]})[0],400)
        self.assertEqual(self.request("GET",base+"/../../evidence.sqlite3")[0],404)
        self.assertEqual(self.request("GET",base+"/photos/"+"0"*24+"/media")[0],404)


# Do not rediscover the imported base class as another copy of its HTTP tests.
del ExistingHTTPTests

if __name__=="__main__":unittest.main()
