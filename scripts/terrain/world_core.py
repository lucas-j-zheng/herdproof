"""Immutable observation preparation and explicit, snapshot-bound review."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

VERSION = "2.0.0"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    with Path(path).open() as stream:
        return json.load(stream)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(canonical(value) + b"\n")
    temp.replace(path)


def load_config(path):
    path = Path(path).resolve()
    cfg = read(path)
    if cfg.get("schema_version") != 2:
        raise ValueError("Expected field schema_version 2")
    if not SAFE_ID.fullmatch(cfg.get("scene_id", "")):
        raise ValueError("Invalid scene_id")
    for key in ("source_image", "detections", "camera", "terrain", "cow_model", "cow_normal"):
        if not (path.parent / cfg[key]).is_file():
            raise ValueError(f"Missing required input {key}: {cfg[key]}")
    if cfg.get("mode", "measured") != "measured":
        raise ValueError("This builder requires measured terrain and a supplied camera; no flat fallback")
    return path.parent, cfg


def pixel_transform(orientation, w, h):
    """Raw pixel centres -> EXIF-normalized pixel centres (all eight orientations)."""
    transforms = {
        1: [[1, 0, 0], [0, 1, 0]], 2: [[-1, 0, w-1], [0, 1, 0]],
        3: [[-1, 0, w-1], [0, -1, h-1]], 4: [[1, 0, 0], [0, -1, h-1]],
        5: [[0, 1, 0], [1, 0, 0]], 6: [[0, -1, h-1], [1, 0, 0]],
        7: [[0, -1, h-1], [-1, 0, w-1]], 8: [[0, 1, 0], [-1, 0, w-1]],
    }
    if orientation not in transforms:
        raise ValueError("Unsupported EXIF orientation")
    return np.array(transforms[orientation] + [[0, 0, 1]], dtype=float)


def source_image(path):
    with Image.open(path) as image:
        w, h = image.size
        orientation = int(image.getexif().get(274, 1))
        rgb = np.array(ImageOps.exif_transpose(image).convert("RGB"))
    return rgb, {"raw_size": [w, h], "size": [rgb.shape[1], rgb.shape[0]],
                 "exif_orientation": orientation,
                 "raw_to_normalized": pixel_transform(orientation, w, h).tolist()}


def checked_box(box):
    a = np.asarray(box, dtype=float)
    if a.shape != (4,) or not np.isfinite(a).all() or np.any(a < 0) or np.any(a > 1):
        raise ValueError("Box must contain four finite normalized coordinates in [0,1]")
    if a[2] <= a[0] or a[3] <= a[1]:
        raise ValueError("Box has no area")
    return a.tolist()


def detections(path, image_hash, meta):
    data = read(path)
    if data.get("image_sha256") != image_hash:
        raise ValueError("Detection image hash does not match the source photograph")
    rows = data.get("observations")
    if not isinstance(rows, list):
        raise ValueError("Detection snapshot requires an observations array with stable IDs")
    result = []
    for row in rows:
        ident = row["id"]
        if not SAFE_ID.fullmatch(ident):
            raise ValueError("Unsafe observation ID")
        box = checked_box(row["box"])
        score = float(row["confidence"])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Invalid detection confidence")
        if data.get("coordinate_space", "normalized_image") == "raw_image":
            w, h = meta["raw_size"]
            nw, nh = meta["size"]
            x1,y1,x2,y2 = np.array(box)*[w,h,w,h]
            points = np.array([[x1,y1,1],[x2,y1,1],[x1,y2,1],[x2,y2,1]],float)
            # Convert pixel edges through the centre-coordinate homography.
            points[:,:2] -= .5
            q = points @ np.array(meta["raw_to_normalized"]).T
            q[:,:2] += .5
            box = checked_box([q[:,0].min()/nw,q[:,1].min()/nh,q[:,0].max()/nw,q[:,1].max()/nh])
        elif data.get("coordinate_space", "normalized_image") != "normalized_image":
            raise ValueError("Unknown detection coordinate space")
        result.append({"id":ident,"box":box,"confidence":score,
                       "provenance":row.get("provenance", "saved model detection")})
    result.sort(key=lambda r:r["id"])
    if len({r["id"] for r in result}) != len(result):
        raise ValueError("Duplicate observation IDs")
    return result, {k:v for k,v in data.items() if k != "observations"}


def crop_bounds(box, width, height, pad=22):
    x1,y1,x2,y2 = np.round(np.array(box)*[width,height,width,height]).astype(int)
    return list(map(int,[max(0,x1-pad),max(0,y1-pad),min(width,x2+pad),min(height,y2+pad)]))


def appearance(rgb, row, strokes=None):
    """Deterministic baseline; quality flags deliberately do not claim probabilities."""
    h,w = rgb.shape[:2]
    bounds = crop_bounds(row["box"],w,h)
    x1,y1,x2,y2 = bounds
    crop = rgb[y1:y2,x1:x2].copy()
    if min(crop.shape[:2]) < 3:
        raise ValueError(f"Observation {row['id']} is too small to crop")
    bh,bw = crop.shape[:2]
    coords = np.round(np.array(row["box"])*[w,h,w,h]).astype(int)-[x1,y1,x1,y1]
    a,b,c,d = np.clip(coords,[1,1,1,1],[bw-1,bh-1,bw-1,bh-1])
    mask = np.zeros((bh,bw),np.uint8)
    mask[b:d,a:c] = cv2.GC_PR_FGD
    flags = []
    if c <= a or d <= b:
        flags.append("tiny_detection")
    for stroke in strokes or []:
        pts = np.round(stroke["points"]).astype(np.int32).reshape(-1,2)
        value = cv2.GC_FGD if stroke["foreground"] else cv2.GC_BGD
        radius = int(stroke["radius"])
        for p in pts:
            cv2.circle(mask,tuple(p),radius,value,-1)
        if len(pts)>1:
            cv2.polylines(mask,[pts],False,value,radius*2)
    cv2.setRNGSeed(int(digest({"row":row,"strokes":strokes})[:7],16))
    try:
        cv2.grabCut(cv2.cvtColor(crop,cv2.COLOR_RGB2BGR),mask,None,
                    np.zeros((1,65)),np.zeros((1,65)),5,cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        flags.append("segmentation_failed")
    foreground = np.isin(mask,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.uint8)
    count = int(foreground.sum())
    if count < 12:
        flags.append("insufficient_foreground")
    if any(v <= .0001 or v >= .9999 for v in row["box"]):
        flags.append("clipped_detection")
    if count > .8*crop.shape[0]*crop.shape[1]:
        flags.append("foreground_may_include_background")
    interior = cv2.erode(foreground,np.ones((3,3),np.uint8))
    samples = crop[(interior if interior.sum()>=12 else foreground)>0]
    if len(samples):
        color = np.median(samples,axis=0).round().astype(int)
        percentiles = np.percentile(samples,[10,50,90],axis=0).round().astype(int).tolist()
    else:
        color = np.array([160,151,131]);percentiles = []
    if count and np.mean((samples[:,1]>samples[:,0]*1.15)&(samples[:,1]>samples[:,2]*1.15))>.35:
        flags.append("possible_grass_contamination")
    yy,xx = np.where(foreground>0)
    elongation = 0.;angle = 0.
    if len(xx)>=3:
        covariance = np.cov(np.column_stack([xx,yy]),rowvar=False)
        vals,vecs = np.linalg.eigh(covariance)
        axis = vecs[:,-1]
        angle = float(np.degrees(np.arctan2(axis[1],axis[0]))%180)
        elongation = float(1-vals[0]/max(vals[-1],1e-9))
    if elongation<.45:
        flags.append("uncertain_body_axis")
    return {"crop_bounds":bounds,"coat_color":"#"+"".join(f"{v:02x}" for v in color),
            "color_percentiles":percentiles,"foreground_pixels":count,
            "axis_degrees":angle,"axis_quality":elongation,"quality_flags":flags,
            "appearance_method":"OpenCV GrabCut; foreground median sRGB; PCA undirected axis",
            "head_status":"unknown"}, crop, foreground*255


def prepare(config_path):
    base,cfg = load_config(config_path)
    rgb,meta = source_image(base/cfg["source_image"])
    image_hash = sha(base/cfg["source_image"])
    rows,model = detections(base/cfg["detections"],image_hash,meta)
    binding = {"image_sha256":image_hash,"image":meta,"detections":rows,"model":model,
               "algorithm_version":VERSION}
    snapshot = digest(binding)
    folder = base/cfg.get("prepared","prepared")/snapshot
    path = folder/"observations.json"
    if path.exists():
        cached = read(path)
        if cached.get("snapshot")!=snapshot:
            raise ValueError("Prepared snapshot corruption")
        for row in cached["observations"]:
            for key in ("crop_file","mask_file"):
                if sha(folder/row[key]) != row[key+"_sha256"]:
                    raise ValueError("Prepared appearance cache corruption")
        return cached,folder
    folder.mkdir(parents=True,exist_ok=True)
    for row in rows:
        proposal,crop,mask = appearance(rgb,row)
        row.update(proposal)
        row["crop_file"] = row["id"]+".png"
        row["mask_file"] = row["id"]+"-mask.png"
        Image.fromarray(crop).save(folder/row["crop_file"])
        Image.fromarray(mask).save(folder/row["mask_file"])
        for key in ("crop_file","mask_file"):
            row[key+"_sha256"] = sha(folder/row[key])
    result = {"schema_version":2,"snapshot":snapshot,"binding":binding,
              "observations":rows,"image":meta,"image_sha256":image_hash,"model":model}
    # Binding must contain only the unmodified detection input records.
    result["binding"]["detections"],_ = detections(base/cfg["detections"],image_hash,meta)
    write(path,result)
    return result,folder


def default_review(snapshot):
    return {"schema_version":2,"snapshot":snapshot,"revision":0,"observations":{},
            "additions":[],"cleanup_boxes":[],"vegetation":{}}


def validate_review(review, prepared):
    if review.get("schema_version")!=2 or review.get("snapshot")!=prepared["snapshot"]:
        raise ValueError("Review belongs to a different image/detection snapshot; explicitly migrate it")
    if not isinstance(review.get("revision"),int) or review["revision"]<0:
        raise ValueError("Invalid review revision")
    known = {r["id"]:r for r in prepared["observations"]}
    if len(review.get("additions",[]))>1000:
        raise ValueError("Too many manual observations")
    for row in review.get("additions",[]):
        if not SAFE_ID.fullmatch(row["id"]) or row["id"] in known:
            raise ValueError("Invalid or repeated manual observation ID")
        checked_box(row["box"])
        known[row["id"]] = row
    allowed = {"status","reason","merge_into","coat_color","axis_degrees","head_status",
               "anchor_pixel","body_height_m","mask_strokes","reviewer"}
    for ident,edit in review.get("observations",{}).items():
        if ident not in known:
            raise ValueError(f"Review refers to unknown observation {ident}")
        if set(edit)-allowed:
            raise ValueError("Unknown review properties: "+str(set(edit)-allowed))
        if edit.get("status","unreviewed") not in ("accepted","rejected","unreviewed"):
            raise ValueError("Invalid review status")
        if edit.get("merge_into"):
            target=edit["merge_into"]
            if target not in known or target==ident or edit.get("status")!="rejected":
                raise ValueError("Merge requires a different existing target and rejected source")
            target_edit=review["observations"].get(target,{})
            if target_edit.get("status")=="rejected":
                raise ValueError("Cannot merge into a rejected observation")
        if "coat_color" in edit and not re.fullmatch(r"#[0-9a-fA-F]{6}",edit["coat_color"]):
            raise ValueError("Invalid coat color")
        if "axis_degrees" in edit and not math.isfinite(float(edit["axis_degrees"])):
            raise ValueError("Nonfinite heading")
        if edit.get("head_status","unknown") not in ("unknown","reviewed"):
            raise ValueError("Invalid head status")
        if "body_height_m" in edit and not .1<=float(edit["body_height_m"])<=3:
            raise ValueError("Body-height assumption outside supported range")
        if "anchor_pixel" in edit:
            a=np.array(edit["anchor_pixel"],float)
            if a.shape!=(2,) or not np.isfinite(a).all() or np.any(a<0) or np.any(a>=prepared["image"]["size"]):
                raise ValueError("Anchor lies outside source image")
        bounds=crop_bounds(known[ident]["box"],*prepared["image"]["size"])
        for stroke in edit.get("mask_strokes",[]):
            pts=np.array(stroke["points"],float)
            if pts.ndim!=2 or pts.shape[1]!=2 or not 1<=len(pts)<=10000 or not np.isfinite(pts).all():
                raise ValueError("Invalid mask stroke")
            if np.any(pts<0) or np.any(pts>=[bounds[2]-bounds[0],bounds[3]-bounds[1]]):
                raise ValueError("Mask stroke outside observation crop")
            if not isinstance(stroke["foreground"],bool) or not 1<=int(stroke["radius"])<=64:
                raise ValueError("Invalid mask brush")
    for box in review.get("cleanup_boxes",[]):
        checked_box(box)
    vegetation=review.get("vegetation",{})
    if set(vegetation)-{"type","height_m","density"}:
        raise ValueError("Unknown vegetation parameters")
    if vegetation.get("type","pasture") not in ("pasture","crop","bare"):
        raise ValueError("Invalid cover type")
    if not 0<=float(vegetation.get("height_m",.3))<=2 or not 0<=float(vegetation.get("density",1))<=2:
        raise ValueError("Invalid vegetation height or density")
    canonical(review)
    return review


def load_review(base,cfg,prepared):
    path=base/cfg.get("review","review.json")
    review=read(path) if path.exists() else default_review(prepared["snapshot"])
    return validate_review(review,prepared)
