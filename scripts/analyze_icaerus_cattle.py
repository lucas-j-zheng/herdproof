#!/usr/bin/env python3
"""Audit ICAERUS annotated grazing-cow v2 without executing dataset code."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

IMAGE_MARKERS = {"JPGImages"}
YOLO_MARKERS = {"YOLO_1.1", "YOLO1.1"}
VOC_MARKERS = {"Pascal_VOC1.1"}


def identity(root: Path, path: Path) -> tuple[str, str]:
    parts = path.relative_to(root).parts
    dataset_index = parts.index("Cattle_drone_images")
    farm = parts[dataset_index + 1]
    return farm, path.stem


def image_flight(root: Path, path: Path) -> str:
    parts = path.relative_to(root).parts
    return next((part for part in parts if part.startswith("DJI_")), "<no-flight>")


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] if low == high else ordered[low] * (high - position) + ordered[high] * (position - low)


def file_digest(path: Path) -> str:
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

    all_files = [path for path in root.rglob("*") if path.is_file() and path.name != ".safe-extraction.json"]
    images = sorted(path for path in all_files if path.suffix.lower() in {".jpg", ".jpeg"} and IMAGE_MARKERS.intersection(path.parts))
    image_stems = {path.stem for path in images}
    yolo_paths = sorted(path for path in all_files if path.suffix.lower() == ".txt" and path.stem in image_stems)
    xml_paths = sorted(path for path in all_files if path.suffix.lower() == ".xml" and VOC_MARKERS.intersection(path.parts))
    names_paths = sorted(path for path in all_files if path.suffix.lower() == ".names" and YOLO_MARKERS.intersection(path.parts))
    class_definitions = Counter(tuple(line.strip() for line in path.read_text().splitlines() if line.strip()) for path in names_paths)

    image_map: dict[tuple[str, str], list[Path]] = defaultdict(list)
    yolo_map: dict[tuple[str, str], list[Path]] = defaultdict(list)
    xml_map: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for path in images: image_map[identity(root, path)].append(path)
    for path in yolo_paths: yolo_map[identity(root, path)].append(path)
    for path in xml_paths: xml_map[identity(root, path)].append(path)

    invalid = []
    image_dimensions = Counter()
    image_formats = Counter()
    image_sizes: dict[tuple[str, str], tuple[int, int]] = {}
    size_groups: dict[int, list[Path]] = defaultdict(list)
    for key, paths in image_map.items():
        if len(paths) != 1:
            invalid.append({"key": key, "reason": "duplicate image identity", "paths": [str(x) for x in paths]})
            continue
        path = paths[0]
        try:
            with Image.open(path) as image:
                width, height = image.size
                image_dimensions[f"{width}x{height}"] += 1
                image_formats[str(image.format)] += 1
                image.verify()
            image_sizes[key] = (width, height)
            size_groups[path.stat().st_size].append(path)
        except Exception as exc:
            invalid.append({"path": str(path.relative_to(root)), "reason": f"image decode: {exc}"})

    yolo_boxes: dict[tuple[str, str], list[tuple[int, float, float, float, float]]] = {}
    class_ids = Counter()
    for key, paths in yolo_map.items():
        if len(paths) != 1:
            invalid.append({"key": key, "reason": "duplicate YOLO identity", "paths": [str(x) for x in paths]})
            continue
        boxes = []
        for line_number, line in enumerate(paths[0].read_text(errors="replace").splitlines(), 1):
            fields = line.split()
            try:
                if len(fields) != 5: raise ValueError("expected five fields")
                class_id = int(fields[0])
                x, y, width, height = map(float, fields[1:])
                if not all(math.isfinite(value) for value in (x, y, width, height)):
                    raise ValueError("non-finite coordinate")
                if width <= 0 or height <= 0: raise ValueError("non-positive dimensions")
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
                    raise ValueError("coordinate outside normalized range")
                if x - width / 2 < -1e-6 or y - height / 2 < -1e-6 or x + width / 2 > 1 + 1e-6 or y + height / 2 > 1 + 1e-6:
                    raise ValueError("box extends outside image")
                boxes.append((class_id, x, y, width, height))
                class_ids[class_id] += 1
            except ValueError as exc:
                invalid.append({"path": str(paths[0].relative_to(root)), "line": line_number, "value": line, "reason": str(exc)})
        yolo_boxes[key] = boxes

    voc_boxes: dict[tuple[str, str], list[tuple[str, float, float, float, float]]] = {}
    object_names = Counter()
    unexpected_voc_objects = []
    for key, paths in xml_map.items():
        if len(paths) != 1:
            invalid.append({"key": key, "reason": "duplicate VOC identity", "paths": [str(x) for x in paths]})
            continue
        boxes = []
        try:
            tree = ET.parse(paths[0])
            for obj in tree.findall(".//object"):
                name = (obj.findtext("name") or "").strip()
                box = obj.find("bndbox")
                if box is None: raise ValueError("object missing bndbox")
                xmin = float(box.findtext("xmin", "nan")); ymin = float(box.findtext("ymin", "nan"))
                xmax = float(box.findtext("xmax", "nan")); ymax = float(box.findtext("ymax", "nan"))
                if not all(math.isfinite(value) for value in (xmin, ymin, xmax, ymax)):
                    raise ValueError("non-finite VOC coordinate")
                if xmax <= xmin or ymax <= ymin: raise ValueError("non-positive VOC dimensions")
                boxes.append((name, xmin, ymin, xmax, ymax)); object_names[name] += 1
                if name not in {"cow", "calf"}:
                    unexpected_voc_objects.append({
                        "path": str(paths[0].relative_to(root)), "name": name,
                        "box": [xmin, ymin, xmax, ymax],
                    })
        except Exception as exc:
            invalid.append({"path": str(paths[0].relative_to(root)), "reason": f"VOC parse: {exc}"})
        voc_boxes[key] = boxes

    missing_yolo = sorted(key for key in image_map if key not in yolo_map)
    missing_voc = sorted(key for key in image_map if key not in xml_map)
    orphan_yolo = sorted(key for key in yolo_map if key not in image_map)
    orphan_voc = sorted(key for key in xml_map if key not in image_map)
    cross_format_mismatches = []
    widths, heights, areas, counts = [], [], [], []
    records = []
    flight_stats: dict[str, Counter] = defaultdict(Counter)
    for key, image_paths in sorted(image_map.items()):
        width, height = image_sizes.get(key, (0, 0))
        ys = yolo_boxes.get(key, [])
        vs = voc_boxes.get(key, [])
        if key in xml_map and len(ys) != len(vs):
            cross_format_mismatches.append({"key": key, "yolo": len(ys), "voc": len(vs), "reason": "count"})
        elif key in xml_map and width and height:
            y_pixels = sorted((x * width, y * height, w * width, h * height) for _, x, y, w, h in ys)
            v_pixels = sorted(((xmin + xmax) / 2, (ymin + ymax) / 2, xmax - xmin, ymax - ymin) for _, xmin, ymin, xmax, ymax in vs)
            max_delta = max((max(abs(a - b) for a, b in zip(left, right)) for left, right in zip(y_pixels, v_pixels)), default=0)
            if max_delta > 3.0:
                cross_format_mismatches.append({"key": key, "yolo": len(ys), "voc": len(vs), "max_pixel_delta": max_delta, "reason": "coordinates"})
        for _, _, _, box_width, box_height in ys:
            pixel_width, pixel_height = box_width * width, box_height * height
            widths.append(pixel_width); heights.append(pixel_height); areas.append(pixel_width * pixel_height)
        counts.append(len(ys))
        farm, _ = key
        flight = image_flight(root, image_paths[0])
        flight_key = f"{farm}/{flight}"
        flight_stats[flight_key]["images"] += 1
        flight_stats[flight_key]["boxes"] += len(ys)
        records.append({
            "image": str(image_paths[0].relative_to(root)),
            "yolo": str(yolo_map[key][0].relative_to(root)) if key in yolo_map else None,
            "boxes": len(ys), "farm": farm, "flight": flight,
            "minimum_box_area": min((w * h * width * height for _, _, _, w, h in ys), default=None),
        })

    exact_duplicates = []
    for same_size in size_groups.values():
        if len(same_size) < 2: continue
        digests: dict[str, list[str]] = defaultdict(list)
        for path in same_size: digests[file_digest(path)].append(str(path.relative_to(root)))
        exact_duplicates.extend(members for members in digests.values() if len(members) > 1)

    rng = random.Random(11048412)
    with_boxes = [record for record in records if record["boxes"] > 0]
    samples = {
        "random": rng.sample(records, min(12, len(records))),
        "densest": sorted(records, key=lambda item: (item["boxes"], item["image"]), reverse=True)[:12],
        "smallest_boxes": sorted(with_boxes, key=lambda item: (item["minimum_box_area"], item["image"]))[:12],
        "negative": rng.sample(
            [record for record in records if record["boxes"] == 0],
            min(12, sum(record["boxes"] == 0 for record in records)),
        ),
    }
    report = {
        "files": len(all_files), "images": len(images), "yolo_labels": len(yolo_paths), "voc_labels": len(xml_paths),
        "image_formats": dict(sorted(image_formats.items())), "image_dimensions": dict(sorted(image_dimensions.items())),
        "class_definition_files": len(names_paths),
        "class_definitions": {"|".join(names): count for names, count in sorted(class_definitions.items())},
        "yolo_class_ids": dict(sorted(class_ids.items())), "voc_object_names": dict(sorted(object_names.items())),
        "valid_yolo_boxes": sum(counts), "images_with_boxes": sum(count > 0 for count in counts),
        "negative_images": sum(count == 0 for count in counts),
        "boxes_per_image": {"minimum": min(counts), "median": statistics.median(counts), "p90": percentile(counts, .9), "maximum": max(counts), "mean": statistics.mean(counts)},
        "box_pixels": {
            "width_p10": percentile(widths, .1), "width_median": percentile(widths, .5),
            "height_p10": percentile(heights, .1), "height_median": percentile(heights, .5),
            "area_minimum": min(areas) if areas else None,
        },
        "farms": sorted({key[0] for key in image_map}), "flights": len(flight_stats),
        "flight_stats": {key: dict(value) for key, value in sorted(flight_stats.items())},
        "missing_yolo": missing_yolo, "missing_voc": missing_voc,
        "orphan_yolo": orphan_yolo, "orphan_voc": orphan_voc,
        "invalid": invalid, "unexpected_voc_objects": unexpected_voc_objects,
        "cross_format_mismatches": cross_format_mismatches,
        "exact_duplicate_image_groups": exact_duplicates,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.sample_manifest.write_text(json.dumps(samples, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print("sample categories", {key: len(value) for key, value in samples.items()})
    if any((missing_yolo, missing_voc, orphan_yolo, orphan_voc, invalid, cross_format_mismatches, exact_duplicates)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
