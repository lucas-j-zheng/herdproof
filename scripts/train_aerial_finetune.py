#!/usr/bin/env python3
"""One frozen 20-epoch aerial fine-tune; all source flight partitions preserved."""
from __future__ import annotations
import hashlib
import json
import os
import random
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
for name, folder in (("YOLO_CONFIG_DIR","ultralytics"),("MPLCONFIGDIR","matplotlib")):
    d = BASE / ".cache" / folder
    d.mkdir(parents=True,exist_ok=True)
    os.environ[name] = str(d)
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["YOLO_OFFLINE"] = "true"

from PIL import Image
from ultralytics import YOLO, settings
from aerial_infer import starts


def main():
    protocol_path = BASE / "validation/finetune-protocol.json"
    spec = json.loads(protocol_path.read_text())
    manifest = json.loads((BASE / "validation/data/manifest.json").read_text())
    calibration = [r for r in manifest["records"] if r["split"] == "calibration"]
    positive_flights = sorted({r["flight"] for r in calibration if r["boxes"]})
    rng = random.Random(spec["seed"])
    rng.shuffle(positive_flights)
    dev = set(positive_flights[:2])
    training = {r["flight"] for r in calibration} - dev
    partition = {"protocol_sha256":hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
                 "training_flights":sorted(training),"calibration_flights":sorted(dev),
                 "evaluation_flights":sorted({r["flight"] for r in manifest["records"] if r["split"]=="evaluation"})}
    run = BASE / "validation/runs/finetuned"
    run.mkdir(parents=True,exist_ok=True)
    split_path = run / "partitions.json"
    if split_path.exists() and json.loads(split_path.read_text()) != partition:
        raise ValueError("Frozen partitions changed")
    split_path.write_text(json.dumps(partition,indent=2)+"\n")
    root = BASE / "validation/train-data"
    counts = {"train":0,"val":0,"source_train_images":0,"source_val_images":0,"source_train_annotations":0,"source_val_annotations":0}
    for r in calibration:
        split = "val" if r["flight"] in dev else "train"
        counts["source_"+split+"_images"] += 1
        counts["source_"+split+"_annotations"] += len(r["boxes"])
        images,labels = root/"images"/split,root/"labels"/split
        images.mkdir(parents=True,exist_ok=True);labels.mkdir(parents=True,exist_ok=True)
        with Image.open(BASE/"validation/data"/r["image"]) as src: image=src.convert("RGB")
        w,h=image.size;size=spec["tile_size"]
        positive,negative=[],[]
        for y in starts(h,size,spec["tile_overlap"]):
            for x in starts(w,size,spec["tile_overlap"]):
                tw,th=min(size,w-x),min(size,h-y)
                boxlines=[]
                for a,b,c,d in r["boxes"]:
                    xmin,ymin,xmax,ymax=max(x,a*w),max(y,b*h),min(x+tw,c*w),min(y+th,d*h)
                    if xmax<=xmin or ymax<=ymin:continue
                    boxlines.append(f"0 {((xmin+xmax)/2-x)/tw:.8f} {((ymin+ymax)/2-y)/th:.8f} {(xmax-xmin)/tw:.8f} {(ymax-ymin)/th:.8f}")
                (positive if boxlines else negative).append((x,y,tw,th,boxlines))
        rng.shuffle(negative)
        for x,y,tw,th,boxlines in positive+negative[:spec["negative_tiles_per_image"]]:
            stem=f"{r['id']}_{x}_{y}"
            image.crop((x,y,x+tw,y+th)).save(images/(stem+".jpg"),quality=95)
            (labels/(stem+".txt")).write_text("\n".join(boxlines)+("\n" if boxlines else ""))
            counts[split]+=1
    (run/"training-data-summary.json").write_text(json.dumps(counts,indent=2)+"\n")
    print(json.dumps(counts),flush=True)
    data_file=root/"dataset.yaml"
    data_file.write_text(f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n  0: cattle\n")
    weights=BASE/"validation/models/yolov8n.pt"
    if hashlib.sha256(weights.read_bytes()).hexdigest()!="f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36":raise ValueError("Wrong initial weights")
    training_name = "training-cpu"
    if (run/training_name/"weights/last.pt").exists():raise ValueError("Training already exists; refusing accidental rerun")
    (run/"backend-amendment.json").write_text(json.dumps({
        "reason":"MPS indexing failure; moving loss to CPU also encountered invalid label indices, so partial fallback was abandoned",
        "action":"Restart from original weights on CPU, with the original upstream implementation and unchanged split/epochs/settings",
        "preserved_failed_runs":["training/","training-cpu-loss/"], "upstream_issue":"https://github.com/pytorch/pytorch/issues/178079",
        "inference_sanity":"One original calibration tile yielded identical CPU/MPS classes and rounded confidences"},indent=2)+"\n")
    settings.update({"sync":False})
    model=YOLO(str(weights))
    model.train(data=str(data_file),epochs=spec["epochs"],imgsz=spec["training_image_size"],batch=spec["batch"],
                device="cpu",workers=0,amp=False,cache=False,seed=spec["seed"],deterministic=True,
                optimizer=spec["optimizer"],lr0=spec["lr0"],patience=spec["epochs"],
                project=str(run),name=training_name,exist_ok=False,plots=False,save=True,
                mosaic=0.0,close_mosaic=0,fliplr=.5,flipud=.5,verbose=False)
    print("Completed fixed 20-epoch fine-tune",flush=True)


if __name__=="__main__":main()
