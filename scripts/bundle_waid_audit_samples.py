#!/usr/bin/env python3
"""Create a bounded tar of preselected WAID image/label pairs without decoding them."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

MAX_FILES = 150
MAX_TOTAL_BYTES = 500 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("output_tar", type=Path)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    data_root = (dataset_root / "WAID").resolve()
    audit = json.loads(args.audit_json.read_text())
    records = audit["visual_sample_manifest"]
    if len(records) > 75:
        raise ValueError(f"sample manifest unexpectedly large: {len(records)}")

    files: list[Path] = []
    for record in records:
        relative_image = Path(record["relative_path"])
        image = (data_root / relative_image).resolve()
        label = (
            data_root / "labels" / record["split"] / f"{relative_image.stem}.txt"
        ).resolve()
        for path in (image, label):
            if data_root not in path.parents:
                raise ValueError(f"path escapes dataset: {path}")
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"unsafe sample path: {path}")
            files.append(path)

    files = sorted(set(files))
    total_bytes = sum(path.stat().st_size for path in files)
    if len(files) > MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
        raise ValueError(f"bundle limit exceeded: {len(files)} files, {total_bytes} bytes")

    args.output_tar.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output_tar, "w") as archive:
        archive.add(args.audit_json, arcname="waid-usability.json", recursive=False)
        for path in files:
            archive.add(path, arcname=str(Path("WAID") / path.relative_to(data_root)), recursive=False)

    print(f"Created {args.output_tar}")
    print(f"Sample pairs: {len(records)}")
    print(f"Input bytes: {total_bytes}")
    print(f"Archive bytes: {args.output_tar.stat().st_size}")


if __name__ == "__main__":
    main()
