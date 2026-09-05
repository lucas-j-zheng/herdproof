from __future__ import annotations

import argparse
import time
from pathlib import Path

from training.common import (PACKAGE, code_fingerprint, configure_runtime, cuda_environment,
                             digest, git_revision, load_config, read_json, verify_prepared, write_json)


def training_arguments(config, data, project, name, *, smoke=False, device=0):
    return dict(data=str(data), project=str(project), name=name, exist_ok=False,
                epochs=2 if smoke else config["epochs"], patience=config["patience"],
                imgsz=1024, batch=config["batch"], device=device, workers=config["workers"],
                seed=config["seed"], deterministic=True, optimizer=config["optimizer"],
                lr0=config["lr0"], lrf=.01, nbs=64, warmup_epochs=3.,
                amp=False, cache=False, plots=False, save=True, save_period=5, val=True,
                fraction=1., multi_scale=False, rect=False,
                mosaic=0., close_mosaic=0, mixup=0., cutmix=0., copy_paste=0.,
                scale=0., translate=0., degrees=0., shear=0., perspective=0.,
                fliplr=.5, flipud=.5, hsv_h=.015, hsv_s=.7, hsv_v=.4,
                max_det=config["max_detections_per_tile"], verbose=False)


def write_dataset_yaml(prepared, folder, smoke=False):
    import yaml
    data = {"path": str(prepared), "names": {0: "cattle"}}
    for split in ("train", "val"):
        if smoke:
            # Lists point to the original 1024-pixel crops. Smoke samples never become the full run.
            tiles = [t for t in read_json(prepared / "tiles.json") if t["split"] == split]
            selected = sorted(tiles, key=lambda t: (-t["objects"], t["image"]))[:32 if split == "train" else 16]
            target = folder / f"smoke-{split}.txt"
            target.write_text("".join(str(prepared / t["image"]) + "\n" for t in selected))
            data[split] = str(target)
        else:
            data[split] = f"images/{split}"
    path = folder / "dataset.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def run(args):
    config = load_config(args.config)
    configure_runtime(args.runs / ".cache")
    environment = cuda_environment()
    verify_prepared(args.prepared, args.config)
    assets = read_json(PACKAGE / "assets.json")["weights"]
    weights = args.weights / (args.variant + ".pt")
    if digest(weights) != assets[args.variant]["sha256"]:
        raise ValueError("Initial weights failed SHA256 verification")
    smoke = args.mode == "smoke"
    folder = args.runs / (("smoke-" if smoke else "") + args.variant)
    recipe = {"variant": args.variant, "mode": args.mode, "config_sha256": digest(args.config),
              "prepared_sha256": digest(args.prepared / "complete.json"),
              "initial_weights_sha256": digest(weights), "code": code_fingerprint()}
    if not smoke:
        for variant in config["variants"]:
            smoke_folder = args.runs / ("smoke-" + variant)
            smoke_done = read_json(smoke_folder / "complete.json")
            smoke_recipe = read_json(smoke_folder / "recipe.json")
            if smoke_done["mode"] != "smoke" or smoke_done["recipe_sha256"] != digest(smoke_folder / "recipe.json"):
                raise ValueError(f"Missing valid CUDA smoke completion: {variant}")
            if any(smoke_recipe[key] != recipe[key] for key in ("config_sha256", "prepared_sha256", "code")):
                raise ValueError("Smoke run uses different code/data/settings; run a new smoke first")
    if folder.exists():
        if not args.resume or smoke:
            raise ValueError(f"Run exists: {folder}; use --resume for an interrupted full run")
        if (folder / "complete.json").exists():
            raise ValueError("Run already completed")
        if read_json(folder / "recipe.json") != recipe:
            raise ValueError("Code/config/data changed; cannot resume the same experiment")
        checkpoint = folder / "fit/weights/last.pt"
        if not checkpoint.is_file():
            raise ValueError("No resumable checkpoint")
    else:
        if args.resume:
            raise ValueError("No run to resume")
        folder.mkdir(parents=True)
        write_json(folder / "recipe.json", recipe)
        checkpoint = weights
    write_json(folder / f"environment-{environment['slurm_job_id']}.json", {**environment, "git_commit": git_revision()})
    data = write_dataset_yaml(args.prepared, folder, smoke)
    from ultralytics import YOLO, settings
    settings.update({"sync": False, "wandb": False, "mlflow": False, "clearml": False,
                     "comet": False, "neptune": False})
    model = YOLO(str(checkpoint))
    arguments = training_arguments(config, data, folder, "fit", smoke=smoke)
    write_json(folder / "requested-arguments.json", arguments)
    epoch_times, epoch_start = [], [None]

    def start_epoch(trainer):
        if next(trainer.model.parameters()).device.type != "cuda":
            raise RuntimeError("Training unexpectedly left the GPU")
        epoch_start[0] = time.monotonic()

    def finish_epoch(trainer):
        epoch_times.append({"epoch": trainer.epoch + 1, "training_seconds": time.monotonic() - epoch_start[0]})
        write_json(folder / "timing.json", epoch_times)

    model.add_callback("on_train_epoch_start", start_epoch)
    model.add_callback("on_train_epoch_end", finish_epoch)
    start = time.monotonic()
    if args.resume:
        model.train(resume=True)
    else:
        model.train(**arguments)
    best = folder / "fit/weights/best.pt"
    if not best.is_file():
        raise RuntimeError("Training ended without best.pt")
    write_json(folder / "complete.json", {"best": str(best), "best_sha256": digest(best),
               "recipe_sha256": digest(folder / "recipe.json"), "elapsed_seconds": time.monotonic() - start,
               "epoch_times": epoch_times, "mode": args.mode, "annotation_status": config["evaluation_status"]})
    print(f"Completed {args.mode} {args.variant}: {best}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Train native-1024 cattle detector inside a SLURM GPU allocation")
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PACKAGE / "config.json")
    parser.add_argument("--variant", choices=["yolov8n", "yolov8s"], required=True)
    parser.add_argument("--mode", choices=["smoke", "train"], default="train")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    for key in ("prepared", "weights", "runs", "config"):
        setattr(args, key, getattr(args, key).resolve())
    run(args)


if __name__ == "__main__":
    main()
