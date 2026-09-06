#!/usr/bin/env python3
"""Bundle a bounded set of perceptual-leakage candidate pairs for review."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

MAX_PAIRS = 24
MAX_TOTAL_BYTES = 300 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("leakage_json", type=Path)
    parser.add_argument("output_tar", type=Path)
    args = parser.parse_args()

    data_root = (args.dataset_root.resolve() / "WAID").resolve()
    report = json.loads(args.leakage_json.read_text())
    pairs = report["closest_cross_split_pairs"][:MAX_PAIRS]
    files = set()
    for pair in pairs:
        for key in ("left", "right"):
            relative = Path(pair[key])
            image = (data_root / relative).resolve()
            label = (data_root / "labels" / relative.parts[1] / f"{relative.stem}.txt").resolve()
            for path in (image, label):
                if data_root not in path.parents or not path.is_file() or path.is_symlink():
                    raise ValueError(f"unsafe candidate path: {path}")
                files.add(path)

    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > MAX_TOTAL_BYTES:
        raise ValueError(f"candidate bundle exceeds limit: {total_bytes}")

    args.output_tar.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output_tar, "w") as archive:
        archive.add(args.leakage_json, arcname="waid-perceptual-leakage.json", recursive=False)
        for path in sorted(files):
            archive.add(path, arcname=str(Path("WAID") / path.relative_to(data_root)), recursive=False)

    print(f"Candidate pairs: {len(pairs)}")
    print(f"Unique files: {len(files)}")
    print(f"Input bytes: {total_bytes}")
    print(f"Archive bytes: {args.output_tar.stat().st_size}")


if __name__ == "__main__":
    main()
