#!/usr/bin/env python3
"""Analyze WAID's cattle subset and split leakage without decoding image pixels."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from validate_waid import jpeg_dimensions

RF_SUFFIX = re.compile(r"(?i)\.rf\.[0-9a-f]+$")
TRAILING_JPG = re.compile(r"(?i)_jpe?g$")
TRAILING_FRAME = re.compile(r"^(.*?)[_-](\d+)$")


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {name: None for name in ("min", "p10", "p25", "p50", "p75", "p90", "max")}
    ordered = sorted(values)

    def pick(fraction: float) -> float:
        return round(ordered[round((len(ordered) - 1) * fraction)], 3)

    return {
        "min": round(ordered[0], 3),
        "p10": pick(0.10),
        "p25": pick(0.25),
        "p50": pick(0.50),
        "p75": pick(0.75),
        "p90": pick(0.90),
        "max": round(ordered[-1], 3),
    }


def source_key(stem: str) -> str:
    return TRAILING_JPG.sub("", RF_SUFFIX.sub("", stem))


def parse_label(line: str) -> tuple[int, float, float, float, float]:
    fields = line.split()
    if len(fields) != 5:
        raise ValueError(f"field_count:{len(fields)}")
    class_value = float(fields[0])
    class_id = int(class_value)
    if class_value != class_id or not 0 <= class_id < 6:
        raise ValueError(f"class:{fields[0]}")
    x, y, width, height = map(float, fields[1:])
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        raise ValueError("non_finite")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError(f"center:{x},{y}")
    if not (0 < width <= 1 and 0 < height <= 1):
        raise ValueError(f"size:{width},{height}")
    if x - width / 2 < -1e-6 or x + width / 2 > 1 + 1e-6:
        raise ValueError(f"horizontal_bounds:{x},{width}")
    if y - height / 2 < -1e-6 or y + height / 2 > 1 + 1e-6:
        raise ValueError(f"vertical_bounds:{y},{height}")
    return class_id, x, y, width, height


def stable_sample(records: list[dict], count: int, salt: str) -> list[dict]:
    ranked = sorted(
        records,
        key=lambda record: hashlib.sha256(
            f"{salt}:{record['relative_path']}".encode()
        ).digest(),
    )
    return ranked[:count]


def analyze(root: Path) -> dict:
    data_root = root / "WAID"
    image_root = data_root / "images"
    label_root = data_root / "labels"
    splits = sorted(path.name for path in image_root.iterdir() if path.is_dir())

    source_families: dict[str, list[tuple[str, str]]] = defaultdict(list)
    source_families_by_class: dict[int, dict[str, list[tuple[str, str]]]] = {
        class_id: defaultdict(list) for class_id in range(6)
    }
    sequence_frames: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    records: list[dict] = []
    invalid_counts = Counter()
    invalid_samples = []
    images_by_class = {split: Counter() for split in splits}
    objects_by_class = {split: Counter() for split in splits}
    dimensions = Counter()
    image_sizes = []
    cattle_widths = []
    cattle_heights = []
    cattle_areas = []
    cattle_counts_per_image = []

    for split in splits:
        for image_path in sorted((image_root / split).iterdir()):
            if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg"}:
                continue
            label_path = label_root / split / f"{image_path.stem}.txt"
            width, height = jpeg_dimensions(image_path)
            dimensions[(width, height)] += 1
            image_sizes.append(image_path.stat().st_size)
            key = source_key(image_path.stem)
            relative = str(image_path.relative_to(data_root))
            source_families[key].append((split, relative))
            match = TRAILING_FRAME.match(key)
            if match:
                sequence_frames[match.group(1)].append((int(match.group(2)), split, relative))

            valid_boxes = []
            present_classes = set()
            for line_number, raw_line in enumerate(label_path.read_text().splitlines(), 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    box = parse_label(line)
                    valid_boxes.append(box)
                    present_classes.add(box[0])
                    objects_by_class[split][box[0]] += 1
                except Exception as exc:
                    reason = str(exc).split(":", 1)[0]
                    invalid_counts[reason] += 1
                    if len(invalid_samples) < 100:
                        invalid_samples.append({
                            "path": str(label_path.relative_to(data_root)),
                            "line": line_number,
                            "value": line,
                            "reason": str(exc),
                        })
            for class_id in present_classes:
                images_by_class[split][class_id] += 1
                source_families_by_class[class_id][key].append((split, relative))

            cattle = [box for box in valid_boxes if box[0] == 1]
            if cattle:
                pixel_widths = [box[3] * width for box in cattle]
                pixel_heights = [box[4] * height for box in cattle]
                pixel_areas = [w * h for w, h in zip(pixel_widths, pixel_heights)]
                cattle_widths.extend(pixel_widths)
                cattle_heights.extend(pixel_heights)
                cattle_areas.extend(pixel_areas)
                cattle_counts_per_image.append(len(cattle))
                records.append({
                    "relative_path": relative,
                    "split": split,
                    "source_key": key,
                    "width": width,
                    "height": height,
                    "cattle_boxes": len(cattle),
                    "smallest_cattle_width": round(min(pixel_widths), 2),
                    "smallest_cattle_height": round(min(pixel_heights), 2),
                    "median_cattle_width": quantiles(pixel_widths)["p50"],
                    "median_cattle_height": quantiles(pixel_heights)["p50"],
                })

    repeated_families = {
        key: members for key, members in source_families.items() if len(members) > 1
    }
    cross_split_families = {
        key: members for key, members in repeated_families.items()
        if len({split for split, _ in members}) > 1
    }

    cattle_source_families = source_families_by_class[1]
    repeated_cattle_families = {
        key: members for key, members in cattle_source_families.items() if len(members) > 1
    }
    cross_split_cattle_families = {
        key: members for key, members in repeated_cattle_families.items()
        if len({split for split, _ in members}) > 1
    }

    adjacent_cross_split = []
    for sequence, frames in sequence_frames.items():
        ordered = sorted(frames)
        for index, (frame, split, relative) in enumerate(ordered):
            for other_frame, other_split, other_relative in ordered[index + 1:]:
                if other_frame - frame > 5:
                    break
                if split != other_split:
                    adjacent_cross_split.append({
                        "sequence": sequence,
                        "frame_a": frame,
                        "split_a": split,
                        "path_a": relative,
                        "frame_b": other_frame,
                        "split_b": other_split,
                        "path_b": other_relative,
                    })
                    if len(adjacent_cross_split) >= 1000:
                        break
            if len(adjacent_cross_split) >= 1000:
                break
        if len(adjacent_cross_split) >= 1000:
            break

    samples = []
    for split in splits:
        split_records = [record for record in records if record["split"] == split]
        samples.extend(stable_sample(split_records, 8, f"random-{split}"))
    samples.extend(sorted(records, key=lambda record: (
        record["smallest_cattle_width"], record["smallest_cattle_height"]
    ))[:12])
    samples.extend(sorted(records, key=lambda record: record["cattle_boxes"], reverse=True)[:12])
    samples.extend(sorted(records, key=lambda record: record["width"] * record["height"], reverse=True)[:12])
    deduplicated_samples = {record["relative_path"]: record for record in samples}

    return {
        "dataset_root": str(root),
        "classes": ["sheep", "cattle", "seal", "camelus", "kiang", "zebra"],
        "images_by_class": {
            split: {str(key): value for key, value in sorted(counts.items())}
            for split, counts in images_by_class.items()
        },
        "objects_by_class": {
            split: {str(key): value for key, value in sorted(counts.items())}
            for split, counts in objects_by_class.items()
        },
        "cattle": {
            "images": len(records),
            "boxes": len(cattle_widths),
            "boxes_per_image": quantiles([float(value) for value in cattle_counts_per_image]),
            "box_width_pixels": quantiles(cattle_widths),
            "box_height_pixels": quantiles(cattle_heights),
            "box_area_pixels": quantiles(cattle_areas),
        },
        "files": {
            "image_bytes": quantiles([float(value) for value in image_sizes]),
            "dimensions": [
                {"width": width, "height": height, "images": count}
                for (width, height), count in dimensions.most_common()
            ],
        },
        "labels": {
            "invalid_lines": sum(invalid_counts.values()),
            "invalid_by_reason": dict(invalid_counts),
            "invalid_samples": invalid_samples,
        },
        "leakage": {
            "source_keys": len(source_families),
            "repeated_source_families": len(repeated_families),
            "cross_split_source_families": len(cross_split_families),
            "cattle_source_keys": len(cattle_source_families),
            "repeated_cattle_source_families": len(repeated_cattle_families),
            "cross_split_cattle_source_families": len(cross_split_cattle_families),
            "sample_cross_split_cattle_source_families": [
                {"source_key": key, "members": members[:20]}
                for key, members in sorted(cross_split_cattle_families.items())[:50]
            ],
            "sample_cross_split_source_families": [
                {"source_key": key, "members": members[:20]}
                for key, members in sorted(cross_split_families.items())[:50]
            ],
            "adjacent_cross_split_frame_pairs_found": len(adjacent_cross_split),
            "adjacent_cross_split_search_capped": len(adjacent_cross_split) >= 1000,
            "sample_adjacent_cross_split_frames": adjacent_cross_split[:50],
        },
        "visual_sample_manifest": list(deduplicated_samples.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = analyze(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
