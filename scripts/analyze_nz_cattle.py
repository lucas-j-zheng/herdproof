#!/usr/bin/env python3
"""Structural and statistical audit of New Zealand Cattle Detection."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

FILENAME = re.compile(
    r"^\d+_(.+)_(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?P<shifted>_shifted)?$"
)


def percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("sample_manifest", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    images = sorted((root / "cow_images").glob("*.png"))
    invalid_lines = []
    missing_labels = []
    point_counts = []
    image_records = []
    dimensions = Counter()
    source_groups = Counter()
    location_groups: dict[str, list[str]] = defaultdict(list)
    shifted_images = 0
    hashes: dict[str, list[str]] = defaultdict(list)
    duplicate_points = 0
    duplicate_point_samples = []
    unparsed_filename_samples = []

    for image_path in images:
        label_path = Path(str(image_path) + ".mask.0.txt")
        if not label_path.is_file():
            missing_labels.append(str(image_path.relative_to(root)))
            continue
        with Image.open(image_path) as image:
            image.load()
            width, height = image.size
            dimensions[f"{width}x{height}"] += 1
        points = []
        for line_number, line in enumerate(label_path.read_text().splitlines(), 1):
            fields = line.strip().split(",")
            try:
                if len(fields) != 2:
                    raise ValueError("expected x,y")
                x, y = (int(field) for field in fields)
                if not (0 <= x < width and 0 <= y < height):
                    raise ValueError("point outside image")
                points.append((x, y))
            except ValueError as exc:
                invalid_lines.append({
                    "label": str(label_path.relative_to(root)),
                    "line": line_number,
                    "value": line,
                    "reason": str(exc),
                })
        point_frequencies = Counter(points)
        repeated = {f"{x},{y}": count for (x, y), count in point_frequencies.items() if count > 1}
        duplicate_points += sum(count - 1 for count in point_frequencies.values() if count > 1)
        if repeated:
            duplicate_point_samples.append({
                "label": str(label_path.relative_to(root)),
                "repeated_points": repeated,
            })
        match = FILENAME.match(image_path.stem)
        source_group = match.group(1) if match else "<unparsed>"
        shifted = bool(match and match.group("shifted"))
        shifted_images += int(shifted)
        if not match and len(unparsed_filename_samples) < 30:
            unparsed_filename_samples.append(image_path.name)
        source_groups[source_group] += 1
        relative = str(image_path.relative_to(root))
        if match:
            location_groups[f"{source_group}:{match.group(2)},{match.group(3)}"].append(relative)
        hashes[digest(image_path)].append(relative)
        point_counts.append(len(points))
        image_records.append({
            "image": relative,
            "label": str(label_path.relative_to(root)),
            "points": len(points),
            "source_group": source_group,
            "shifted": shifted,
        })

    rng = random.Random(5908869)
    random_records = rng.sample(image_records, min(12, len(image_records)))
    ordered = sorted(image_records, key=lambda item: (item["points"], item["image"]))
    duplicate_labels = {item["label"] for item in duplicate_point_samples}
    selected = {
        "random": random_records,
        "sparsest": ordered[:8],
        "densest": list(reversed(ordered[-12:])),
        "duplicate_points": [
            record for record in image_records if record["label"] in duplicate_labels
        ],
    }

    duplicate_hash_groups = [members for members in hashes.values() if len(members) > 1]
    repeated_location_groups = {
        key: members for key, members in location_groups.items() if len(members) > 1
    }
    result = {
        "images": len(images),
        "paired_images": len(image_records),
        "missing_labels": missing_labels,
        "valid_points": sum(point_counts),
        "invalid_lines": invalid_lines,
        "duplicate_points_within_labels": duplicate_points,
        "duplicate_point_samples": duplicate_point_samples,
        "unparsed_filename_samples": unparsed_filename_samples,
        "image_dimensions": dict(sorted(dimensions.items())),
        "source_groups": dict(sorted(source_groups.items())),
        "shifted_images": shifted_images,
        "unique_source_locations": len(location_groups),
        "repeated_source_locations": len(repeated_location_groups),
        "sample_repeated_source_locations": dict(sorted(repeated_location_groups.items())[:20]),
        "points_per_image": {
            "minimum": min(point_counts) if point_counts else None,
            "p10": percentile(point_counts, 0.10),
            "median": percentile(point_counts, 0.50),
            "p90": percentile(point_counts, 0.90),
            "p95": percentile(point_counts, 0.95),
            "maximum": max(point_counts) if point_counts else None,
            "mean": sum(point_counts) / len(point_counts) if point_counts else None,
        },
        "exact_duplicate_image_groups": duplicate_hash_groups,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.sample_manifest.write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("sample categories", {key: len(value) for key, value in selected.items()})
    if missing_labels or invalid_lines or duplicate_points or duplicate_hash_groups:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
