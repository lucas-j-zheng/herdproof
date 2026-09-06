#!/usr/bin/env python3
"""Create a bounded archive of New Zealand cattle audit samples."""

from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

MAX_FILES = 120
MAX_BYTES = 100 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads(args.manifest.read_text())
    paths = set()
    for records in manifest.values():
        for record in records:
            for key in ("image", "label"):
                path = (root / record[key]).resolve()
                if root not in path.parents or not path.is_file() or path.is_symlink():
                    raise ValueError(f"unsafe sample path: {path}")
                paths.add(path)
    if len(paths) > MAX_FILES:
        raise ValueError(f"too many files: {len(paths)}")
    total = sum(path.stat().st_size for path in paths)
    if total > MAX_BYTES:
        raise ValueError(f"sample files exceed byte limit: {total}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w") as archive:
        archive.add(args.manifest, arcname="nz-cattle-samples.json", recursive=False)
        for path in sorted(paths):
            archive.add(path, arcname=str(Path("dataset") / path.relative_to(root)), recursive=False)
    print(f"files={len(paths)} input_bytes={total} archive_bytes={args.output.stat().st_size}")


if __name__ == "__main__":
    main()
