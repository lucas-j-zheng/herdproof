#!/usr/bin/env python3
"""Validate and extract an untrusted ZIP without following links or escaping root."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-members", type=int, default=100_000)
    args = parser.parse_args()

    archive = args.archive.resolve()
    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit(f"destination already exists: {destination}")

    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > args.max_members:
            raise ValueError(f"too many ZIP members: {len(members)}")
        total_size = sum(member.file_size for member in members)
        compressed_size = sum(member.compress_size for member in members)
        if total_size > args.max_bytes:
            raise ValueError(f"uncompressed size exceeds limit: {total_size}")

        extensions = Counter()
        roots = Counter()
        for member in members:
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError(f"unsafe ZIP path: {member.filename!r}")
            if member.flag_bits & 0x1:
                raise ValueError(f"encrypted ZIP member: {member.filename!r}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"symbolic link in ZIP: {member.filename!r}")
            if member.file_size > 2 * 1024**3:
                raise ValueError(f"individual member exceeds 2 GiB: {member.filename!r}")
            if member.compress_size and member.file_size / member.compress_size > 500:
                raise ValueError(f"suspicious compression ratio: {member.filename!r}")
            if not member.is_dir():
                extensions[name.suffix.lower() or "<none>"] += 1
            roots[name.parts[0]] += 1

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            source.extractall(temporary)
            # Reading every member during extraction causes zipfile to verify CRC values.
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    summary = {
        "archive": str(archive),
        "destination": str(destination),
        "members": len(members),
        "compressed_member_bytes": compressed_size,
        "uncompressed_bytes": total_size,
        "extensions": dict(sorted(extensions.items())),
        "top_level_entries": dict(sorted(roots.items())),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    (destination / ".safe-extraction.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
