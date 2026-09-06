"""Numerical checks, full epoch timing, and bounded crash-safe recovery snapshots."""
from __future__ import annotations

import math
import os
import shutil
import time
import uuid
from pathlib import Path

from training.common import atomic_copy, digest, read_json, write_json


def ensure_finite(value, label):
    import torch
    tensors = []

    def visit(item):
        if isinstance(item, torch.nn.Module):
            visit(item.state_dict())
        elif isinstance(item, torch.Tensor):
            if item.is_floating_point() or item.is_complex():
                tensors.append(torch.isfinite(item).all())
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child)
        elif isinstance(item, (float, int)) and not math.isfinite(item):
            raise RuntimeError(f"Nonfinite {label}")

    visit(value)
    # Group by device to avoid synchronizing for every individual parameter.
    for device in {t.device for t in tensors}:
        if not torch.stack([t for t in tensors if t.device == device]).all().item():
            raise RuntimeError(f"Nonfinite {label}")


def checked_trainer():
    from ultralytics.models.yolo.detect import DetectionTrainer

    class CheckedDetectionTrainer(DetectionTrainer):
        def get_dataloader(self, dataset_path, batch_size=16, rank=0, mode="train"):
            # Upstream doubles validation workers; respect the SLURM CPU allocation.
            requested = self.args.workers
            allocated = int(os.environ.get("SLURM_CPUS_PER_TASK", max(requested, 1)))
            self.args.workers = min(requested, allocated // (2 if mode == "val" else 1))
            try:
                return super().get_dataloader(dataset_path, batch_size, rank, mode)
            finally:
                self.args.workers = requested

        def optimizer_step(self):
            ensure_finite((self.loss, self.loss_items), "training loss")
            ensure_finite([p.grad for p in self.model.parameters()], "gradients")
            self.run_callbacks("on_before_verified_step")
            super().optimizer_step()
            ensure_finite(self.model, "model after optimizer step")
            self.run_callbacks("on_verified_step")

        def validate(self):
            metrics, fitness = super().validate()
            ensure_finite((metrics, fitness, self.validator.loss), "validation")
            return metrics, fitness

    return CheckedDetectionTrainer


def read_recovery(folder, recipe_sha256):
    manifest = folder / "recovery.json"
    if not manifest.exists():
        return None
    state = read_json(manifest)
    if state["recipe_sha256"] != recipe_sha256:
        raise ValueError("Recovery checkpoint belongs to a different recipe")
    for entry in state["checkpoints"]:
        if all((folder / entry[key]).is_file() and digest(folder / entry[key]) == entry[key + "_sha256"]
               for key in ("last", "best")):
            return entry
    raise ValueError("No verified recovery checkpoint; preserve the run for inspection")


def restore_recovery(folder, entry):
    """Restore best and trim logs to the checkpoint, including fallback to the prior epoch."""
    import csv
    from training.common import atomic_output
    atomic_copy(folder / entry["best"], folder / "fit/weights/best.pt")
    csv_path = folder / "fit/results.csv"
    if csv_path.exists():
        with csv_path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = [row for row in reader if int(row["epoch"]) <= entry["epoch"]]
        with atomic_output(csv_path) as temporary:
            with temporary.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
    write_json(folder / "timing.json", entry["monitor"]["epoch_times"])


class TrainingMonitor:
    def __init__(self, folder, *, device_type="cuda", restored=None):
        self.folder = Path(folder)
        self.device_type = device_type
        self.state = restored or {"optimizer_steps": 0, "post_warmup_steps": 0,
                                  "weights_changed": False, "epoch_times": []}
        self.epoch_start = None
        self.probes = None

    def install(self, model):
        events = {"on_train_epoch_start": self.start_epoch, "on_train_batch_start": self.start_batch,
                  "on_train_batch_end": self.end_batch, "on_train_epoch_end": self.end_training,
                  "on_before_verified_step": self.before_step, "on_verified_step": self.after_step,
                  "on_fit_epoch_end": self.finish_epoch}
        for event, callback in events.items():
            model.callbacks.setdefault(event, []).append(callback)

    def start_epoch(self, trainer):
        if next(trainer.model.parameters()).device.type != self.device_type:
            raise RuntimeError(f"Training unexpectedly left {self.device_type}")
        self.epoch_start = time.monotonic()
        self.batch_index = -1

    def start_batch(self, trainer):
        self.batch_index += 1

    def end_batch(self, trainer):
        ensure_finite((trainer.loss, trainer.loss_items), "training loss")

    def before_step(self, trainer):
        if not self.state["weights_changed"]:
            self.probes = [(p, p.detach().clone()) for p in trainer.model.parameters() if p.requires_grad]

    def after_step(self, trainer):
        import torch
        self.state["optimizer_steps"] += 1
        nb = len(trainer.train_loader)
        warmup = max(round(trainer.args.warmup_epochs * nb), 100) if trainer.args.warmup_epochs > 0 else -1
        if trainer.epoch * nb + self.batch_index > warmup:
            self.state["post_warmup_steps"] += 1
        if self.probes is not None:
            self.state["weights_changed"] = bool(torch.stack([(p.detach() != old).any() for p, old in self.probes]).any().item())
            self.probes = None

    def end_training(self, trainer):
        self.training_seconds = time.monotonic() - self.epoch_start

    def finish_epoch(self, trainer):
        # Ultralytics calls this again during final_eval; count each epoch once.
        if self.epoch_start is None:
            return
        ensure_finite((trainer.metrics, trainer.fitness), "epoch metrics")
        generation = self.folder / "recovery" / f"epoch-{trainer.epoch + 1:04d}-{uuid.uuid4().hex}"
        generation.mkdir(parents=True)
        entry = {"epoch": trainer.epoch + 1, "training_finished": bool(trainer.stop)}
        for key, source in (("last", trainer.last), ("best", trainer.best)):
            target = generation / (key + ".pt")
            atomic_copy(source, target)
            entry[key] = str(target.relative_to(self.folder))
            entry[key + "_sha256"] = digest(target)
        elapsed = time.monotonic() - self.epoch_start
        self.state["epoch_times"].append({"epoch": trainer.epoch + 1, "training_seconds": self.training_seconds,
                                          "epoch_seconds": elapsed, "validation_and_save_seconds": elapsed - self.training_seconds})
        entry["monitor"] = self.state
        # Preserve early-stopping patience across a resumed job as well as model/optimizer state.
        entry["stopper"] = {key: getattr(trainer.stopper, key) for key in ("best_epoch", "best_fitness", "possible_stop")}
        manifest = self.folder / "recovery.json"
        # If recovery fell back after corruption, retain that verified generation.
        previous = [read_recovery(self.folder, digest(self.folder / "recipe.json"))] if manifest.exists() else []
        entries = [entry, *previous]
        write_json(manifest, {"recipe_sha256": digest(self.folder / "recipe.json"), "checkpoints": entries})
        write_json(self.folder / "timing.json", self.state["epoch_times"])
        # Only delete our own superseded snapshots after publishing the new pointer.
        retained = {str((self.folder / item["last"]).parent) for item in entries}
        for old in generation.parent.iterdir():
            if old.is_dir() and str(old) not in retained:
                shutil.rmtree(old)
        self.epoch_start = None

    def completion_checks(self, smoke):
        if not self.state["weights_changed"] or self.state["optimizer_steps"] < 1:
            raise RuntimeError("Training did not demonstrate trainable weight updates")
        if smoke and self.state["post_warmup_steps"] < 2:
            raise RuntimeError("Smoke must exercise at least two post-warmup optimizer updates")
        return {key: self.state[key] for key in ("optimizer_steps", "post_warmup_steps", "weights_changed")}


def validate_checkpoint(checkpoint, image_path, device=0):
    import numpy as np
    import torch
    from PIL import Image
    from ultralytics import YOLO
    model = YOLO(str(checkpoint)).model.to(device if device == "cpu" else f"cuda:{device}").float().eval()
    ensure_finite(model, "checkpoint tensors")
    with Image.open(image_path) as image:
        if image.size != (1024, 1024):
            raise ValueError("Checkpoint probe must use a native 1024 tile")
        pixels = np.array(image.convert("RGB"), copy=True)
    tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to(next(model.parameters()).device).float() / 255.
    with torch.inference_mode():
        ensure_finite(model(tensor), "reloaded checkpoint inference")
    return {"finite_checkpoint": True, "finite_inference": True}
