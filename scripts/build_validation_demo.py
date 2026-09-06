#!/usr/bin/env python3
"""Prepare EXIF-free local review images and an explicitly synthetic business case."""
from __future__ import annotations
import json
import argparse
import random
from pathlib import Path
from PIL import Image
from reconcile_inventory import read_records, reconcile

BASE = Path(__file__).resolve().parents[1]


def main():
    data = BASE / "validation/data"
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=BASE / "validation/runs/baseline")
    run = parser.parse_args().run.resolve()
    manifest = json.loads((data / "manifest.json").read_text())
    report = json.loads((run / "report.json").read_text())
    mode = report["selection"]["selected_mode"]
    threshold = report["selection"]["selected_threshold"]
    records = {r["id"]:r for r in manifest["records"]}
    eval_rows = [r for r in manifest["records"] if r["split"] == "evaluation"]
    # Representative demo/trial selection depends on labels, never prediction success.
    pool = sorted((r for r in eval_rows if 3 <= len(r["boxes"]) <= 90), key=lambda r:(abs(len(r["boxes"])-20),r["id"]))
    trials, flights = [], set()
    for r in pool:
        if r["flight"] in flights: continue
        trials.append(r["id"])
        flights.add(r["flight"])
        if len(trials) == 4: break
    if len(trials) < 4: raise RuntimeError("Need four independent flights for review instrument")
    chosen = next((records[i] for i in trials if any((b[0]+b[2])/2<.5 for b in records[i]["boxes"]) and any((b[0]+b[2])/2>=.5 for b in records[i]["boxes"])),records[trials[0]])
    assets = BASE / "validation/review-assets"
    assets.mkdir(parents=True, exist_ok=True)
    for image_id in trials:
        with Image.open(data / records[image_id]["image"]) as source:
            # Re-encode pixels without EXIF/GPS and retain full resolution for review.
            clean = Image.frombytes("RGB", source.size, source.convert("RGB").tobytes())
            clean.save(assets / f"{image_id}.jpg", quality=94)
    selected_predictions = {}
    for image_id in trials:
        p = json.loads((run / f"{image_id}.json").read_text())
        selected_predictions[image_id] = [b for b in p["modes"][mode]["boxes"] if b[4] >= threshold]
    ref_counts = {"West":0,"East":0}
    model_counts = {"West":0,"East":0}
    for b in chosen["boxes"]: ref_counts["West" if (b[0]+b[2])/2 < .5 else "East"] += 1
    for b in selected_predictions[chosen["id"]]: model_counts["West" if (b[0]+b[2])/2 < .5 else "East"] += 1
    csv = ("document_id,date,event,pen,quantity\n"
           f"INV-W,2026-09-01,inventory,West,{ref_counts['West']+4}\n"
           f"INV-E,2026-09-01,inventory,East,{ref_counts['East']}\n"
           "SALE-W,2026-09-03,sale,West,4\n")
    observations = {pen:{"count":n,"reviewed":True,"coverage":"complete","as_of":"2026-09-05"} for pen,n in ref_counts.items()}
    parsed = read_records(csv)
    stages = {"initial": reconcile(parsed, {}, "2026-09-05"),
              "west_reference_review": reconcile(parsed, {"West":observations["West"]}, "2026-09-05"),
              "east_supplied_unreviewed": reconcile(parsed, {"West":observations["West"], "East":{"count":model_counts["East"],"reviewed":False,"coverage":"complete","as_of":"2026-09-05"}}, "2026-09-05"),
              "both_reference_reviews": reconcile(parsed, observations, "2026-09-05")}
    private = {"trial_ids":trials,"records":{k:records[k] for k in trials},"predictions":selected_predictions,
               "model":mode,"threshold":threshold}
    (run / "review-private.json").write_text(json.dumps(private,indent=2)+"\n")
    demo = {"image_id":chosen["id"],"synthetic":True,"csv":csv,"reference_counts":ref_counts,
            "model_counts":model_counts,"predictions":selected_predictions[chosen["id"]],"stages":stages,
            "disclosure":"Real historical pasture imagery. West/East are artificial image halves, not real pens or parcel boundaries. Business records, dates, and complete-coverage assumptions are synthetic. Reference review replays publisher annotations; it is not a new human inspection.",
            "attribution":manifest["attribution"]}
    (run / "demo.json").write_text(json.dumps(demo,indent=2)+"\n")
    (BASE / "validation/example-inventory.csv").write_text(csv)
    print(json.dumps({"trials":len(trials),"demo_image":chosen["id"],"stages":{k:v["status"] for k,v in stages.items()}},indent=2))


if __name__ == "__main__": main()
