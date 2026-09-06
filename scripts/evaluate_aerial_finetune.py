#!/usr/bin/env python3
"""Evaluate the fixed domain fine-tune without touching its training flights."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from aerial_infer import BASE, nms, starts  # Sets offline/config flags before CV imports.
import cv2
import torch
from ultralytics import YOLO, settings
from aerial_metrics import evaluate, aggregate, by_flight


def main():
    run=BASE/"validation/runs/finetuned"
    protocol=json.loads((BASE/"validation/finetune-protocol.json").read_text())
    partitions=json.loads((run/"partitions.json").read_text())
    manifest=json.loads((BASE/"validation/data/manifest.json").read_text())
    weights=run/"training-cpu/weights/last.pt"
    if not weights.exists():raise RuntimeError("Fixed training run is not complete")
    # Reject incomplete checkpoints even if epoch-one last.pt already exists.
    rows=(run/"training-cpu/results.csv").read_text().strip().splitlines()
    if int(rows[-1].split(',')[0]) != protocol["epochs"]:raise RuntimeError("Wait for all fixed epochs")
    selected=[]
    for r in manifest["records"]:
        if r["flight"] in partitions["training_flights"]:continue
        split="calibration" if r["flight"] in partitions["calibration_flights"] else "evaluation"
        selected.append({**r,"split":split})
    metadata={"weights_sha256":hashlib.sha256(weights.read_bytes()).hexdigest(),
              "protocol_sha256":partitions["protocol_sha256"],"training":"20 fixed epochs, 6 flights, 30 source images, 334 source annotations",
              "calibration_flights":2,"evaluation_flights":17,"torch":torch.__version__,"device":"mps",
              "training_backend":"CPU, original upstream implementation", "known_benchmark_followup":True}
    meta_path=run/"metadata.json"
    if meta_path.exists() and json.loads(meta_path.read_text())!=metadata:raise ValueError("Run identity changed")
    meta_path.write_text(json.dumps(metadata,indent=2)+"\n")
    settings.update({"sync":False})
    torch.set_num_threads(4)
    model=YOLO(str(weights))
    # Check a calibration tile on both backends before relying on MPS inference.
    sanity = next(r for r in selected if r["split"] == "calibration" and r["boxes"])
    frame = cv2.imread(str(BASE/"validation/data"/sanity["image"]))
    hh,ww = frame.shape[:2];b=sanity["boxes"][0];size=protocol["tile_size"]
    xx=max(0,min(ww-size,int((b[0]+b[2])/2*ww)-size//2))
    yy=max(0,min(hh-size,int((b[1]+b[3])/2*hh)-size//2))
    tile=frame[yy:yy+size,xx:xx+size]
    parity={}
    actual_devices={}
    for device in ("cpu","mps"):
        probe=YOLO(str(weights)).to(device)
        p=probe.predict(tile,classes=[0],imgsz=size,conf=.05,iou=.5,max_det=1000,device=device,verbose=False)[0]
        actual_devices[device]=str(probe.predictor.device)
        if actual_devices[device]!=device:raise RuntimeError("Requested backend not active")
        parity[device]=sorted(p.boxes.data.cpu().tolist(),key=lambda b:-b[4])
        del probe
    same_count=len(parity["cpu"])==len(parity["mps"])
    max_delta=max((abs(a-b) for left,right in zip(parity["cpu"],parity["mps"]) for a,b in zip(left,right)),default=0)
    passed=same_count and max_delta<1.0
    (run/"backend-parity.json").write_text(json.dumps({"calibration_image_id":sanity["id"],"actual_devices":actual_devices,"same_count":same_count,"max_raw_coordinate_or_score_delta":max_delta,"passed_pixel_tolerance":passed,"detections":parity},indent=2)+"\n")
    if not passed:raise RuntimeError("CPU/MPS inference check failed; investigate before scoring")
    for i,r in enumerate(selected):
        target=run/(r["id"]+".json")
        if target.exists():continue
        image=cv2.imread(str(BASE/"validation/data"/r["image"]));h,w=image.shape[:2]
        begin=time.perf_counter();boxes=[];size=protocol["tile_size"]
        for y in starts(h,size,protocol["tile_overlap"]):
            for x in starts(w,size,protocol["tile_overlap"]):
                p=model.predict(image[y:y+size,x:x+size],classes=[0],imgsz=size,conf=.05,iou=.5,max_det=1000,device="mps",verbose=False)[0]
                for b,c in zip(p.boxes.xyxy.cpu().tolist(),p.boxes.conf.cpu().tolist()):
                    boxes.append([(b[0]+x)/w,(b[1]+y)/h,(b[2]+x)/w,(b[3]+y)/h,c])
        output={"id":r["id"],"image_sha256":r["image_sha256"],"modes":{"tiled-finetuned":{"boxes":nms(boxes,.5),"seconds":time.perf_counter()-begin}}}
        target.write_text(json.dumps(output,indent=2)+"\n")
        print(f"Fine-tune inference {i+1}/{len(selected)}",flush=True)
    predictions={r["id"]:json.loads((run/(r["id"]+".json")).read_text())["modes"]["tiled-finetuned"] for r in selected}
    candidates=[]
    for threshold in protocol["confidence_candidates"]:
        scores=[evaluate(r,predictions[r["id"]]["boxes"],threshold) for r in selected if r["split"]=="calibration"]
        candidates.append({"threshold":threshold,**aggregate(scores)})
    chosen=min(candidates,key=lambda r:(r["correction_operations"],r["count_mae"],-r["threshold"]))
    selection={"selected_mode":"tiled-finetuned","selected_threshold":chosen["threshold"],"calibration_candidates":candidates,
               "selection_used_evaluation_labels":False,"known_benchmark_followup":True}
    selection_path=run/"selection.json"
    if selection_path.exists() and json.loads(selection_path.read_text())!=selection:raise ValueError("Calibration choice changed")
    selection_path.write_text(json.dumps(selection,indent=2)+"\n")
    scores=[evaluate(r,predictions[r["id"]]["boxes"],chosen["threshold"]) for r in selected if r["split"]=="evaluation"]
    summary=aggregate(scores)
    summary["mean_inference_seconds"]=sum(predictions[r["id"]]["seconds"] for r in scores)/len(scores)
    report={"protocol":protocol,"inference":metadata,"dataset":manifest["dataset"],"sample_images":len(manifest["records"]),
            "selection":selection,"results":{"tiled-finetuned":{"threshold":chosen["threshold"],"summary":summary,
              "positive_only":aggregate([r for r in scores if r["truth"]]),"by_flight":by_flight(scores),"images":scores}},
            "human_timing":{"status":"not_measured","time_saved":None},
            "conclusion":"Known-benchmark follow-up. Human efficiency, new-farm generalization, and collateral verification remain unvalidated."}
    (run/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"selected_threshold":chosen["threshold"],"evaluation":summary},indent=2))


if __name__=="__main__":main()
