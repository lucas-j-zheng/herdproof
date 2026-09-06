from __future__ import annotations

import argparse
import math
import time
import uuid
from pathlib import Path

from training.common import (PACKAGE, code_fingerprint, configure_runtime, cuda_environment,
                             digest, exclusive_lock, git_revision, load_config, read_json, verify_prepared, write_json)
from training.runtime import TrainingMonitor, checked_trainer, read_recovery, restore_recovery, validate_checkpoint


def training_arguments(config, data, project, name, *, smoke=False, device=0, smoke_images=32):
    # Match full-run warmup and accumulation, then exercise two steady-state updates.
    batches = math.ceil(smoke_images / config["batch"])
    warmup_batches = max(round(3. * batches), 100)
    smoke_epochs = math.ceil((warmup_batches + 2 * max(round(64 / config["batch"]), 1) + 1) / batches)
    return dict(data=str(data), project=str(project), name=name, exist_ok=False,
                epochs=smoke_epochs if smoke else config["epochs"], patience=0 if smoke else config["patience"],
                imgsz=1024, batch=config["batch"], device=device, workers=config["workers"],
                seed=config["seed"], deterministic=True, optimizer=config["optimizer"],
                lr0=config["lr0"], lrf=.01, nbs=64, warmup_epochs=3., warmup_bias_lr=0.,
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
    name = ("smoke-" if args.mode == "smoke" else "") + args.variant
    with exclusive_lock(args.runs / ".locks" / (name + ".lock")):
        return run_locked(args, config)


def run_locked(args, config):
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
            checks = smoke_done.get("checks", {})
            if not all(checks.get(k) for k in ("finite_checkpoint", "finite_inference", "weights_changed")) or checks.get("post_warmup_steps", 0) < 2:
                raise ValueError("Smoke completion lacks numerical and post-warmup checks")
            if digest(smoke_folder / "fit/weights/best.pt") != smoke_done["best_sha256"]:
                raise ValueError("Smoke checkpoint changed")
    recover = args.resume or getattr(args, "resume_if_needed", False)
    recovery = None
    if folder.exists():
        if not recover:
            raise ValueError(f"Run exists: {folder}; use --resume-if-needed to recover this recipe")
        if not (folder / "recipe.json").exists() and not any(folder.iterdir()):
            write_json(folder / "recipe.json", recipe)
        if read_json(folder / "recipe.json") != recipe:
            raise ValueError("Code/config/data changed; cannot resume the same experiment")
        if (folder / "complete.json").exists():
            done = read_json(folder / "complete.json")
            if done["recipe_sha256"] != digest(folder / "recipe.json") or done["best_sha256"] != digest(folder / "fit/weights/best.pt"):
                raise ValueError("Completed run changed")
            print(f"Already completed and verified: {folder}", flush=True)
            return done
        recovery = read_recovery(folder, digest(folder / "recipe.json"))
        if recovery:
            restore_recovery(folder, recovery)
        else:
            # No verified epoch exists. Preserve the partial attempt, then start cleanly.
            archive = folder / "interrupted" / uuid.uuid4().hex
            for filename in ("fit", "timing.json"):
                path = folder / filename
                if path.exists():
                    archive.mkdir(parents=True, exist_ok=True)
                    path.rename(archive / filename)
    else:
        if args.resume:
            raise ValueError("No run to resume")
        folder.mkdir(parents=True)
        write_json(folder / "recipe.json", recipe)
    write_json(folder / f"environment-{environment['slurm_job_id']}.json", {**environment, "git_commit": git_revision()})
    data = write_dataset_yaml(args.prepared, folder, smoke)
    from ultralytics import YOLO, settings
    settings.update({"sync": False, "wandb": False, "mlflow": False, "clearml": False,
                     "comet": False, "neptune": False})
    smoke_images = len((folder / "smoke-train.txt").read_text().splitlines()) if smoke else 32
    if smoke_images == 0:
        raise ValueError("No smoke training images")
    arguments = training_arguments(config, data, folder, "fit", smoke=smoke, smoke_images=smoke_images)
    write_json(folder / "requested-arguments.json", arguments)
    monitor = TrainingMonitor(folder, restored=recovery["monitor"] if recovery else None)
    start = time.monotonic()
    if not recovery or not recovery["training_finished"]:
        model = YOLO(str(folder / recovery["last"] if recovery else weights))
        monitor.install(model)
        if recovery:
            def restore_stopper(trainer):
                for key, value in recovery["stopper"].items():
                    setattr(trainer.stopper, key, value)
            model.add_callback("on_pretrain_routine_end", restore_stopper)
            model.train(trainer=checked_trainer(), resume=True)
        else:
            model.train(trainer=checked_trainer(), **arguments)
    best = folder / "fit/weights/best.pt"
    if not best.is_file():
        raise RuntimeError("Training ended without best.pt")
    checks = monitor.completion_checks(smoke)
    sample = next(row for row in read_json(args.prepared / "tiles.json") if row["split"] == "val")
    checks.update(validate_checkpoint(best, args.prepared / sample["image"]))
    completion = {"best": str(best), "best_sha256": digest(best),
               "recipe_sha256": digest(folder / "recipe.json"), "elapsed_seconds": time.monotonic() - start,
               "elapsed_scope": "current_attempt_after_setup",
               "completed_epoch_seconds": sum(row["epoch_seconds"] for row in monitor.state["epoch_times"]),
               "epoch_times": monitor.state["epoch_times"], "checks": checks,
               "mode": args.mode, "annotation_status": config["evaluation_status"]}
    write_json(folder / "complete.json", completion)
    print(f"Completed {args.mode} {args.variant}: {best}", flush=True)
    return completion


def main():
    parser = argparse.ArgumentParser(description="Train native-1024 cattle detector inside a SLURM GPU allocation")
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PACKAGE / "config.json")
    parser.add_argument("--variant", choices=["yolov8n", "yolov8s"], required=True)
    parser.add_argument("--mode", choices=["smoke", "train"], default="train")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-if-needed", action="store_true", help="Start, recover, or verify an already completed matching recipe")
    args = parser.parse_args()
    for key in ("prepared", "weights", "runs", "config"):
        setattr(args, key, getattr(args, key).resolve())
    run(args)


if __name__ == "__main__":
    main()
