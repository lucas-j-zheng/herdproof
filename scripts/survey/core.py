"""Server-authoritative checks. Consistency findings never establish scene truth."""
from __future__ import annotations

import hashlib
import io
import json
import math
import secrets
import sqlite3
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pyproj import Geod, Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import transform
from shapely.validation import explain_validity

VERSION = "1.0"
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
GPS_MARGIN_M = 10
TO_MAP = Transformer.from_crs(4326, 2154, always_xy=True)
FROM_MAP = Transformer.from_crs(2154, 4326, always_xy=True)
GEOD = Geod(ellps="WGS84")


class Conflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def boundary(value):
    if not isinstance(value, dict):
        raise ValueError("Supply a GeoJSON Polygon or Feature.")
    geometry = value.get("geometry") if value.get("type") == "Feature" else value
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("Use one GeoJSON Polygon in longitude, latitude order.")
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or len(rings) != 1:
        raise ValueError("This demo supports one boundary without holes; split other areas into separate boundaries.")
    ring = rings[0]
    if not isinstance(ring, list) or not 4 <= len(ring) <= 129:
        raise ValueError("Use 3–128 vertices and repeat the first vertex to close the boundary.")
    for p in ring:
        if (not isinstance(p, list) or len(p) != 2 or not all(finite(x) for x in p)
                or not -180 <= p[0] <= 180 or not -85 <= p[1] <= 85):
            raise ValueError("Coordinates must be finite [longitude, latitude] pairs within supported bounds.")
    if ring[0] != ring[-1] or len({tuple(p) for p in ring[:-1]}) != len(ring) - 1:
        raise ValueError("Close the boundary and remove repeated vertices.")
    poly = Polygon(ring)
    if not poly.is_valid:
        raise ValueError("Boundary is invalid: " + explain_validity(poly))
    if poly.bounds[2] - poly.bounds[0] > 1 or poly.bounds[3] - poly.bounds[1] > 1:
        raise ValueError("Use a local farm boundary spanning less than one degree; dateline crossings are unsupported.")
    area, _ = GEOD.geometry_area_perimeter(poly)
    if abs(area) < 10:
        raise ValueError("Boundary must cover at least 10 square metres.")
    normalized = {"type": "Polygon", "coordinates": [[[float(x), float(y)] for x, y in ring]]}
    return {"geometry": normalized, "sha256": digest(canonical(normalized)),
            "area_ha": abs(area) / 10_000,
            "map_vertices": [list(TO_MAP.transform(*p)) for p in ring[:-1]]}


def gps_check(location, geometry):
    # Distance uses a metre-based projection centred on the parcel, not degree units.
    poly = Polygon(geometry["coordinates"][0])
    centre = poly.centroid
    projection = Transformer.from_crs(4326,
        f"+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +datum=WGS84 +units=m", always_xy=True)
    projected = transform(projection.transform, poly)
    point = Point(*projection.transform(location["longitude"], location["latitude"]))
    distance = projected.boundary.distance(point)
    if not math.isfinite(distance):
        raise ValueError("GPS cannot be projected near this boundary.")
    inside = projected.covers(point)
    status = "INCONCLUSIVE" if distance <= GPS_MARGIN_M else "PASS" if inside else "FAIL"
    return status, {"inside": inside, "distance_to_boundary_m": round(distance, 2),
                    "boundary_margin_m": GPS_MARGIN_M}


def inspect_image(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Use a JPEG or PNG no larger than 20 MiB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                frames = getattr(image, "n_frames", 1)
                pixel_scope = "complete decoded image"
                if image.format == "MPO":
                    # DJI's original JPEG includes an MPF preview. Permit a primary
                    # JPEG plus declared thumbnails, not an arbitrary multi-view set.
                    entries = getattr(image, "mpinfo", {}).get(45058, [])
                    if (not 1 <= len(entries) <= 4 or len(entries) != frames
                            or entries[0]["Attribute"]["MPType"] != "Baseline MP Primary Image"
                            or any(not e["Attribute"]["MPType"].startswith("Large Thumbnail") for e in entries[1:])):
                        raise ValueError("Multi-view images are unsupported; use one primary photograph.")
                    pixel_scope = "primary JPEG; embedded MPF thumbnails excluded from pixel comparison"
                    image.seek(0)
                elif image.format not in {"JPEG", "PNG"} or frames != 1:
                    raise ValueError("Use a JPEG or single-frame PNG photograph.")
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("Image exceeds the 32-megapixel limit.")
                image.load()  # Decode the bytes; an extension or client hash is never trusted.
                rgb = image.convert("RGB")
                result = {"byte_sha256": digest(raw), "bytes": len(raw), "format": image.format,
                          "embedded_frames": frames, "pixel_scope": pixel_scope,
                          "width": image.width, "height": image.height,
                          "pixel_sha256": digest(canonical([image.width, image.height, "RGB"]) + rgb.tobytes()),
                          "gps": None, "map_point": None, "captured_local": None, "captured_utc": None, "metadata_errors": []}
                try:
                    exif = image.getexif()
                    gps = exif.get_ifd(34853)
                    detail = exif.get_ifd(34665)
                    result["orientation"] = int(exif.get(274, 1))
                    if gps:
                        def degrees(key, ref, allowed):
                            parts = gps[key]
                            direction = gps[ref]
                            if len(parts) != 3 or direction not in allowed:
                                raise ValueError("Invalid GPS representation")
                            parts = [float(x) for x in parts]
                            if not all(math.isfinite(x) and x >= 0 for x in parts) or parts[1] >= 60 or parts[2] >= 60:
                                raise ValueError("Invalid GPS values")
                            value = parts[0] + parts[1] / 60 + parts[2] / 3600
                            return -value if direction in ("S", "W") else value
                        lat, lon = degrees(2, 1, ("N", "S")), degrees(4, 3, ("E", "W"))
                        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                            raise ValueError("GPS is out of range")
                        result["gps"] = {"latitude": lat, "longitude": lon, "source": "editable EXIF GPS"}
                        mapped = list(TO_MAP.transform(lon, lat))
                        result["map_point"] = mapped if all(finite(x) for x in mapped) else None
                    captured = detail.get(36867) or exif.get(36867)
                    if captured:
                        local = datetime.strptime(str(captured), "%Y:%m:%d %H:%M:%S")
                        result["captured_local"] = local.isoformat()
                        offset = detail.get(36881) or exif.get(36881)
                        if offset:
                            aware = datetime.fromisoformat(local.isoformat() + str(offset))
                            if aware.tzinfo is None:
                                raise ValueError("Invalid EXIF timezone")
                            result["captured_utc"] = aware.astimezone(timezone.utc).isoformat()
                except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError, SyntaxError) as error:
                    result["metadata_errors"].append(str(error))
                # Preview is separate from original evidence and strips metadata.
                preview = ImageOps.exif_transpose(image).convert("RGB")
                preview.thumbnail((1200, 900))
                clean = Image.frombytes("RGB", preview.size, preview.tobytes())
                buf = io.BytesIO()
                clean.save(buf, "JPEG", quality=88)
                return result, buf.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("File could not be safely decoded as a supported image.") from error


def finding(code, label, status, message, evidence=None):
    return {"code": code, "label": label, "status": status, "message": message, "evidence": evidence or {}}


def assess(meta, parcel, declared_date, received, exact, pixels):
    checks = [finding("submission_token", "One-use submission token", "PASS",
        "Issued by this server, bound to this boundary and capture date, and consumed once. This does not prove a fresh capture.")]
    checks.append(finding("exact_reuse", "Exact file reuse", "FAIL" if exact else "PASS",
        "These exact bytes were already submitted." if exact else "No exact match in this demo's retained submissions.",
        {"prior_submission_ids": exact, "scope": "this local demo database", "sha256": meta["byte_sha256"]}))
    checks.append(finding("pixel_reuse", "Same decoded pixels", "FAIL" if pixels else "PASS",
        "The decoded image already exists, including when metadata or the filename changes." if pixels else
        "No identical decoded RGB image in retained submissions. Crops and lossy re-encoding may evade this check.",
        {"prior_submission_ids": pixels, "sha256": meta["pixel_sha256"], "orientation": "raw decoded pixels before EXIF rotation"}))
    if meta["gps"]:
        status, evidence = gps_check(meta["gps"], parcel["geometry"])
        checks.append(finding("boundary", "Camera GPS vs farmland", status,
            "Camera GPS is within 10 m of the boundary; allow for location uncertainty." if status == "INCONCLUSIVE" else
            "Supplied camera GPS is inside the selected boundary." if status == "PASS" else
            "Supplied camera GPS is outside the selected boundary. Review location and parcel selection.", evidence))
    else:
        checks.append(finding("boundary", "Camera GPS vs farmland", "INCONCLUSIVE", "No usable EXIF GPS. Location remains unknown."))
    if meta["captured_local"]:
        match = meta["captured_local"][:10] == declared_date
        checks.append(finding("capture_date", "Declared date vs photo", "PASS" if match else "FAIL",
            "The EXIF camera-local date matches the declared camera-local date." if match else
            "The photo's EXIF date conflicts with the declared capture date.",
            {"declared_camera_local_date": declared_date, "exif_camera_local_time": meta["captured_local"],
             "source": "editable EXIF DateTimeOriginal; no timezone inferred"}))
    else:
        checks.append(finding("capture_date", "Declared date vs photo", "INCONCLUSIVE", "No usable original capture time in EXIF."))
    if meta["captured_utc"]:
        future = datetime.fromisoformat(meta["captured_utc"]).timestamp() > received + 300
        checks.append(finding("future_time", "Capture time vs receipt", "FAIL" if future else "PASS",
            "EXIF capture is more than five minutes after server receipt." if future else "EXIF capture is not later than server receipt plus five minutes.",
            {"exif_utc": meta["captured_utc"], "server_received_utc": utc(received)}))
    else:
        future = meta["captured_local"] and date.fromisoformat(meta["captured_local"][:10]) > datetime.fromtimestamp(received, timezone.utc).date() + timedelta(days=1)
        checks.append(finding("future_time", "Capture time vs receipt", "FAIL" if future else "INCONCLUSIVE",
            "EXIF date is beyond the next UTC day, even allowing for timezone differences." if future else
            "No explicit EXIF timezone; exact comparison with server time is unavailable."))
    if meta["metadata_errors"]:
        checks.append(finding("metadata", "Metadata structure", "INCONCLUSIVE", "Some metadata could not be interpreted.", {"errors": meta["metadata_errors"]}))
    checks.append(finding("coverage", "Whole-property coverage", "NOT TESTED",
        "A camera point does not establish photographed area, a complete property sweep, or a unique herd total."))
    return checks


class Store:
    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "evidence.sqlite3"
        self.clock = clock
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS parcels(id TEXT PRIMARY KEY, created REAL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges(token TEXT PRIMARY KEY, parcel_id TEXT NOT NULL,
                    capture_date TEXT NOT NULL, expires REAL NOT NULL, used_by TEXT);
                CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY, received REAL NOT NULL,
                    idempotency TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
                    byte_hash TEXT NOT NULL, pixel_hash TEXT NOT NULL, report TEXT NOT NULL,
                    report_hash TEXT NOT NULL, media BLOB NOT NULL, preview BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS byte_lookup ON submissions(byte_hash);
                CREATE INDEX IF NOT EXISTS pixel_lookup ON submissions(pixel_hash);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def save_parcel(self, geometry, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Give the boundary a name of 1–100 characters.")
        body = {**boundary(geometry), "id": secrets.token_hex(12), "name": name.strip(), "created_utc": utc(self.clock())}
        with self.connect() as db:
            db.execute("INSERT INTO parcels VALUES(?,?,?)", (body["id"], self.clock(), canonical(body).decode()))
        return body

    def parcels(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM parcels ORDER BY created DESC, rowid DESC LIMIT 100")]

    def parcel(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT body FROM parcels WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError("Boundary not found.")
        return json.loads(row[0])

    def issue(self, parcel_id, capture_date):
        if not isinstance(parcel_id, str) or len(parcel_id) != 24 or any(c not in "0123456789abcdef" for c in parcel_id):
            raise ValueError("Choose a saved boundary.")
        if not isinstance(capture_date, str) or date.fromisoformat(capture_date).isoformat() != capture_date:
            raise ValueError("Supply a valid capture date (YYYY-MM-DD).")
        if date.fromisoformat(capture_date) > datetime.fromtimestamp(self.clock(), timezone.utc).date() + timedelta(days=1):
            raise ValueError("Declared capture date is in the future.")
        token, expires = secrets.token_urlsafe(32), self.clock() + 900
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM parcels WHERE id=?", (parcel_id,)).fetchone():
                raise ValueError("Save a boundary before submitting evidence.")
            db.execute("INSERT INTO challenges VALUES(?,?,?,?,NULL)", (digest(token.encode()), parcel_id, capture_date, expires))
        return {"token": token, "expires_utc": utc(expires), "parcel_id": parcel_id, "capture_date": capture_date}

    def submit(self, raw, token, parcel_id, capture_date, idempotency, filename):
        if not all(isinstance(x, str) and 1 <= len(x) <= 200 for x in (token, parcel_id, capture_date, idempotency, filename)):
            raise ValueError("Missing or invalid submission fields.")
        request_hash = digest(canonical({"byte_hash": digest(raw), "token": token, "parcel_id": parcel_id,
                                        "capture_date": capture_date, "filename": filename}))
        # BEGIN IMMEDIATE serializes consume + duplicate lookup + commit across callers/processes.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            retry = db.execute("SELECT * FROM submissions WHERE idempotency=?", (idempotency,)).fetchone()
            if retry:
                if retry["request_hash"] != request_hash:
                    raise Conflict("This retry key was already used with different evidence.")
                return {**json.loads(retry["report"]), "report_sha256": retry["report_hash"]}, True
            challenge = db.execute("SELECT * FROM challenges WHERE token=?", (digest(token.encode()),)).fetchone()
            if challenge is None:
                raise Conflict("Unknown submission token. Request a new token.")
            if challenge["used_by"]:
                raise Conflict("Submission token was already consumed. Use the original retry key for a transport retry.")
            if challenge["expires"] <= self.clock():
                raise Conflict("Submission token expired. Request a new token.")
            if (challenge["parcel_id"], challenge["capture_date"]) != (parcel_id, capture_date):
                raise Conflict("Submission token does not match this boundary and capture date.")
            meta, preview = inspect_image(raw)
            received = self.clock()
            if challenge["expires"] <= received:
                raise Conflict("Submission token expired while the image was being checked.")
            parcel = json.loads(db.execute("SELECT body FROM parcels WHERE id=?", (parcel_id,)).fetchone()[0])
            exact = [r[0] for r in db.execute("SELECT id FROM submissions WHERE byte_hash=?", (meta["byte_sha256"],))]
            pixels = [r[0] for r in db.execute("SELECT id FROM submissions WHERE pixel_hash=?", (meta["pixel_sha256"],))]
            checks = assess(meta, parcel, capture_date, received, exact, pixels)
            report = {"schema_version": VERSION, "id": secrets.token_hex(12), "received_utc": utc(received),
                      "filename": filename, "declared_capture_date": capture_date, "parcel": parcel,
                      "media": meta, "checks": checks,
                      "status": "needs_review" if any(c["status"] == "FAIL" for c in checks) else "no_conflicts_found",
                      "limitations": ["Findings flag inconsistencies; they do not prove fraud or authenticate editable metadata.",
                          "This is a single-user local demo. Duplicate matching is limited to its retained submissions.",
                          "No proof of freshness, complete coverage, ownership, or persistent animal identity.",
                          "Report verification compares with this server's saved record, not an independent signature."]}
            payload = canonical(report)
            report_hash = digest(payload)
            db.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (report["id"], received, idempotency, request_hash, meta["byte_sha256"], meta["pixel_sha256"],
                 payload.decode(), report_hash, raw, preview))
            db.execute("UPDATE challenges SET used_by=? WHERE token=?", (report["id"], digest(token.encode())))
        return {**report, "report_sha256": report_hash}, False

    def reports(self):
        with self.connect() as db:
            return [{"id": r["id"], "received_utc": utc(r["received"]),
                     "filename": json.loads(r["report"])["filename"], "status": json.loads(r["report"])["status"]}
                    for r in db.execute("SELECT id, received, report FROM submissions ORDER BY received DESC, rowid DESC LIMIT 100")]

    def report(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT report,report_hash FROM submissions WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError("Assessment not found.")
        return {**json.loads(row["report"]), "report_sha256": row["report_hash"]}

    def preview(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT preview FROM submissions WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError("Assessment not found.")
        return row[0]

    def verify(self, exported):
        if not isinstance(exported, dict) or not isinstance(exported.get("id"), str):
            raise ValueError("Supply an exported assessment JSON.")
        try:
            stored = self.report(exported["id"])
        except KeyError:
            return {"status": "INCONCLUSIVE", "message": "No matching assessment in this server's retained records."}
        supplied = dict(exported)
        claimed = supplied.pop("report_sha256", None)
        actual = digest(canonical(supplied))
        stored_claim = stored.pop("report_sha256")
        intact = digest(canonical(stored)) == stored_claim
        ok = intact and actual == stored_claim and claimed == stored_claim
        return {"status": "PASS" if ok else "FAIL", "message":
                "Assessment matches this server's saved record." if ok else "Assessment content or checksum differs from the saved record.",
                "scope": "Local saved-record comparison; not independent capture authentication."}
