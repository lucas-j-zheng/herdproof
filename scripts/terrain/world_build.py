"""Offline, deterministic export and independent scene verification."""
from __future__ import annotations

import json
import inspect
import math
import os
import platform
import shutil
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from world_core import (VERSION, appearance, canonical, digest, load_config,
                        load_review, prepare, read, sha, source_image, write)
from world_geometry import load_geometry

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
VIEWER=ROOT/"validation/world-viewer"
INPUT_KEYS=("source_image","detections","terrain","camera","reference_ortho",
            "source_manifest","cow_model","cow_normal","features","texture_masks")
LOADED_CODE={str(p):sha(p) for p in HERE.glob("world*.py")}


def input_fingerprint(base,cfg):
    return {key:sha(base/cfg[key]) for key in INPUT_KEYS if cfg.get(key)}


def lock_inputs(base,cfg):
    value={"files":input_fingerprint(base,cfg),
           "config":digest({k:v for k,v in cfg.items() if k not in ("output","prepared","review")})}
    write(base/"inputs.lock.json",value)
    return value


def check_inputs(base,cfg):
    path=base/"inputs.lock.json"
    if not path.exists():
        raise ValueError("Inputs have not been locked. Run prepare first")
    expected=read(path)
    current={"files":input_fingerprint(base,cfg),
             "config":digest({k:v for k,v in cfg.items() if k not in ("output","prepared","review")})}
    if current!=expected:
        raise ValueError("Input/configuration lock changed. Inspect changes and explicitly run prepare --refresh-inputs")
    return current


def effective_observations(rgb,prepared,folder,review):
    rows=[]
    originals=prepared["observations"]+[{**r,"confidence":None,"provenance":"manual addition"} for r in review["additions"]]
    for raw in originals:
        ident=raw["id"];edit=review["observations"].get(ident,{})
        row=dict(raw)
        if edit.get("mask_strokes") or "crop_file" not in raw:
            key=digest({"snapshot":prepared["snapshot"],"row":raw,"strokes":edit.get("mask_strokes",[])})
            cache=folder/"review-cache"/key
            if (cache/"proposal.json").exists():
                proposal=read(cache/"proposal.json")
                crop=np.array(Image.open(cache/"crop.png"));mask=np.array(Image.open(cache/"mask.png"))
                if digest({"crop":sha(cache/"crop.png"),"mask":sha(cache/"mask.png")})!=proposal.pop("cache_hash"):
                    raise ValueError("Reviewed mask cache corrupted")
            else:
                proposal,crop,mask=appearance(rgb,row,edit.get("mask_strokes"))
                cache.mkdir(parents=True,exist_ok=True)
                Image.fromarray(crop).save(cache/"crop.png");Image.fromarray(mask).save(cache/"mask.png")
                write(cache/"proposal.json",{**proposal,"cache_hash":digest({"crop":sha(cache/"crop.png"),"mask":sha(cache/"mask.png")})})
            row.update(proposal)
        else:
            crop=np.array(Image.open(folder/raw["crop_file"]))
            mask=np.array(Image.open(folder/raw["mask_file"]))
        row["proposal"]={k:row[k] for k in ("coat_color","axis_degrees","head_status","quality_flags","axis_quality")}
        row.update(edit)
        row["status"]=edit.get("status","unreviewed")
        rows.append((row,crop,mask))
    return sorted(rows,key=lambda item:item[0]["id"])


def texture(rgb,rows,review,cfg,base,terrain,camera,out):
    h,w=rgb.shape[:2]
    mask=np.zeros((h,w),np.uint8)
    cleanup=list(review["cleanup_boxes"])
    if cfg.get("texture_masks"):
        cleanup+=read(base/cfg["texture_masks"])["boxes_normalized"]
    # Rectangles include likely shadows. Rejected non-cows are left unchanged.
    cleanup += [row["box"] for row,_,_ in rows if row["status"]!="rejected" or row.get("merge_into")]
    padding=cfg.get("texture_padding",[24,24,70,35])
    for box in cleanup:
        x1,y1,x2,y2=np.round(np.array(box)*[w,h,w,h]).astype(int)
        cv2.rectangle(mask,(max(0,x1-padding[0]),max(0,y1-padding[1])),
                      (min(w-1,x2+padding[2]),min(h-1,y2+padding[3])),255,-1)
    image_width=min(w,int(cfg.get("texture_working_width",2640)))
    small=cv2.resize(rgb,(image_width,round(h*image_width/w)),interpolation=cv2.INTER_AREA)
    smask=cv2.resize(mask,(small.shape[1],small.shape[0]),interpolation=cv2.INTER_NEAREST)
    clean=cv2.inpaint(small,smask,9,cv2.INPAINT_TELEA)
    Image.fromarray(mask).save(out/"texture-repair-mask.png")
    reference=np.array(Image.open(base/cfg["reference_ortho"]).convert("RGB")) if cfg.get("reference_ortho") else None
    if reference is not None:
        rmask=np.zeros(reference.shape[:2],np.uint8)
        for box in cfg.get("reference_cleanup_boxes",[]):
            from world_core import checked_box
            x1,y1,x2,y2=np.round(np.array(checked_box(box))*[reference.shape[1],reference.shape[0],reference.shape[1],reference.shape[0]]).astype(int)
            cv2.rectangle(rmask,(x1,y1),(x2,y2),255,-1)
        if rmask.any():reference=cv2.inpaint(reference,rmask,7,cv2.INPAINT_TELEA)
        Image.fromarray(rmask).save(out/"reference-repair-mask.png")
    size=int(cfg.get("atlas_resolution",2048))
    if not 128<=size<=8192:
        raise ValueError("Atlas resolution must be between 128 and 8192")
    atlas=np.full((size,size,3),[122,128,105],np.uint8)
    observed=np.zeros((size,size),np.uint8)
    for row in range(0,size,128):
        xs=terrain.min_x+(np.arange(size)+.5)*(terrain.max_x-terrain.min_x)/size
        zs=terrain.min_z+(np.arange(row,min(row+128,size))+.5)*(terrain.max_z-terrain.min_z)/size
        x,z=np.meshgrid(xs,zs);y=terrain.sample(x,z,True);valid_terrain=np.isfinite(y)
        uv,depth=camera.project(np.stack([x,np.nan_to_num(y),z],axis=-1))
        u,v=uv[:,:,0],uv[:,:,1]
        valid=(u>=0)&(u<w-1)&(v>=0)&(v<h-1)&(depth>0)&valid_terrain
        sampled=cv2.remap(clean,((u+.5)*clean.shape[1]/w-.5).astype('f4'),
                          ((v+.5)*clean.shape[0]/h-.5).astype('f4'),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
        background=np.full_like(sampled,[122,128,105])
        if reference is not None:
            xmin,ymin,xmax,ymax=cfg["reference_bounds"]
            a=((x+terrain.origin[0]-xmin)/(xmax-xmin)*reference.shape[1]-.5).astype('f4')
            b=((ymax-(-z+terrain.origin[1]))/(ymax-ymin)*reference.shape[0]-.5).astype('f4')
            if np.any((a<-.51)|(a>reference.shape[1]-.49)|(b<-.51)|(b>reference.shape[0]-.49)):
                raise ValueError("Reference imagery does not cover requested terrain; supply a larger reference or smaller window")
            background=cv2.remap(reference,a,b,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        weight=np.clip(np.minimum.reduce([u,w-1-u,v,h-1-v])/90,0,1)*valid
        atlas[row:row+len(zs)]=(sampled*weight[:,:,None]+background*(1-weight[:,:,None])).round().astype(np.uint8)
        observed[row:row+len(zs)]=valid*255
    Image.fromarray(atlas).save(out/"ground.jpg",quality=94)
    Image.fromarray(observed).save(out/"observed.png")
    Image.fromarray(atlas).resize((512,512),Image.Resampling.BOX).save(out/"landcover.jpg",quality=97)
    return {"method":"Saved observation/cleanup boxes with local inpainting; inferred appearance",
            "masked_source_fraction":float((mask>0).mean()),"cleanup_boxes":len(cleanup),
            "observed_terrain_fraction":float((observed>0).mean()),"mask_file":"texture-repair-mask.png"}


def copy_viewer(out):
    for file in VIEWER.iterdir():
        if file.suffix in (".js",".css",".html") or file.name=="ASSETS.json":
            shutil.copy2(file,out/file.name)
    vendor=out/"vendor";vendor.mkdir()
    modules=ROOT/"validation/terrain-demo/node_modules"
    for src,dest in ((modules/"three/build",vendor/"three/build"),
                     (modules/"three/examples/jsm",vendor/"three/examples/jsm"),
                     (modules/"@dimforge/rapier3d-compat",vendor/"rapier")):
        if not src.exists():
            raise ValueError("Missing viewer dependencies; use the documented frozen pnpm install")
        shutil.copytree(src,dest,ignore=shutil.ignore_patterns("*.map","*.d.ts","*.ts","node_modules"))
    for name,src in (("three",modules/"three/LICENSE"),("rapier",modules/"@dimforge/rapier3d-compat/LICENSE")):
        if src.exists():shutil.copy2(src,vendor/(name+"-LICENSE"))


def cached_texture(rgb,rows,review,cfg,base,terrain,camera,stage,locked,folder):
    """Coat/head/vegetation edits reuse ground imagery instead of repainting it."""
    binding={"inputs":{k:v for k,v in locked["files"].items() if k in ("source_image","terrain","camera","reference_ortho","texture_masks")},
             "parameters":{k:cfg.get(k) for k in ("origin_enu","terrain_window","atlas_resolution","texture_working_width","texture_padding","reference_bounds","reference_cleanup_boxes")},
             "cleanup_boxes":review["cleanup_boxes"],
             "cow_boxes":[r["box"] for r,_,_ in rows if r["status"]!="rejected" or r.get("merge_into")],
             "algorithm":digest(inspect.getsource(texture)),
             "geometry_algorithm":sha(HERE/"world_geometry.py"),
             "packages":{p:version(p) for p in ("numpy","opencv-python-headless","pillow")}}
    cache=folder/"textures"/digest(binding);manifest=cache/"manifest.json"
    if manifest.exists():
        saved=read(manifest)
        for name,expected in saved["files"].items():
            if sha(cache/name)!=expected:raise ValueError("Ground texture cache corrupted")
            shutil.copy2(cache/name,stage/name)
        return saved["repair"]
    repair=texture(rgb,rows,review,cfg,base,terrain,camera,stage)
    cache.mkdir(parents=True,exist_ok=True)
    names=["ground.jpg","landcover.jpg","observed.png","texture-repair-mask.png","reference-repair-mask.png"]
    files={}
    for name in names:
        if (stage/name).exists():shutil.copy2(stage/name,cache/name);files[name]=sha(cache/name)
    write(manifest,{"files":files,"repair":repair})
    return repair


def build(config_path,output=None):
    started=time.perf_counter();base,cfg=load_config(config_path)
    if any(not Path(p).is_file() or sha(p)!=expected for p,expected in LOADED_CODE.items()):
        raise ValueError("Builder source changed after this process started; restart the review server")
    locked=check_inputs(base,cfg)
    prepared,folder=prepare(config_path)
    review=load_review(base,cfg,prepared)
    terrain,camera=load_geometry(base,cfg,prepared)
    rgb,_=source_image(base/cfg["source_image"])
    rows=effective_observations(rgb,prepared,folder,review)
    dest=Path(output).resolve() if output else (base/cfg.get("output","build")).resolve()
    if dest==base or dest in base.parents or dest in (base/cfg["source_image"]).resolve().parents:
        raise ValueError("Output must be a dedicated directory separate from input files")
    if dest.exists() and (not (dest/"build-manifest.json").exists() or read(dest/"scene.json")["scene_id"]!=cfg["scene_id"]):
        raise ValueError("Refusing to replace a directory that is not this scene's previous build")
    dest.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".world-stage-",dir=dest.parent))
    try:
        (stage/"cows").mkdir();(stage/"assets").mkdir()
        terrain.heights.tofile(stage/"heights.bin");terrain.valid.tofile(stage/"valid.bin")
        original_name="original"+Path(cfg["source_image"]).suffix.lower()
        shutil.copy2(base/cfg["source_image"],stage/original_name)
        Image.fromarray(rgb).save(stage/"source.jpg",quality=98)
        cows=[];all_rows=[];failures=[]
        for row,crop,mask in rows:
            ident=row["id"]
            Image.fromarray(crop).save(stage/"cows"/(ident+".png"))
            Image.fromarray(mask).save(stage/"cows"/(ident+"-mask.png"))
            row={k:v for k,v in row.items() if not k.startswith("crop_file") and not k.startswith("mask_file")}
            row.update(source_crop=f"cows/{ident}.png",mask_file=f"cows/{ident}-mask.png")
            all_rows.append(row)
            if row["status"]=="rejected":continue
            w,h=prepared["image"]["size"]
            box=np.array(row["box"])*[w,h,w,h]
            anchor=row.get("anchor_pixel",((box[:2]+box[2:])/2).tolist())
            body=float(row.get("body_height_m",cfg.get("cow_body_height_m",1.25)))
            try:
                position=camera.hit(anchor,body)
                theta=math.radians(float(row["axis_degrees"]))
                d=np.array([math.cos(theta),math.sin(theta)])
                a=np.array(camera.hit(np.array(anchor)-d*5,body))
                b=np.array(camera.hit(np.array(anchor)+d*5,body))
                yaw=float(math.atan2(b[0]-a[0],b[2]-a[2]))
            except ValueError as error:
                failures.append({"id":ident,"error":str(error)});continue
            cows.append({**row,"sceneCowId":ident,"animalId":None,"trackId":None,
                         "source_image":original_name,"source_pixel":anchor,"position":position,
                         "body_height_assumption_m":body,"yaw":yaw,"candidate_index":len(cows),
                         "heading_status":"reviewed head direction" if row["head_status"]=="reviewed" else "ambiguous head/tail; estimated body axis",
                         "coat":"Observed apparent coat; hidden markings estimated","camera_id":cfg["scene_id"]})
        if failures:
            write(base/"placement-errors.json",failures)
            raise ValueError("Invalid cow placements; correct camera/terrain or reject observations: "+", ".join(f["id"] for f in failures))
        repair=cached_texture(rgb,rows,review,cfg,base,terrain,camera,stage,locked,folder)
        features=read(base/cfg["features"]) if cfg.get("features") else {}
        def placed(value):
            if "source_pixel" in value:return camera.hit(value["source_pixel"])
            point=list(value["position"])
            point[1]=float(terrain.sample(point[0],point[2]));return point
        vegetation={"type":"pasture","height_m":.25,"density":1,**cfg.get("vegetation",{}),**review["vegetation"]}
        scene={"schema_version":2,"scene_id":cfg["scene_id"],"name":cfg["name"],"title":cfg["name"],
               "date":cfg.get("captured",""),"snapshot":prepared["snapshot"],"units":"metres",
               "origin":dict(zip(("easting","northing","altitude"),cfg["origin_enu"])),
               "horizontal_crs":cfg["horizontal_crs"],"vertical_reference":cfg["vertical_reference"],
               "terrain":terrain.spec(),"camera":camera.data,"cows":cows,"detectionReview":all_rows,
               "image":prepared["image"],"source_image":original_name,"source_image_sha256":prepared["image_sha256"],
               "fences":[[placed(p) for p in path] for path in features.get("fences",[])],
               "trees":[{**t,"position":placed(t)} for t in features.get("trees",[])],
               "vegetation":vegetation,"repair":repair,"referenceCount":cfg.get("reference_count"),
               "procedural_seeds":{"features":9721,"ground_grain":7821,"grass":78231},
               "attributions":cfg.get("attributions",[]),"limits":cfg.get("limits",[]),
               "review_sha256":digest(review),"review_revision":review["revision"]}
        write(stage/"scene.json",scene);write(stage/"review.json",review)
        write(stage/"observations.json",{"snapshot":prepared["snapshot"],"observations":all_rows,"image":prepared["image"]})
        write(stage/"camera.json",camera.data)
        for key,name in (("cow_model","cow-original.glb"),("cow_normal","cow-normal.png")):
            shutil.copy2(base/cfg[key],stage/"assets"/name)
        if cfg.get("source_manifest"):shutil.copy2(base/cfg["source_manifest"],stage/"terrain-source.json")
        copy_viewer(stage)
        output_hashes={str(p.relative_to(stage)):sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted(list(HERE.glob("world*.py"))+[p for p in VIEWER.iterdir() if p.is_file()])}
        runtime={"python":platform.python_version(),"packages":{p:version(p) for p in ("numpy","scipy","opencv-python-headless","rasterio","pillow")}}
        manifest={"version":VERSION,"scene_id":cfg["scene_id"],"snapshot":prepared["snapshot"],"inputs":locked,
                  "review_sha256":digest(review),"source_sha256":source_hashes,"output_sha256":output_hashes,
                  "algorithms":{"appearance_version":VERSION,"foreground_seed":"First seven SHA256 hex digits of canonical observation and brush strokes",
                                "color":"Median sRGB of eroded cow foreground; full foreground fallback when fewer than 12 interior pixels",
                                "body_axis":"PCA undirected foreground axis; saved head-end review",
                                "procedural_seeds":scene["procedural_seeds"],
                                "terrain_diagonal":terrain.spec()["diagonal"]},
                  "runtime":runtime,"dependency_locks":{"python":sha(HERE/"uv.lock"),"viewer":sha(VIEWER/"pnpm-lock.yaml")}}
        write(stage/"build-manifest.json",manifest)
        verify(stage)
        previous=None
        if dest.exists():
            previous=Path(tempfile.mkdtemp(prefix=".world-previous-",dir=dest.parent));previous.rmdir();dest.replace(previous)
        try:stage.replace(dest)
        except Exception:
            if previous:previous.replace(dest)
            raise
        if previous:shutil.rmtree(previous)
        elapsed=time.perf_counter()-started
        write(base/"last-build.json",{"seconds":elapsed,"output":str(dest),"cows":len(cows),"snapshot":prepared["snapshot"],
                                     "unreviewed":sum(c["status"]!="accepted" for c in cows),
                                     "unknown_heads":sum(c["head_status"]!="reviewed" for c in cows),
                                     "appearance_flagged":sum(bool(c["quality_flags"]) for c in cows)})
        return dest
    except Exception:
        if stage.exists():shutil.rmtree(stage)
        raise


def verify(output):
    output=Path(output);manifest=read(output/"build-manifest.json");scene=read(output/"scene.json")
    for name,expected in manifest["output_sha256"].items():
        path=(output/name).resolve()
        if not path.is_relative_to(output.resolve()) or not path.is_file() or sha(path)!=expected:
            raise ValueError("Missing or corrupted scene output: "+name)
    rgb,meta=source_image(output/scene["source_image"])
    if sha(output/scene["source_image"])!=scene["source_image_sha256"]:
        raise ValueError("Source image integrity failure")
    ids=[c["sceneCowId"] for c in scene["cows"]]
    if len(ids)!=len(set(ids)):raise ValueError("Repeated cow identity")
    from world_geometry import Camera
    # Reconstruct sampling from exported buffers, independently of the input raster.
    from world_geometry import Terrain
    t=Terrain.__new__(Terrain);s=scene["terrain"]
    t.w=s["width"];t.h=s["height"];t.spacing=s["spacing"];t.min_x=s["minX"];t.min_z=s["minZ"]
    t.max_x=t.min_x+(t.w-1)*t.spacing;t.max_z=t.min_z+(t.h-1)*t.spacing
    t.origin=np.array([scene["origin"][k] for k in ("easting","northing","altitude")])
    t.heights=np.fromfile(output/"heights.bin",dtype='<f4').reshape(t.h,t.w)
    t.valid=np.fromfile(output/"valid.bin",dtype=np.uint8).reshape(t.h,t.w)
    camera=Camera(scene["camera"],t,meta)
    max_pixel=0.
    for row in scene["detectionReview"]:
        x1,y1,x2,y2=row["crop_bounds"]
        actual=np.array(Image.open(output/row["source_crop"]))
        if not np.array_equal(actual,rgb[y1:y2,x1:x2]):
            raise ValueError("Crop does not match original observation: "+row["id"])
    expected={r["id"] for r in scene["detectionReview"] if r["status"]!="rejected"}
    if set(ids)!=expected:raise ValueError("Exported population disagrees with saved review")
    for cow in scene["cows"]:
        p=np.array(cow["position"],float)
        if abs(p[1]-float(t.sample(p[0],p[2])))>.001:raise ValueError("Cow is off ground")
        p[1]+=cow["body_height_assumption_m"]
        pixel,_=camera.project(p)
        max_pixel=max(max_pixel,float(np.linalg.norm(pixel-cow["source_pixel"])))
    if max_pixel>.05:raise ValueError("Camera/observation round trip exceeds .05 px")
    review=read(output/"review.json")
    if digest(review)!=scene["review_sha256"] or review["snapshot"]!=scene["snapshot"]:
        raise ValueError("Review provenance mismatch")
    return {"passed":True,"files_verified":len(manifest["output_sha256"]),"cows":len(ids),
            "source_crops_exact":True,"max_reprojection_error_px":max_pixel,
            "scope":"Export integrity and geometry consistency; not survey accuracy or validated animal identification"}
