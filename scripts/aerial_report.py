#!/usr/bin/env python3
"""Select settings on calibration flights only, then score held-out flights."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from aerial_metrics import aggregate, by_flight, evaluate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("validation/data"))
    p.add_argument("--run", type=Path, default=Path("validation/runs/baseline"))
    args = p.parse_args()
    protocol_path = Path("validation/protocol.json")
    protocol = json.loads(protocol_path.read_text())
    manifest = json.loads((args.data / "manifest.json").read_text())
    records = manifest["records"]
    if manifest["protocol_sha256"] != hashlib.sha256(protocol_path.read_bytes()).hexdigest():
        raise ValueError("Protocol changed")
    if not records or not any(r["split"] == "calibration" for r in records) or not any(r["split"] == "evaluation" for r in records):
        raise ValueError("Both disjoint partitions are required")
    if {r["flight"] for r in records if r["split"] == "calibration"} & {r["flight"] for r in records if r["split"] == "evaluation"}:
        raise ValueError("Flight leakage")
    predictions = {}
    for row in records:
        predicted = json.loads((args.run / (row["id"] + ".json")).read_text())
        if predicted["image_sha256"] != row["image_sha256"]: raise ValueError("Image hash mismatch")
        predictions[row["id"]] = predicted
    candidates, chosen = {}, {}
    for mode in protocol["inference_modes"]:
        scores = []
        for threshold in protocol["confidence_candidates"]:
            rows = [evaluate(r, predictions[r["id"]]["modes"][mode]["boxes"], threshold)
                    for r in records if r["split"] == "calibration"]
            scores.append({"mode": mode, "threshold": threshold, **aggregate(rows)})
        candidates[mode] = scores
        chosen[mode] = min(scores, key=lambda s: (s["correction_operations"], s["count_mae"], -s["threshold"]))
    selected_mode = min(chosen, key=lambda mode: (chosen[mode]["correction_operations"], chosen[mode]["count_mae"], mode))
    selection = {"protocol_sha256": manifest["protocol_sha256"], "calibration_candidates": candidates,
                 "chosen_per_mode": chosen, "selected_mode": selected_mode,
                 "selected_threshold": chosen[selected_mode]["threshold"],
                 "selection_used_evaluation_labels": False}
    selected_path = args.run / "selection.json"
    if selected_path.exists() and json.loads(selected_path.read_text()) != selection:
        raise ValueError("Previously frozen calibration choice changed")
    selected_path.write_text(json.dumps(selection, indent=2) + "\n")
    # Evaluation labels first affect scoring here, after selection has been saved.
    results = {}
    for mode, selected in chosen.items():
        rows = [evaluate(r, predictions[r["id"]]["modes"][mode]["boxes"], selected["threshold"])
                for r in records if r["split"] == "evaluation"]
        for r in rows: r["seconds"] = predictions[r["id"]]["modes"][mode]["seconds"]
        summary = aggregate(rows)
        summary["mean_inference_seconds"] = sum(r["seconds"] for r in rows)/len(rows)
        results[mode] = {"threshold": selected["threshold"], "summary": summary,
                         "positive_only": aggregate([r for r in rows if r["truth"]]),
                         "by_flight": by_flight(rows), "images": rows}
    output = {"protocol": protocol, "inference": json.loads((args.run / "metadata.json").read_text()),
              "dataset": manifest["dataset"], "sample_images": len(records),
              "selection": selection, "results": results,
              "human_timing": {"status": "not_measured", "time_saved": None},
              "conclusion": "Baseline feasibility evidence only. Correction operations are a proxy; no demonstrated human time saving."}
    (args.run / "report.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"selected_mode": selected_mode, "evaluation": {m:r["summary"] for m,r in results.items()}}, indent=2))


if __name__ == "__main__": main()
