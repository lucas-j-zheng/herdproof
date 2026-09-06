#!/usr/bin/env python3
"""Conservatively audit an untrusted WAID checkout without decoding images."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_CLASSES = ["sheep", "cattle", "seal", "camelus", "kiang", "zebra"]
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".txt", ".md"}
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_LABEL_BYTES = 5 * 1024 * 1024
MAX_DIMENSION = 50_000


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    """Read JPEG dimensions from bounded marker parsing; do not decode pixels."""
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError("missing JPEG SOI marker")
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                raise ValueError("no JPEG frame header")
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker:
                raise ValueError("truncated JPEG marker")
            code = marker[0]
            if code in {0xD8, 0xD9} or 0xD0 <= code <= 0xD7:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                raise ValueError("truncated JPEG segment length")
            segment_length = struct.unpack(">H", length_bytes)[0]
            if segment_length < 2:
                raise ValueError("invalid JPEG segment length")
            if code in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                payload = handle.read(5)
                if len(payload) != 5:
                    raise ValueError("truncated JPEG frame header")
                height, width = struct.unpack(">HH", payload[1:5])
                if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
                    raise ValueError(f"unsafe JPEG dimensions {width}x{height}")
                return width, height
            handle.seek(segment_length - 2, os.SEEK_CUR)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path) -> dict:
    data_root = root / "WAID"
    image_root = data_root / "images"
    label_root = data_root / "labels"
    errors: list[str] = []
    warnings: list[str] = []

    class_file = data_root / "classes.txt"
    classes = [line.strip() for line in class_file.read_text().splitlines() if line.strip()]
    if classes != EXPECTED_CLASSES:
        errors.append(f"unexpected classes: {classes!r}")

    unexpected_files = []
    symlinks = []
    for path in root.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.is_symlink():
            symlinks.append(str(path.relative_to(root)))
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            unexpected_files.append(str(path.relative_to(root)))
    if symlinks:
        errors.append(f"symlinks present: {symlinks[:20]}")
    if unexpected_files:
        errors.append(f"unexpected file types: {unexpected_files[:20]}")

    split_names = sorted(
        set(path.name for path in image_root.iterdir() if path.is_dir())
        | set(path.name for path in label_root.iterdir() if path.is_dir())
    )
    split_stats = {}
    object_counts = Counter()
    cattle_box_widths = []
    cattle_box_heights = []
    image_hashes: dict[str, list[str]] = defaultdict(list)
    dimensions = Counter()
    total_images = 0
    total_labels = 0

    for split in split_names:
        images = {
            path.stem: path
            for path in (image_root / split).iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
        } if (image_root / split).is_dir() else {}
        labels = {
            path.stem: path
            for path in (label_root / split).iterdir()
            if path.is_file() and path.suffix.lower() == ".txt"
        } if (label_root / split).is_dir() else {}

        missing_labels = sorted(set(images) - set(labels))
        missing_images = sorted(set(labels) - set(images))
        if missing_labels:
            errors.append(f"{split}: {len(missing_labels)} images lack labels")
        if missing_images:
            errors.append(f"{split}: {len(missing_images)} labels lack images")

        split_objects = Counter()
        empty_labels = 0
        invalid_labels = 0
        for stem in sorted(set(images) & set(labels)):
            image_path = images[stem]
            label_path = labels[stem]
            image_size = image_path.stat().st_size
            label_size = label_path.stat().st_size
            if not (0 < image_size <= MAX_IMAGE_BYTES):
                errors.append(f"unsafe image size: {image_path} ({image_size})")
                continue
            if not (0 <= label_size <= MAX_LABEL_BYTES):
                errors.append(f"unsafe label size: {label_path} ({label_size})")
                continue

            try:
                width, height = jpeg_dimensions(image_path)
            except Exception as exc:
                errors.append(f"invalid JPEG {image_path}: {exc}")
                continue
            dimensions[(width, height)] += 1
            image_hashes[sha256_file(image_path)].append(
                str(image_path.relative_to(data_root))
            )

            lines = [line.strip() for line in label_path.read_text().splitlines() if line.strip()]
            if not lines:
                empty_labels += 1
            for line_number, line in enumerate(lines, 1):
                fields = line.split()
                try:
                    if len(fields) != 5:
                        raise ValueError(f"expected 5 fields, got {len(fields)}")
                    class_value = float(fields[0])
                    class_id = int(class_value)
                    if class_value != class_id or not 0 <= class_id < len(classes):
                        raise ValueError(f"invalid class {fields[0]!r}")
                    center_x, center_y, box_width, box_height = map(float, fields[1:])
                    values = (center_x, center_y, box_width, box_height)
                    if not all(math.isfinite(value) for value in values):
                        raise ValueError("non-finite coordinate")
                    if not (0 <= center_x <= 1 and 0 <= center_y <= 1):
                        raise ValueError("center outside normalized image")
                    if not (0 < box_width <= 1 and 0 < box_height <= 1):
                        raise ValueError("invalid normalized box size")
                    if center_x - box_width / 2 < -1e-6 or center_x + box_width / 2 > 1 + 1e-6:
                        raise ValueError("box crosses horizontal image bounds")
                    if center_y - box_height / 2 < -1e-6 or center_y + box_height / 2 > 1 + 1e-6:
                        raise ValueError("box crosses vertical image bounds")
                    split_objects[class_id] += 1
                    object_counts[class_id] += 1
                    if class_id == 1:
                        cattle_box_widths.append(box_width * width)
                        cattle_box_heights.append(box_height * height)
                except Exception as exc:
                    invalid_labels += 1
                    if len(errors) < 500:
                        errors.append(f"{label_path}:{line_number}: {exc}")

        split_stats[split] = {
            "images": len(images),
            "labels": len(labels),
            "paired": len(set(images) & set(labels)),
            "missing_labels": len(missing_labels),
            "missing_images": len(missing_images),
            "empty_labels": empty_labels,
            "invalid_label_lines": invalid_labels,
            "objects_by_class": {
                classes[index]: split_objects[index] for index in range(len(classes))
            },
        }
        total_images += len(images)
        total_labels += len(labels)

    duplicates = [paths for paths in image_hashes.values() if len(paths) > 1]
    cross_split_duplicates = [
        paths for paths in duplicates
        if len({Path(path).parts[1] for path in paths}) > 1
    ]
    if cross_split_duplicates:
        warnings.append(
            f"{len(cross_split_duplicates)} exact image hashes occur across splits"
        )
    if total_images != 14_375:
        warnings.append(f"paper reports 14375 images; checkout has {total_images}")

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(int((len(ordered) - 1) * fraction), len(ordered) - 1)], 2)

    return {
        "root": str(root),
        "classes": classes,
        "splits": split_stats,
        "totals": {
            "images": total_images,
            "labels": total_labels,
            "objects_by_class": {
                classes[index]: object_counts[index] for index in range(len(classes))
            },
            "unique_image_hashes": len(image_hashes),
            "duplicate_hash_groups": len(duplicates),
            "cross_split_duplicate_hash_groups": len(cross_split_duplicates),
        },
        "cattle_box_pixels": {
            "width_p10": percentile(cattle_box_widths, 0.10),
            "width_p50": percentile(cattle_box_widths, 0.50),
            "width_p90": percentile(cattle_box_widths, 0.90),
            "height_p10": percentile(cattle_box_heights, 0.10),
            "height_p50": percentile(cattle_box_heights, 0.50),
            "height_p90": percentile(cattle_box_heights, 0.90),
        },
        "top_dimensions": [
            {"width": width, "height": height, "images": count}
            for (width, height), count in dimensions.most_common(20)
        ],
        "sample_cross_split_duplicates": cross_split_duplicates[:20],
        "warnings": warnings,
        "errors": errors[:500],
        "passed_structural_validation": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed_structural_validation"] else 1)


if __name__ == "__main__":
    main()
