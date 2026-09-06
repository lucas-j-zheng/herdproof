#!/usr/bin/env python3
"""Find likely near-duplicate cattle images across WAID's published splits."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
from collections import Counter
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = 20_000_000
RESAMPLING = Image.Resampling.LANCZOS
TRANSFORMS = (
    None,
    Image.Transpose.FLIP_LEFT_RIGHT,
    Image.Transpose.FLIP_TOP_BOTTOM,
    Image.Transpose.ROTATE_180,
)


def has_cattle(label_path: Path) -> bool:
    for line in label_path.read_text().splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == "1":
            return True
    return False


def bits_from_comparisons(values: list[int], width: int, height: int) -> int:
    result = 0
    for y in range(height):
        offset = y * (width + 1)
        for x in range(width):
            result = (result << 1) | (values[offset + x] > values[offset + x + 1])
    return result


def bits_from_average(values: list[int]) -> int:
    average = sum(values) / len(values)
    result = 0
    for value in values:
        result = (result << 1) | (value >= average)
    return result


def fingerprints(path: Path) -> tuple[tuple[int, ...], tuple[int, ...], tuple[str, ...]]:
    with Image.open(path) as source:
        if source.format != "JPEG":
            raise ValueError(f"unexpected image format {source.format!r}")
        source.load()
        gray = source.convert("L")

    dhashes = []
    ahashes = []
    pixel_hashes = []
    for transform in TRANSFORMS:
        candidate = gray if transform is None else gray.transpose(transform)
        dhash_image = candidate.resize((17, 16), RESAMPLING)
        ahash_image = candidate.resize((16, 16), RESAMPLING)
        dhash_values = list(dhash_image.getdata())
        ahash_values = list(ahash_image.getdata())
        dhashes.append(bits_from_comparisons(dhash_values, 16, 16))
        ahashes.append(bits_from_average(ahash_values))
        pixel_hashes.append(hashlib.sha256(bytes(ahash_values)).hexdigest())
    return tuple(dhashes), tuple(ahashes), tuple(pixel_hashes)


def min_distance(first: tuple[int, ...], second: tuple[int, ...]) -> int:
    return min((left ^ right).bit_count() for left in first for right in second)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data_root = args.dataset_root.resolve() / "WAID"
    records = []
    decode_errors = []
    for split_dir in sorted((data_root / "images").iterdir()):
        if not split_dir.is_dir():
            continue
        split = split_dir.name
        for image_path in sorted(split_dir.glob("*.jpg")):
            label_path = data_root / "labels" / split / f"{image_path.stem}.txt"
            if not has_cattle(label_path):
                continue
            try:
                dhashes, ahashes, pixel_hashes = fingerprints(image_path)
                records.append({
                    "split": split,
                    "path": str(image_path.relative_to(data_root)),
                    "dhash": dhashes,
                    "ahash": ahashes,
                    "pixel_hash": pixel_hashes,
                })
            except Exception as exc:
                decode_errors.append({"path": str(image_path), "error": str(exc)})

    by_split = {
        split: [record for record in records if record["split"] == split]
        for split in sorted({record["split"] for record in records})
    }
    thresholds = (4, 8, 12, 16, 24, 32)
    distance_counts = Counter()
    exact_resized_pairs = 0
    compared_pairs = 0
    closest: list[tuple[int, int, int, str, str]] = []
    keep = 250

    split_names = sorted(by_split)
    for left_index, left_split in enumerate(split_names):
        for right_split in split_names[left_index + 1:]:
            for left in by_split[left_split]:
                for right in by_split[right_split]:
                    compared_pairs += 1
                    dhash_distance = min_distance(left["dhash"], right["dhash"])
                    ahash_distance = min_distance(left["ahash"], right["ahash"])
                    score = dhash_distance + ahash_distance
                    for threshold in thresholds:
                        if dhash_distance <= threshold and ahash_distance <= threshold:
                            distance_counts[threshold] += 1
                    if set(left["pixel_hash"]) & set(right["pixel_hash"]):
                        exact_resized_pairs += 1
                    item = (-score, -dhash_distance, -ahash_distance, left["path"], right["path"])
                    if len(closest) < keep:
                        heapq.heappush(closest, item)
                    elif item > closest[0]:
                        heapq.heapreplace(closest, item)

    closest_pairs = []
    for negative_score, negative_dhash, negative_ahash, left, right in sorted(closest, reverse=True):
        closest_pairs.append({
            "score": -negative_score,
            "dhash_distance": -negative_dhash,
            "ahash_distance": -negative_ahash,
            "left": left,
            "right": right,
        })

    result = {
        "pillow_version": Image.__version__,
        "cattle_images": len(records),
        "cattle_images_by_split": {split: len(items) for split, items in by_split.items()},
        "decode_errors": decode_errors,
        "cross_split_pairs_compared": compared_pairs,
        "exact_resized_pixel_pairs": exact_resized_pairs,
        "pairs_with_both_hash_distances_at_most": {
            str(threshold): distance_counts[threshold] for threshold in thresholds
        },
        "closest_cross_split_pairs": closest_pairs,
        "warning": "Perceptual hashes are a screening tool; manually inspect candidate pairs.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "closest_cross_split_pairs"}, indent=2, sort_keys=True))
    print("Closest 20 pairs:")
    print(json.dumps(closest_pairs[:20], indent=2))


if __name__ == "__main__":
    main()
