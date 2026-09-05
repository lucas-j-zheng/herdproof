from __future__ import annotations

import argparse
from pathlib import Path

from training.common import (PACKAGE, code_fingerprint, configure_runtime, cuda_environment,
                             digest, load_config, read_json, verify_prepared, write_json)
from training.data import native_crop, starts
from training.metrics import matched_count, summarize


def global_nms(predictions, threshold):
    if not predictions:
        return []
    import torch
    from torchvision.ops import nms
    tensor = torch.tensor(predictions, dtype=torch.float32)
    return tensor[nms(tensor[:, :4], tensor[:, 4], threshold)].tolist()


def predict_sources(checkpoint, source, records, config):
    from PIL import Image
    from ultralytics import YOLO
    model = YOLO(str(checkpoint))
    output = {}
    for index, row in enumerate(records):
        path = source / row["image"]
        if digest(path) != row["image_sha256"] or digest(source / row["label"]) != row["label_sha256"]:
            raise ValueError(f"Source data changed: {row['image']}")
        with Image.open(path) as original:
            image = original.convert("RGB")
        width, height = image.size
        predictions = []
        for y in starts(height, config["tile_size"], config["tile_overlap"]):
            for x in starts(width, config["tile_size"], config["tile_overlap"]):
                crop = native_crop(image, x, y, config["tile_size"])
                result = model.predict(crop, imgsz=1024, conf=min(config["confidence_candidates"]),
                    iou=config["tile_nms_iou"], max_det=config["max_detections_per_tile"],
                    device=0, half=False, augment=False, classes=[0], verbose=False)[0]
                for left, top, right, bottom, confidence, _ in result.boxes.data.cpu().tolist():
                    box = [max(0., min(1., (left + x) / width)), max(0., min(1., (top + y) / height)),
                           max(0., min(1., (right + x) / width)), max(0., min(1., (bottom + y) / height)), confidence]
                    if box[2] > box[0] and box[3] > box[1]:
                        predictions.append(box)
        output[row["id"]] = predictions
        print(f"Full-image inference: {index + 1}/{len(records)}", flush=True)
    return output


def score(records, predictions, confidence, nms_iou, config):
    rows = []
    for row in records:
        selected = [p for p in global_nms(predictions[row["id"]], nms_iou) if p[4] >= confidence]
        rows.append({"id": row["id"], "group": row["group"], "flight": row["flight"],
                     "annotated": len(row["boxes"]), "predicted": len(selected),
                     "matched": matched_count(selected, row["boxes"]), "predictions": selected})
    return {"overall": summarize(rows),
            "dense_images": summarize([r for r in rows if r["annotated"] >= config["dense_image_minimum_annotations"]]),
            "by_group": {group: summarize([r for r in rows if r["group"] == group]) for group in sorted({r["group"] for r in rows})},
            "rows": rows}


def checkpoint_for(runs, variant, prepared, config_path):
    folder = runs / variant
    done = read_json(folder / "complete.json")
    recipe = read_json(folder / "recipe.json")
    if done["mode"] != "train" or digest(folder / "recipe.json") != done["recipe_sha256"]:
        raise ValueError("Incomplete or modified training run")
    if recipe["prepared_sha256"] != digest(prepared / "complete.json") or recipe["config_sha256"] != digest(config_path):
        raise ValueError("Training run uses different data or settings")
    if recipe["code"] != code_fingerprint():
        raise ValueError("Training/evaluation code changed; use the original checkout")
    checkpoint = folder / "fit/weights/best.pt"
    if digest(checkpoint) != done["best_sha256"]:
        raise ValueError("Checkpoint changed")
    return checkpoint


def main():
    parser = argparse.ArgumentParser(description="Select only on validation; evaluate the frozen winner once on held-out capture groups")
    parser.add_argument("stage", choices=["select", "test"])
    for name in ("source", "prepared", "runs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PACKAGE / "config.json")
    args = parser.parse_args()
    for key in ("source", "prepared", "runs", "output", "config"):
        setattr(args, key, getattr(args, key).resolve())
    config = load_config(args.config)
    configure_runtime(args.output.parent / ".cache")
    environment = cuda_environment()
    verify_prepared(args.prepared, args.config, verify_tiles=False)
    rows = read_json(args.prepared / "catalog.json")
    split = "val" if args.stage == "select" else "test"
    records = [r for r in rows if r["eligible"] and r["split"] == split]
    if not records:
        raise ValueError("Empty evaluation split")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / (args.stage + ".started.json")
    # Exclusive creation prevents accidentally consuming test repeatedly or overwriting a selection.
    with lock.open("x") as stream:
        stream.write('{"status":"started"}\n')
    base = {"prepared_sha256": digest(args.prepared / "complete.json"), "config_sha256": digest(args.config),
            "environment": environment, "status": config["evaluation_status"], "code": code_fingerprint()}
    if args.stage == "select":
        candidates = []
        for variant in config["variants"]:
            checkpoint = checkpoint_for(args.runs, variant, args.prepared, args.config)
            predictions = predict_sources(checkpoint, args.source, records, config)
            write_json(args.output / f"val-{variant}-predictions.json", predictions)
            for nms_iou in config["global_nms_candidates"]:
                for confidence in config["confidence_candidates"]:
                    report = score(records, predictions, confidence, nms_iou, config)
                    candidates.append({"variant": variant, "confidence": confidence, "nms_iou": nms_iou,
                                       "checkpoint_sha256": digest(checkpoint), "metrics": report["overall"]})
        # Same predeclared criterion for both models. No test metrics are read here.
        winner = min(candidates, key=lambda c: (c["metrics"]["annotation_disagreements"],
                     c["metrics"]["count_mae_vs_annotations"], -c["confidence"], c["variant"], c["nms_iou"]))
        write_json(args.output / "validation-candidates.json", candidates)
        predictions = read_json(args.output / f"val-{winner['variant']}-predictions.json")
        write_json(args.output / "validation-report.json", {**base, **score(records, predictions, winner["confidence"], winner["nms_iou"], config)})
        write_json(args.output / "winner.json", {**base, **winner})
        print(winner, flush=True)
    else:
        winner_path = args.output / "winner.json"
        winner = read_json(winner_path)
        if any(winner[k] != base[k] for k in ("prepared_sha256", "config_sha256", "code")):
            raise ValueError("Winner belongs to a different experiment")
        checkpoint = checkpoint_for(args.runs, winner["variant"], args.prepared, args.config)
        if digest(checkpoint) != winner["checkpoint_sha256"]:
            raise ValueError("Selected checkpoint changed")
        predictions = predict_sources(checkpoint, args.source, records, config)
        write_json(args.output / "test-predictions.json", predictions)
        report = score(records, predictions, winner["confidence"], winner["nms_iou"], config)
        write_json(args.output / "test-report.json", {**base, "winner_sha256": digest(winner_path), **report})
        print(report["overall"], flush=True)


if __name__ == "__main__":
    main()
