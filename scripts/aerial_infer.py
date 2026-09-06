#!/usr/bin/env python3
"""Run the selected cattle model; --baseline reproduces the frozen COCO experiment."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
for name, folder in (("YOLO_CONFIG_DIR", "ultralytics"), ("MPLCONFIGDIR", "matplotlib")):
    directory = BASE / ".cache" / folder
    directory.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(directory)
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["YOLO_OFFLINE"] = "true"

import cv2
import numpy as np
import torch
import ultralytics
from ultralytics import YOLO, settings
from training.metrics import iou


def nms(boxes, threshold):
    kept = []
    for box in sorted(boxes, key=lambda b: -b[4]):
        if all(iou(box, prior) <= threshold for prior in kept): kept.append(box)
    return kept


def starts(length, size, overlap):
    if length <= size: return [0]
    step = max(1, round(size * (1-overlap)))
    return sorted(set(list(range(0, length-size+1, step)) + [length-size]))


def baseline_main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=BASE / "validation/data")
    p.add_argument("--output", type=Path, default=BASE / "validation/runs/baseline")
    p.add_argument("--weights", type=Path, default=BASE / "validation/models/yolov8n.pt")
    p.add_argument("--device", default="cpu")
    args = p.parse_args()
    protocol_path = BASE / "validation/protocol.json"
    protocol = json.loads(protocol_path.read_text())
    selection = json.loads((args.data / "selection.json").read_text())
    if selection["protocol_sha256"] != hashlib.sha256(protocol_path.read_bytes()).hexdigest():
        raise RuntimeError("Protocol changed after sample selection")
    if not args.weights.exists(): raise RuntimeError("Download official weights explicitly first")
    expected = "f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36"
    weight_hash = hashlib.sha256(args.weights.read_bytes()).hexdigest()
    if weight_hash != expected: raise RuntimeError("Unexpected official baseline weight checksum")
    args.output.mkdir(parents=True, exist_ok=True)
    settings.update({"sync": False})
    torch.set_num_threads(4)
    model = YOLO(str(args.weights))
    model.predict(np.zeros((640,640,3), dtype=np.uint8), device=args.device, verbose=False)
    metadata = {"protocol_sha256": selection["protocol_sha256"], "model_sha256": weight_hash,
                "ultralytics": ultralytics.__version__, "torch": torch.__version__,
                "device": args.device, "platform": platform.platform(),
                "trained_on_target_data": False, "prediction_source": "model pixels, no annotation input"}
    meta_path = args.output / "metadata.json"
    if meta_path.exists() and json.loads(meta_path.read_text()) != metadata:
        raise RuntimeError("Run configuration changed; choose a new output directory")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    # May run while images download; ordered selection is already frozen.
    for index, record in enumerate(selection["images"]):
        dest = args.output / (record["id"] + ".json")
        if dest.exists(): continue
        image_path = args.data / (record["id"] + ".jpg")
        for attempt in range(60):
            if image_path.exists(): break
            completed = args.data / "manifest.json"
            if completed.exists(): break
            time.sleep(1)
        if not image_path.exists():
            if (args.data / "manifest.json").exists():
                print(f"Excluded before inference: {record['id']}", flush=True)
                continue
            print(f"Image not downloaded yet: {index+1}; rerun safely to resume", flush=True)
            break
        frame = cv2.imread(str(image_path))
        if frame is None: raise RuntimeError("Image failed to decode")
        h, w = frame.shape[:2]
        result = {"id": record["id"], "width": w, "height": h,
                  "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "modes": {}}
        for mode in protocol["inference_modes"]:
            begin = time.perf_counter()
            if mode == "whole": tiles = [(0, 0, frame)]
            else:
                size = protocol["tile_size"]
                tiles = [(x, y, frame[y:y+size, x:x+size])
                         for y in starts(h, size, protocol["tile_overlap"])
                         for x in starts(w, size, protocol["tile_overlap"])]
            boxes = []
            for x, y, tile in tiles:
                found = model.predict(tile, classes=[19], conf=protocol["inference_confidence_floor"],
                                      iou=protocol["merge_nms_iou"], max_det=1000,
                                      imgsz=protocol["whole_image_size"] if mode == "whole" else protocol["tile_size"],
                                      device=args.device, verbose=False)[0]
                for b, confidence in zip(found.boxes.xyxy.cpu().tolist(), found.boxes.conf.cpu().tolist()):
                    boxes.append([(b[0]+x)/w, (b[1]+y)/h, (b[2]+x)/w, (b[3]+y)/h, confidence])
            boxes = nms(boxes, protocol["merge_nms_iou"])
            result["modes"][mode] = {"boxes": boxes, "seconds": time.perf_counter()-begin, "tiles": len(tiles)}
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2) + "\n")
        tmp.replace(dest)
        print(f"Inferred {index+1}/{len(selection['images'])}: {record['id']} whole={len(result['modes']['whole']['boxes'])} tiled={len(result['modes']['tiled']['boxes'])}", flush=True)


def main():
    if "--baseline" in sys.argv[1:]:
        sys.argv.remove("--baseline")
        return baseline_main()
    from training.infer import main as default_inference
    return default_inference()


if __name__ == "__main__": main()
