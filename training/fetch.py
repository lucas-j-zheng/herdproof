"""Download pinned assets on a compute node; never execute dataset archive content."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from training.common import PACKAGE, digest, read_json, require_compute_job, write_json


def download(url, destination, expected, algorithm="sha256", expected_bytes=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        partial = destination.with_suffix(destination.suffix + ".partial")
        subprocess.run(["curl", "--fail", "--location", "--retry", "5", "--continue-at", "-",
                        "--output", str(partial), url], check=True)
        candidate = partial
    else:
        candidate = destination
    if expected_bytes is not None and candidate.stat().st_size != expected_bytes:
        raise ValueError(f"Unexpected download size: {candidate}")
    if digest(candidate, algorithm) != expected:
        raise ValueError(f"Checksum mismatch: {candidate}; preserve for inspection or remove before retry")
    if candidate != destination:
        candidate.rename(destination)


def safe_extract(archive, destination):
    if destination.exists():
        raise ValueError("Extraction destination already exists")
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > 100_000 or sum(m.file_size for m in members) > 40 * 1024**3:
            raise ValueError("Archive exceeds extraction limits")
        seen = set()
        for m in members:
            p = PurePosixPath(m.filename)
            mode = m.external_attr >> 16
            if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in m.filename:
                raise ValueError("Unsafe archive path")
            if stat.S_ISLNK(mode) or m.flag_bits & 1 or m.file_size > 2 * 1024**3:
                raise ValueError("Unsupported archive member")
            if p in seen:
                raise ValueError("Duplicate archive path")
            seen.add(p)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.extract-", dir=destination.parent))
        try:
            source.extractall(temporary)  # zipfile validates each extracted member's CRC.
            temporary.rename(destination)
        except BaseException:
            shutil.rmtree(temporary)
            raise
    write_json(destination / ".download-verification.json", {"archive": archive.name, "sha256": digest(archive),
               "assets_sha256": digest(PACKAGE / "assets.json"), "members": len(members)})


def main():
    parser = argparse.ArgumentParser(description="Fetch checksum-pinned weights and, if needed, the full ICAERUS dataset")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    require_compute_job()
    assets = read_json(PACKAGE / "assets.json")
    for variant, entry in assets["weights"].items():
        download(entry["url"], args.root / "weights" / (variant + ".pt"), entry["sha256"])
    if not args.source.exists():
        entry = assets["dataset"]
        archive = args.root / "downloads" / entry["filename"]
        download(entry["url"], archive, entry["md5"], "md5", entry["bytes"])
        safe_extract(archive, args.source)
    else:
        print(f"Reusing source directory: {args.source}; preparation will hash and validate its images/labels")


if __name__ == "__main__":
    main()
