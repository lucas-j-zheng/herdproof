#!/usr/bin/env python3
"""Test MP4 metadata/hash limits using a tiny synthetic video, not cattle footage.

Requires existing ffmpeg/ffprobe binaries; installs nothing. Temporary videos are
deleted. This is not a test of QR challenges, app attestation, or cattle counting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def inspect(path: Path) -> dict:
    metadata = json.loads(run(
        "ffprobe", "-v", "error", "-show_entries", "format_tags",
        "-of", "json", str(path),
    ))["format"].get("tags", {})
    frame_md5 = run("ffmpeg", "-v", "error", "-i", str(path),
                    "-map", "0:v:0", "-f", "framemd5", "-")
    frames = [line for line in frame_md5.splitlines()
              if line and not line.startswith("#")]
    return {
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "decoded_frame_rows_sha256": hashlib.sha256(
            "\n".join(frames).encode()).hexdigest(),
        "decoded_frames": len(frames),
        "tags": metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="herdproof-metadata-probe-") as directory:
        original = Path(directory) / "original.mp4"
        changed = Path(directory) / "metadata_changed.mp4"
        stripped = Path(directory) / "metadata_stripped.mp4"
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=320x240:r=5", "-t", "2", "-c:v", "mpeg4",
            "-metadata", "creation_time=2020-01-01T00:00:00Z",
            "-metadata", "location=+00.0000+000.0000/", str(original))
        run("ffmpeg", "-v", "error", "-i", str(original), "-map", "0",
            "-c", "copy", "-metadata", "creation_time=2026-09-05T12:00:00Z",
            "-metadata:s:v:0", "creation_time=2026-09-05T12:00:00Z",
            "-metadata", "location=+01.0000+001.0000/", str(changed))
        run("ffmpeg", "-v", "error", "-i", str(original), "-map", "0",
            "-c", "copy", "-map_metadata", "-1", "-map_metadata:s:v", "-1",
            str(stripped))
        records = {name: inspect(path) for name, path in (
            ("original", original), ("metadata_changed", changed),
            ("metadata_stripped", stripped))}

    original_record = records["original"]
    changed_record = records["metadata_changed"]
    stripped_record = records["metadata_stripped"]
    checks = {
        "file_hash_changed": original_record["file_sha256"] != changed_record["file_sha256"],
        "decoded_video_unchanged": original_record["decoded_frame_rows_sha256"] == changed_record["decoded_frame_rows_sha256"],
        "timestamp_changed": original_record["tags"].get("creation_time") != changed_record["tags"].get("creation_time"),
        "location_changed": original_record["tags"].get("location") != changed_record["tags"].get("location"),
        "stripped_video_unchanged": original_record["decoded_frame_rows_sha256"] == stripped_record["decoded_frame_rows_sha256"],
        "timestamp_and_location_removed": all(
            tag not in stripped_record["tags"] for tag in ("creation_time", "location")),
    }
    result = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Synthetic MP4 metadata edits; no cattle, QR, or attestation tested",
        "ffmpeg_version": run("ffmpeg", "-version").splitlines()[0],
        "records": records,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "interpretation": (
            "MP4 time/location tags can change while decoded frames stay identical. "
            "File SHA-256 detects exact bytes, not all reuse of visual content. "
            "A reused nonce could still reject this file; no full-system bypass is demonstrated."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "checks": checks}, indent=2))
    if not result["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
