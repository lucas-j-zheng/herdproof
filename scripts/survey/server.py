"""Local-only HTTP surface for the survey demo, with an explicit asset allowlist."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import secrets
import re
import mimetypes
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import serve_validation as lab
from survey.core import Conflict, FROM_MAP, MAX_BYTES, Store, canonical, digest, finite, inspect_image
from survey.batch import Batches, MAX_PHOTOS
from survey.worlds import Worlds

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).parent / "web"
MAP_BOUNDS = [826555.75, 6590372.25, 827055.75, 6590872.25]
MAP_SHA = "478e7c4873d14e5190248e826b2b72c2aa63b3e8b3280d9650d26b9a375e86b0"
FLIGHT = ROOT / "validation/terrain-demo/data/flight"


def assets():
    map_raw = (ROOT / "validation/terrain-demo/data/ign/reference-ortho.jpg").read_bytes()
    if digest(map_raw) != MAP_SHA:
        raise ValueError("Reference map changed; verify its bounds and update its pinned checksum before using it.")
    sample = ROOT / "validation/data/46472379c810.jpg"
    raw = sample.read_bytes()
    meta, preview = inspect_image(raw)
    manifest = json.loads((ROOT / "validation/data/manifest.json").read_text())
    expected = next(r["image_sha256"] for r in manifest["records"] if r["id"] == sample.stem)
    if digest(raw) != expected:
        raise ValueError("Demo photograph differs from the source manifest.")
    model = None
    run = ROOT / "validation/default-model-smoke-2026-09-06"
    if (run / (sample.stem + ".json")).exists():
        p = json.loads((run / (sample.stem + ".json")).read_text())
        cfg = json.loads((ROOT / "training/default_model.json").read_text())
        if p["image_sha256"] == expected and p["model_sha256"] == cfg["checkpoint_sha256"]:
            mode = p["modes"][cfg["mode"]]
            model = {"count": sum(b[4] >= cfg["confidence"] for b in mode["boxes"]),
                     "model": cfg["model_id"], "confidence": cfg["confidence"], "image_sha256": expected}
    flight_manifest = FLIGHT / "manifest.json"
    demo_batch = []
    if flight_manifest.exists():
        demo_batch = [{"filename": p["name"], "sha256": p["sha256"]} for p in json.loads(flight_manifest.read_text())["images"]
                      if re.fullmatch(r"DJI_202309261347\d{2}_00(?:14|15|16|17|18|19)_V.JPG", p["name"])]
        demo_batch.sort(key=lambda p: p["filename"])
    return {"map": map_raw, "sample": raw, "preview": preview,
            "info": {"bounds": MAP_BOUNDS, "crs": "EPSG:2154", "map_sha256": MAP_SHA,
                     "demo_batch": demo_batch, "max_batch_photos": MAX_PHOTOS,
                     "sample": {"filename": sample.name, "date": meta["captured_local"][:10], "gps": meta["gps"],
                                "image_sha256": expected}, "model": model}}


def make_server(port, state, media):
    store = Store(state)
    batches = Batches(store)
    worlds = Worlds(store, batches, start_worker=False)
    csrf = secrets.token_urlsafe(32)

    class Handler(lab.Handler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            world_page = urlparse(self.path).path.startswith('/worlds/')
            script = "'self' 'unsafe-inline' 'wasm-unsafe-eval'" if world_page else "'self' 'unsafe-inline'" if urlparse(self.path).path == "/lab" else "'self'"
            self.send_header("Content-Security-Policy", f"default-src 'self'; script-src {script}; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            super().end_headers()

        def local_request(self):
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed_hosts:
                self.send({"error": "Host rejected."}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + x for x in allowed_hosts}:
                self.send({"error": "Origin rejected."}, 403)
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send({"error": "Cross-site request rejected."}, 403)
                return False
            return True

        def raw(self, body, mime):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def download(self, value, filename):
            data = json.dumps(value, indent=2, allow_nan=False).encode() + b"\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.local_request():
                return
            path = urlparse(self.path).path
            try:
                static = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/review-summary.js": ("review-summary.js", "text/javascript; charset=utf-8"),
                          "/project-evidence.json": ("project-evidence.json", "application/json"),
                          "/overlap-evidence.jpg": ("overlap-evidence.jpg", "image/jpeg"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path in static:
                    file, mime = static[path]
                    return self.raw((WEB / file).read_bytes(), mime)
                if path == "/map.jpg":
                    return self.raw(media["map"], "image/jpeg")
                if path == "/example-preview.jpg":
                    return self.raw(media["preview"], "image/jpeg")
                if path == "/api/survey/bootstrap":
                    return self.send({"csrf_token": csrf, "map": media["info"], "parcels": store.parcels(), "reports": store.reports(), "batches": batches.recent(), "worlds": worlds.recent()})
                world_api = re.fullmatch(r'/api/survey/worlds/([a-f0-9]{24})', path)
                if world_api:
                    return self.send(worlds.get(world_api[1]))
                world_bundle = re.fullmatch(r'/api/survey/worlds/([a-f0-9]{24})/replay.zip', path)
                if world_bundle:
                    job=worlds.get(world_bundle[1])
                    if job['status']!='ready': raise KeyError('World is not ready.')
                    file=worlds.root/job['id']/'replay.zip'
                    self.send_response(200);self.send_header('Content-Type','application/zip')
                    self.send_header('Content-Disposition',f'attachment; filename="herdproof-world-{job["id"]}.zip"')
                    self.send_header('Content-Length',str(file.stat().st_size));self.end_headers()
                    import shutil
                    with file.open('rb') as stream: shutil.copyfileobj(stream,self.wfile)
                    return
                world_asset = re.fullmatch(r'/worlds/([a-f0-9]{24})/(.*)', path)
                if world_asset:
                    file = worlds.asset(*world_asset.groups())
                    mime = mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
                    if file.suffix in ('.js', '.mjs'): mime = 'text/javascript'
                    return self.raw(file.read_bytes(), mime)
                batch_route = re.fullmatch(r"/api/survey/batches/([a-f0-9]{24})(?:/(mosaic.png|photos/([a-f0-9]{24})/preview.jpg))?", path)
                if batch_route:
                    ident, suffix, photo_id = batch_route.groups()
                    if suffix == "mosaic.png":
                        return self.raw(batches.mosaic(ident), "image/png")
                    if photo_id:
                        return self.raw(batches.photo(ident, photo_id, preview=True)[0], "image/jpeg")
                    return self.send(batches.get(ident))
                if path.startswith("/api/survey/reports/"):
                    tail = path.removeprefix("/api/survey/reports/")
                    if tail.endswith("/export.json"):
                        report = store.report(tail.removesuffix("/export.json"))
                        return self.download(report, f"herdproof-assessment-{report['id']}.json")
                    if tail.endswith("/preview.jpg"):
                        return self.raw(store.preview(tail.removesuffix("/preview.jpg")), "image/jpeg")
                    return self.send(store.report(tail))
                if path.startswith("/api/survey/parcels/") and path.endswith("/export.geojson"):
                    parcel = store.parcel(path.removeprefix("/api/survey/parcels/").removesuffix("/export.geojson"))
                    return self.download({"type": "Feature", "properties": {"name": parcel["name"],
                        "area_ha": parcel["area_ha"], "boundary_sha256": parcel["sha256"]}, "geometry": parcel["geometry"]},
                        f"herdproof-boundary-{parcel['id']}.geojson")
                if path == "/lab":
                    page = (ROOT / "validation/review.html").read_text()
                    page = page.replace('<nav aria-label="Sections">', '<nav aria-label="Sections"><a href="/">← Survey checks</a>')
                    page = page.replace("headers:{'Content-Type':'application/json'}", "headers:{'Content-Type':'application/json','X-Demo-Token':" + json.dumps(csrf) + "}")
                    return self.raw(page.encode(), "text/html; charset=utf-8")
                # The established lab serves only fixed routes and normalized image IDs.
                return super().do_GET()
            except (KeyError, FileNotFoundError):
                self.send({"error": "Not found."}, 404)

        def do_POST(self):
            if not self.local_request():
                return
            if not secrets.compare_digest(self.headers.get("X-Demo-Token", ""), csrf):
                return self.send({"error": "Missing or stale page token. Reload this page."}, 403)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send({"error": "Use application/json."}, 415)
            if not self.path.startswith("/api/survey/"):
                return super().do_POST()
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Chunked requests are unsupported.")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 28 * 1024 * 1024:
                    raise ValueError("Request exceeds upload limit.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object.")
                if self.path == '/api/survey/worlds':
                    return self.send(worlds.create(body.get('batch_id'), body.get('parcel_id')), 202)
                world_retry = re.fullmatch(r'/api/survey/worlds/([a-f0-9]{24})/retry', self.path)
                if world_retry:
                    return self.send(worlds.retry(world_retry[1]), 202)
                if self.path == "/api/survey/batches":
                    return self.send(batches.create(), 201)
                batch_route = re.fullmatch(r"/api/survey/batches/([a-f0-9]{24})/(photos|build|coverage)", self.path)
                if batch_route:
                    ident, operation = batch_route.groups()
                    if operation == "build":
                        return self.send(batches.build(ident), 202)
                    if operation == "coverage":
                        if not isinstance(body.get("parcel_id"), str):
                            raise ValueError("Choose a saved boundary.")
                        return self.send(batches.coverage(ident, body["parcel_id"]))
                    if body.get("source") == "example_batch":
                        index = body.get("index")
                        examples = media["info"].get("demo_batch", [])
                        if type(index) is not int or not 0 <= index < len(examples):
                            raise ValueError("Choose an available demo photograph.")
                        item = examples[index]
                        raw, filename = (FLIGHT / item["filename"]).read_bytes(), item["filename"]
                        if digest(raw) != item["sha256"]:
                            raise ValueError("Demo photograph differs from its source manifest.")
                    elif body.get("source") == "example":
                        raw, filename = media["sample"], media["info"]["sample"]["filename"]
                    else:
                        raw, filename = self.upload(body)
                    return self.send(batches.add(ident, raw, filename), 201)
                if self.path == "/api/survey/parcels":
                    geometry = body.get("geometry")
                    if "map_vertices" in body:
                        points = body["map_vertices"]
                        if not isinstance(points, list) or not 3 <= len(points) <= 128 or any(
                            not isinstance(p, list) or len(p) != 2 or not all(finite(x) for x in p) for p in points):
                            raise ValueError("Draw 3–128 valid boundary vertices.")
                        coords = [list(FROM_MAP.transform(*p)) for p in points]
                        geometry = {"type": "Polygon", "coordinates": [coords + [coords[0]]]}
                    return self.send(store.save_parcel(geometry, body.get("name")), 201)
                if self.path == "/api/survey/challenges":
                    return self.send(store.issue(body.get("parcel_id"), body.get("capture_date")), 201)
                if self.path == "/api/survey/submissions":
                    if body.get("source") == "example":
                        raw, filename = media["sample"], media["info"]["sample"]["filename"]
                    elif body.get("source") == "upload":
                        raw, filename = self.upload(body)
                    elif body.get("source") == "batch":
                        raw, filename = batches.photo(body.get("batch_id"), body.get("photo_id"))
                    else:
                        raise ValueError("Choose an example or upload an image.")
                    report, retry = store.submit(raw, body.get("token"), body.get("parcel_id"), body.get("capture_date"), body.get("idempotency"), filename)
                    return self.send({"report": report, "retry": retry}, 200 if retry else 201)
                if self.path == "/api/survey/verify":
                    return self.send(store.verify(body.get("report")))
                return self.send({"error": "Not found."}, 404)
            except Conflict as error:
                self.send({"error": str(error)}, 409)
            except (ValueError, TypeError, KeyError, binascii.Error, OverflowError) as error:
                self.send({"error": str(error)}, 400)

        def upload(self, body):
            encoded = body.get("file_base64")
            if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES + 2) // 3 * 4:
                raise ValueError("Use an image no larger than 20 MiB.")
            return base64.b64decode(encoded, validate=True), body.get("filename")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.worlds = worlds
    import threading
    worlds.thread=threading.Thread(target=worlds._worker,daemon=True)
    worlds.thread.start()
    original_close = server.server_close
    def close():
        worlds.stopping.set(); worlds.wake.set()
        original_close()
        worlds.thread.join(timeout=2)
    server.server_close = close
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18776)
    parser.add_argument("--state", type=Path, default=ROOT / "validation/survey-demo/state")
    args = parser.parse_args()
    lab.RUN = ROOT / "validation/runs/finetuned"
    server = make_server(args.port, args.state, assets())
    print(f"HerdProof survey checks: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()
