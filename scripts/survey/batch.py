"""Bounded photo batches and an explicitly approximate, planar survey map.

Camera metadata supplies an initial placement; background registration can refine
nearby overlapping views. Neither method authenticates capture or orthorectifies
terrain. Original evidence never comes from the rendered map.
"""
from __future__ import annotations

from datetime import datetime
import io
import json
import math
import re
import secrets
import threading

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

from aerial_survey import Config, frame_polygon, register, transform
from survey.core import Conflict, GEOD, TO_MAP, canonical, inspect_image, utc

MAX_PHOTOS = 24
MAP_LIMIT = "Approximate photo placement: editable camera GPS, lens and pose; flat ground at takeoff elevation. Check alignment against field edges. This is not a terrain-corrected orthomosaic or proof of complete coverage."


def initial_placement(raw, meta):
    """Project near-nadir DJI image corners onto a ground plane, with no defaults
    for missing camera parameters. Corner order follows the cleaned preview.
    """
    def unplaced(reason):
        return {"status": "unplaced", "reason": reason, "corners": None}

    if not meta["gps"]:
        return unplaced("No GPS. Keep this photo as evidence; it cannot be placed automatically.")
    lon, lat = meta["gps"]["longitude"], meta["gps"]["latitude"]
    if not -5.5 <= lon <= 10.5 or not 41 <= lat <= 52:
        return unplaced("Outside this local demo's France map projection.")
    if meta.get("orientation") != 1:
        return unplaced("Rotated camera pixels need a supported camera calibration.")
    try:
        xmp = dict(re.findall(r'drone-dji:(\w+)="([^"\r\n]{1,300})"', raw[:200000].decode("latin1")))
        altitude, yaw, pitch, roll = [float(xmp[k]) for k in
            ("RelativeAltitude", "GimbalYawDegree", "GimbalPitchDegree", "GimbalRollDegree")]
        with Image.open(io.BytesIO(raw)) as image:
            focal35 = float(image.getexif().get_ifd(34665)[41989])
        if not all(math.isfinite(x) for x in (altitude, yaw, pitch, roll, focal35)):
            raise ValueError
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
        return unplaced("GPS found; lens, altitude or DJI camera direction is missing. Only a camera point is available.")
    if not (5 <= altitude <= 500 and -90.1 <= pitch <= -75 and abs(roll) <= 5 and abs(yaw) <= 360 and 10 <= focal35 <= 150):
        return unplaced("Camera pose is outside the supported near-vertical, 5–500 m survey range.")

    yaw, pitch, roll = np.radians([yaw, pitch, roll])
    right = np.array([math.cos(yaw), -math.sin(yaw), 0])
    forward = np.array([math.cos(pitch)*math.sin(yaw), math.cos(pitch)*math.cos(yaw), math.sin(pitch)])
    down = np.cross(forward, right)
    right, down = right*math.cos(roll)+down*math.sin(roll), -right*math.sin(roll)+down*math.cos(roll)
    width, height = meta["width"], meta["height"]
    focal_px = focal35 * math.hypot(width, height) / math.hypot(36, 24)
    pixels = np.array([[0, 0], [width, 0], [width, height], [0, height]])
    rays = forward + (pixels[:, 0:1]-width/2)/focal_px*right + (pixels[:, 1:2]-height/2)/focal_px*down
    if np.any(rays[:, 2] >= -.1):
        return unplaced("Some image rays miss the supported ground plane.")
    offsets = rays[:, :2] * (-altitude/rays[:, 2:3])
    corners = []
    for east, north in offsets:
        x, y, _ = GEOD.fwd(lon, lat, math.degrees(math.atan2(east, north)), math.hypot(east, north))
        corners.append(list(TO_MAP.transform(x, y)))
    return {"status": "approximate", "reason": "Camera metadata placement; alignment needs review.",
            "corners": corners, "initial_corners": corners, "relative_altitude_m": altitude,
            "focal_35mm": focal35, "method": "camera_metadata_ground_plane"}


def features(preview):
    rgb = cv2.cvtColor(cv2.imdecode(np.frombuffer(preview, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    keypoints, descriptors = cv2.SIFT_create(nfeatures=6000).detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), None)
    return {"rgb": rgb, "descriptors": descriptors,
            "points": np.asarray([p.pt for p in keypoints], np.float32).reshape(-1, 2)}


def nearby(a, b):
    ta, tb = a["meta"]["captured_local"], b["meta"]["captured_local"]
    if not ta or not tb or ta[:10] != tb[:10]:
        return False
    return (abs((datetime.fromisoformat(ta)-datetime.fromisoformat(tb)).total_seconds()) <= 30
            and np.linalg.norm(np.array(a["meta"]["map_point"])-b["meta"]["map_point"]) <= 160)


def compose(items, progress=lambda text: None):
    """Place all usable images, refine at most three neighbours per image, and
    preserve transparent gaps. Work and output raster size are bounded.
    """
    placed = [p for p in items if p["placement"]["corners"]]
    placed.sort(key=lambda p: (p["meta"]["captured_local"] or "", p["ordinal"]))
    if placed:
        all_corners = np.concatenate([p["placement"]["corners"] for p in placed])
        if np.max(np.ptp(all_corners, axis=0)) > 5000:
            raise ValueError("This batch spans more than 5 km. Upload one local survey at a time.")
        # Anchor near the middle of the flight and grow outward, limiting drift
        # and avoiding a turn at the beginning as the only global reference.
        anchor = placed[len(placed)//2]
        centre = np.array(anchor["meta"]["map_point"])
        placed.sort(key=lambda p: (p is not anchor, np.linalg.norm(np.array(p["meta"]["map_point"])-centre)))
    frames, matrices, depths, links = {}, {}, {}, []
    for index, item in enumerate(placed):
        ident = item["id"]
        progress(f"Linking photo {index+1} of {len(placed)}…")
        frame = frames[ident] = features(item["preview"])
        corners = np.array(item["placement"]["initial_corners"], np.float64)
        # Estimate in a local metric frame to avoid float32 rounding at 6.6M northing.
        origin = corners.mean(axis=0)
        shift = np.array([[1, 0, origin[0]], [0, 1, origin[1]], [0, 0, 1]])
        initial = shift @ cv2.getPerspectiveTransform(frame_polygon(frame), (corners-origin).astype(np.float32))
        best = None
        candidates = [p for p in placed[:index] if nearby(item, p) and depths[p["id"]] < 4][-3:]
        for prior in candidates:
            result = register(frame, frames[prior["id"]], Config())
            if not result["accepted"]:
                continue
            refined = matrices[prior["id"]] @ np.array(result["homography_a_to_b"])
            new_corners = transform(frame_polygon(frame), refined)
            new_poly, old_poly = Polygon(new_corners), Polygon(corners)
            adjustment = float(np.max(np.linalg.norm(new_corners-corners, axis=1)))
            if (not new_poly.is_valid or not .6 <= new_poly.area/old_poly.area <= 1.7 or adjustment > 35):
                continue
            if best is None or result["inliers"] > best[0]["inliers"]:
                best = result, prior, refined, new_corners, adjustment
        matrices[ident], depths[ident] = initial, 0
        if best:
            result, prior, matrices[ident], refined_corners, adjustment = best
            depths[ident] = depths[prior["id"]] + 1
            item["placement"].update(corners=refined_corners.tolist(), method="background_linked_ground_plane",
                                     reason="Overlapping background linked; global map position remains approximate.")
            links.append({"photo_id": ident, "reference_id": prior["id"], "inliers": result["inliers"],
                          "median_error_px": result["median_error_px"], "maximum_adjustment_m": adjustment})

    result = {"placed": len(placed), "unplaced": len(items)-len(placed), "links": links,
              "bounds": None, "coverage": None, "limitation": MAP_LIMIT}
    if not placed:
        return result, None
    coverage = unary_union([Polygon(p["placement"]["corners"]) for p in placed])
    west, south, east, north = coverage.bounds
    scale = min(6, 1800 / max(east-west, north-south))
    width, height = math.ceil((east-west)*scale)+2, math.ceil((north-south)*scale)+2
    # Pixel bounds are exact, including the final partial metre at the raster edge.
    east, south = west + width/scale, north - height/scale
    raster = np.zeros((height, width, 4), np.uint8)
    best_weight = np.zeros((height, width), np.float32)
    to_raster = np.array([[scale, 0, -west*scale], [0, -scale, north*scale], [0, 0, 1]])
    for index, item in enumerate(placed):
        progress(f"Filling map with photo {index+1} of {len(placed)}…")
        frame = frames[item["id"]]
        h, w = frame["rgb"].shape[:2]
        y, x = np.mgrid[:h, :w]
        weight = np.minimum.reduce([x+1, w-x, y+1, h-y]).astype(np.float32)
        weight /= weight.max()
        matrix = to_raster @ matrices[item["id"]]
        warped = cv2.warpPerspective(frame["rgb"], matrix, (width, height))
        weights = cv2.warpPerspective(weight, matrix, (width, height))
        use = weights > best_weight
        raster[use, :3] = warped[use]
        raster[use, 3] = 255
        best_weight[use] = weights[use]
    output = io.BytesIO()
    Image.fromarray(raster).save(output, "PNG")
    result.update(bounds=[west, south, east, north], coverage=mapping(coverage), area_ha=coverage.area/10000)
    return result, output.getvalue()


class Batches:
    def __init__(self, store):
        self.store = store
        self.worker_lock = threading.Lock()
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS survey_batches(id TEXT PRIMARY KEY, created REAL, status TEXT,
                    message TEXT, result TEXT, mosaic BLOB);
                CREATE TABLE IF NOT EXISTS survey_photos(id TEXT PRIMARY KEY, batch_id TEXT, ordinal INTEGER,
                    filename TEXT, byte_hash TEXT, metadata TEXT, placement TEXT, media BLOB, preview BLOB,
                    UNIQUE(batch_id, byte_hash));
            """)
            db.execute("UPDATE survey_batches SET status='failed', message='Map build interrupted by server restart. Rebuild to continue.' WHERE status='building'")

    def create(self):
        ident = secrets.token_hex(12)
        with self.store.connect() as db:
            db.execute("INSERT INTO survey_batches VALUES(?,?,'draft','Add photographs to this survey.',NULL,NULL)", (ident, self.store.clock()))
        return self.get(ident)

    def recent(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,status,created,(SELECT COUNT(*) FROM survey_photos WHERE batch_id=survey_batches.id) AS count FROM survey_batches ORDER BY created DESC LIMIT 20")]

    def get(self, ident):
        if not isinstance(ident, str):
            raise ValueError("Choose a survey batch.")
        with self.store.connect() as db:
            row = db.execute("SELECT id,created,status,message,result FROM survey_batches WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise KeyError("Survey batch not found.")
            photos = db.execute("SELECT id,ordinal,filename,metadata,placement FROM survey_photos WHERE batch_id=? ORDER BY ordinal", (ident,)).fetchall()
        return {"id": ident, "created_utc": utc(row["created"]), "status": row["status"], "message": row["message"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "photos": [{"id": p["id"], "ordinal": p["ordinal"], "filename": p["filename"],
                            "meta": json.loads(p["metadata"]), "placement": json.loads(p["placement"])} for p in photos]}

    def add(self, ident, raw, filename):
        if not isinstance(filename, str) or not 1 <= len(filename) <= 200:
            raise ValueError("Use a filename of 1–200 characters.")
        self.get(ident)
        meta, preview = inspect_image(raw)
        placement = initial_placement(raw, meta)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute("SELECT id FROM survey_photos WHERE batch_id=? AND byte_hash=?", (ident, meta["byte_sha256"])).fetchone()
            if duplicate:
                return {"photo_id": duplicate[0], "duplicate": True}
            status = db.execute("SELECT status FROM survey_batches WHERE id=?", (ident,)).fetchone()[0]
            if status != "draft":
                raise Conflict("This batch is closed. Start a new batch to add photos.")
            count = db.execute("SELECT COUNT(*) FROM survey_photos WHERE batch_id=?", (ident,)).fetchone()[0]
            if count >= MAX_PHOTOS:
                raise ValueError(f"Use at most {MAX_PHOTOS} photographs per demo survey.")
            photo_id = secrets.token_hex(12)
            db.execute("INSERT INTO survey_photos VALUES(?,?,?,?,?,?,?,?,?)", (photo_id, ident, count, filename,
                meta["byte_sha256"], canonical(meta).decode(), canonical(placement).decode(), raw, preview))
        return {"photo_id": photo_id, "duplicate": False}

    def photo(self, ident, photo_id, preview=False):
        if not all(isinstance(x, str) for x in (ident, photo_id)):
            raise ValueError("Choose a photo from a survey batch.")
        with self.store.connect() as db:
            column = "preview" if preview else "media"
            row = db.execute(f"SELECT {column},filename FROM survey_photos WHERE batch_id=? AND id=?", (ident, photo_id)).fetchone()
        if row is None:
            raise KeyError("Survey photograph not found.")
        return row[0], row[1]

    def mosaic(self, ident):
        with self.store.connect() as db:
            row = db.execute("SELECT mosaic FROM survey_batches WHERE id=? AND status='ready'", (ident,)).fetchone()
        if row is None or row[0] is None:
            raise KeyError("No placed imagery in this batch.")
        return row[0]

    def build(self, ident):
        batch = self.get(ident)
        if batch["status"] in {"ready", "building"}:
            return batch
        if not batch["photos"]:
            raise ValueError("Add at least one photograph first.")
        if not self.worker_lock.acquire(blocking=False):
            raise Conflict("Another survey map is processing. Try Build map when it finishes.")
        try:
            with self.store.connect() as db:
                db.execute("UPDATE survey_batches SET status='building',message='Preparing photo map…' WHERE id=?", (ident,))
            threading.Thread(target=self._run, args=(ident,), daemon=True).start()
        except Exception:
            self.worker_lock.release()
            raise
        return self.get(ident)

    def _run(self, ident):
        try:
            items = self.get(ident)["photos"]
            for item in items:
                item["preview"] = self.photo(ident, item["id"], preview=True)[0]
            def progress(message):
                with self.store.connect() as db:
                    db.execute("UPDATE survey_batches SET message=? WHERE id=?", (message, ident))
            result, mosaic = compose(items, progress)
            with self.store.connect() as db:
                for item in items:
                    db.execute("UPDATE survey_photos SET placement=? WHERE id=?", (canonical(item["placement"]).decode(), item["id"]))
                db.execute("UPDATE survey_batches SET status='ready',message=?,result=?,mosaic=? WHERE id=?",
                           (f"{result['placed']} of {len(items)} photos placed on the map.", canonical(result).decode(), mosaic, ident))
        except Exception as error:
            with self.store.connect() as db:
                db.execute("UPDATE survey_batches SET status='failed',message=? WHERE id=?", (f"Map build failed: {error}", ident))
        finally:
            self.worker_lock.release()

    def coverage(self, ident, parcel_id):
        batch = self.get(ident)
        parcel = self.store.parcel(parcel_id)
        if batch["status"] != "ready" or not batch["result"]["coverage"]:
            return {"percent": None, "message": "No photo footprints are available to compare with this boundary."}
        polygon = Polygon(parcel["map_vertices"])
        covered = polygon.intersection(shape(batch["result"]["coverage"]))
        return {"percent": round(covered.area/polygon.area*100, 1), "parcel_id": parcel_id,
                "boundary_sha256": parcel["sha256"], "message": "Estimated boundary area under photo footprints. Placement errors, terrain and hidden ground are not measured; complete coverage remains unverified."}
