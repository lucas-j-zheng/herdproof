from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def load_config(path: Path = PACKAGE / "config.json"):
    config = read_json(path)
    if config["tile_size"] != 1024:
        raise ValueError("This protocol requires native 1024-pixel inputs")
    if not 0 <= config["tile_overlap"] < 1:
        raise ValueError("Invalid tile overlap")
    if config["label_policy"] != "provisional_positive_images_and_positive_tiles_only":
        raise ValueError("Unsupported label policy")
    return config


def require_compute_job():
    # CLI entrypoints refuse heavy work on any host identified as Oscar/login.
    host = socket.getfqdn().lower()
    on_cluster = any(x in host for x in ("oscar", "ccv.brown", "login"))
    if on_cluster and not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Run this command inside sbatch/srun, never on a login node")


def configure_runtime(cache: Path):
    for key, name in (("YOLO_CONFIG_DIR", "ultralytics"), ("MPLCONFIGDIR", "matplotlib")):
        folder = cache / name
        folder.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(folder)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_OFFLINE"] = "true"
    os.environ["WANDB_DISABLED"] = "true"
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    # Upstream checks for Arial even with plots=False. Use a bundled font alias so it never downloads one.
    import matplotlib
    font = Path(os.environ["YOLO_CONFIG_DIR"]) / "Ultralytics/Arial.ttf"
    font.parent.mkdir(parents=True, exist_ok=True)
    if not font.exists():
        shutil.copyfile(Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf", font)


def cuda_environment():
    require_compute_job()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("GPU training/evaluation requires a SLURM allocation")
    import sys
    import platform
    import importlib.metadata
    import torch
    expected = {"torch": "2.8.0+cu126", "torchvision": "0.23.0+cu126", "ultralytics": "8.3.200"}
    versions = {name: importlib.metadata.version(name) for name in expected}
    if versions != expected or sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Wrong environment: {sys.version}; {versions}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; refusing CPU fallback")
    # Exercise kernels and compiled torchvision ops before loading data.
    from torchvision.ops import nms
    a = torch.ones((32, 32), device="cuda")
    _ = a @ a
    nms(torch.tensor([[0., 0., 2., 2.]], device="cuda"), torch.ones(1, device="cuda"), .5)
    torch.cuda.synchronize()
    props = torch.cuda.get_device_properties(0)
    return {"versions": versions, "python": sys.version, "platform": platform.platform(),
            "gpu": props.name, "gpu_memory_bytes": props.total_memory,
            "cuda": torch.version.cuda, "slurm_job_id": os.environ["SLURM_JOB_ID"]}


def code_fingerprint():
    # Ignore untracked local research; bind runs to executable training sources.
    files = sorted(p for p in PACKAGE.rglob("*") if p.suffix in {".py", ".sh", ".json", ".toml", ".lock"})
    return {str(p.relative_to(PACKAGE)): digest(p) for p in files}


def git_revision():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PACKAGE, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def verify_prepared(root: Path, config_path: Path, verify_tiles=True):
    completion = read_json(root / "complete.json")
    if completion["config_sha256"] != digest(config_path):
        raise ValueError("Prepared data uses a different configuration; prepare a new output directory")
    if "preparation_code_sha256" in completion and completion["preparation_code_sha256"] != digest(PACKAGE / "data.py"):
        raise ValueError("Preparation code changed; rebuild in a new output directory")
    for filename, expected in completion["manifests"].items():
        if digest(root / filename) != expected:
            raise ValueError(f"Prepared manifest changed: {filename}")
    if verify_tiles:
        for row in read_json(root / "tiles.json"):
            for field in ("image", "label"):
                if digest(root / row[field]) != row[field + "_sha256"]:
                    raise ValueError(f"Prepared tile changed: {row[field]}")
    return completion
