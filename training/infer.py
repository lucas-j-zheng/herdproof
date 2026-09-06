"""Run the selected HerdProof model on pixels, using the recorded default settings."""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from training.common import (PACKAGE, configure_runtime, digest, exclusive_lock,
                             read_json, require_compute_job, write_json)
from training.data import native_crop, starts
from training.evaluate import global_nms
from training.runtime import ensure_finite

ROOT = PACKAGE.parent
DEFAULT_CONFIG = PACKAGE / "default_model.json"


def load_default_config(path=DEFAULT_CONFIG):
    config = read_json(path)
    if config["schema"] != 1 or config["class_id"] != 0:
        raise ValueError("Expected the single-class cattle model configuration")
    if not 0 < config["inference_confidence_floor"] <= config["confidence"] <= 1:
        raise ValueError("Invalid default confidence settings")
    if any(not 0 < config[key] <= 1 for key in ("tile_nms_iou", "global_nms_iou")):
        raise ValueError("Invalid NMS settings")
    if config["tile_size"] != 1024 or config["model_imgsz"] != 1024 or not 0 <= config["tile_overlap"] < 1:
        raise ValueError("Expected the selected native-1024 inference recipe")
    return config


def resolve_checkpoint(config, weights=None):
    require_compute_job()
    if weights is None:
        path = ROOT / config["checkpoint"]
        if not path.is_file() and os.environ.get("HERDPROOF_ROOT"):
            path = Path(os.environ["HERDPROOF_ROOT"]) / config["oscar_checkpoint"]
    else:
        path = Path(weights)
    if not path.is_file():
        raise FileNotFoundError(f"Selected cattle checkpoint missing: {path}. Supply --weights with the pinned Oscar checkpoint.")
    if digest(path) != config["checkpoint_sha256"]:
        raise ValueError("Default checkpoint SHA-256 mismatch; refusing to use another model")
    return path.resolve()


def predict_image(model, image, config, device="cpu"):
    """Match the Oscar evaluator's tile geometry, class filter and two NMS stages."""
    require_compute_job()
    image = image.convert("RGB")
    width, height = image.size
    predictions, count = [], 0
    for y in starts(height, config["tile_size"], config["tile_overlap"]):
        for x in starts(width, config["tile_size"], config["tile_overlap"]):
            crop = native_crop(image, x, y, config["tile_size"])
            result = model.predict(crop, imgsz=config["model_imgsz"],
                conf=config["inference_confidence_floor"], iou=config["tile_nms_iou"],
                max_det=config["max_detections_per_tile"], classes=[config["class_id"]],
                device=device, half=False, augment=False, verbose=False)[0]
            ensure_finite(result.boxes.data, "default model predictions")
            for left, top, right, bottom, confidence, _ in result.boxes.data.cpu().tolist():
                box = [max(0., min(1., (left+x)/width)), max(0., min(1., (top+y)/height)),
                       max(0., min(1., (right+x)/width)), max(0., min(1., (bottom+y)/height)), confidence]
                if box[2] > box[0] and box[3] > box[1]:
                    predictions.append(box)
            count += 1
    boxes = global_nms(predictions, config["global_nms_iou"])
    return {"boxes": boxes, "tiles": count,
            "count": sum(b[4] >= config["confidence"] for b in boxes)}


def input_records(data, image_ids=None):
    data = Path(data).resolve()
    if data.is_file():
        records = [{"id": data.stem, "path": data, "expected_sha256": None}]
    elif (data / "manifest.json").is_file():
        records = [{"id": r["id"], "path": data/r["image"], "expected_sha256": r["image_sha256"]}
                   for r in read_json(data/"manifest.json")["records"]]
    else:
        records = [{"id": p.stem, "path": p, "expected_sha256": None} for p in sorted(data.iterdir())
                   if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if image_ids:
        wanted = set(image_ids)
        if wanted - {r["id"] for r in records}:
            raise ValueError("Requested image IDs not found")
        records = [r for r in records if r["id"] in wanted]
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("No images or duplicate image IDs")
    if any(not r["id"] or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in r["id"]) for r in records):
        raise ValueError("Image IDs must contain only letters, digits, underscores or hyphens")
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", "--source", type=Path, default=ROOT/"validation/data",
                        help="Image, directory of images, or directory with manifest.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--weights", type=Path, help="Alternative location of the same SHA-pinned checkpoint")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--image-ids", nargs="+", help="Explicit subset of manifest IDs")
    args = parser.parse_args(argv)
    require_compute_job()
    config = load_default_config()
    output = (args.output or ROOT/config["default_output"]).resolve()
    checkpoint = resolve_checkpoint(config, args.weights)
    records = input_records(args.data, args.image_ids)
    with exclusive_lock(output/".inference.lock"):
        configure_runtime(output/".cache")
        import torch
        from PIL import Image
        from ultralytics import YOLO, settings
        torch.set_num_threads(min(4, int(os.environ.get("SLURM_CPUS_PER_TASK", "4"))))
        settings.update({"sync": False})
        metadata = {"model_id": config["model_id"], "weights_sha256": config["checkpoint_sha256"],
                    "default_config_sha256": digest(DEFAULT_CONFIG), "settings": config,
                    "device": args.device, "trained_on_target_data": True,
                    "input_ids": [r["id"] for r in records], "prediction_source": "model pixels; no annotations used"}
        if (output/"metadata.json").exists() and read_json(output/"metadata.json") != metadata:
            raise ValueError("Run inputs/settings changed; choose a new output directory")
        write_json(output/"metadata.json", metadata)
        model = None
        for record in records:
            image_sha = digest(record["path"])
            if record["expected_sha256"] is not None and image_sha != record["expected_sha256"]:
                raise ValueError(f"Input pixels changed: {record['id']}")
            target = output/(record["id"]+".json")
            if target.exists():
                cached = read_json(target)
                if cached.get("image_sha256") != image_sha or cached.get("model_sha256") != config["checkpoint_sha256"]:
                    raise ValueError("Cached prediction identity changed")
                ensure_finite(cached["modes"][config["mode"]]["boxes"], "cached predictions")
                continue
            if model is None:
                model = YOLO(str(checkpoint))
                if len(model.names) != 1 or 0 not in model.names:
                    raise ValueError("Expected a class-0 cattle detector")
            begin = time.perf_counter()
            with Image.open(record["path"]) as image:
                result = predict_image(model, image, config, args.device)
                width, height = image.size
            result["seconds"] = time.perf_counter()-begin
            write_json(target, {"id": record["id"], "image_sha256": image_sha,
                "model_sha256": config["checkpoint_sha256"], "width": width, "height": height,
                "modes": {config["mode"]: result}})
            print(f"{record['id']}: {result['count']} cattle candidates at confidence {config['confidence']:.2f}", flush=True)
        selection = {"selected_mode": config["mode"], "selected_threshold": config["confidence"],
                     "global_nms_iou": config["global_nms_iou"], "weights_sha256": config["checkpoint_sha256"],
                     "selection_method": "explicit_user_choice", "known_benchmark_followup": True}
        write_json(output/"selection.json", selection)
        # Compatible with the survey pipeline's saved-run interface; no invented accuracy metrics.
        write_json(output/"report.json", {"status": "inference_only", "selection": selection,
            "inference": metadata, "sample_images": len(records), "results": {}})


if __name__ == "__main__":
    main()
