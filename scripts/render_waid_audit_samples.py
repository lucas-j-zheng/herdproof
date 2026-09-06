#!/usr/bin/env python3
"""Render bounded WAID cattle-label samples on a compute node for human audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = 20_000_000
THUMB = (480, 320)
GRID = (3, 3)


def stable_rank(record: dict) -> bytes:
    return hashlib.sha256(record["relative_path"].encode()).digest()


def choose(records: list[dict]) -> dict[str, list[dict]]:
    return {
        "random": sorted(records, key=stable_rank)[:18],
        "smallest": sorted(
            records,
            key=lambda item: (item["smallest_cattle_width"], item["smallest_cattle_height"]),
        )[:18],
        "densest": sorted(records, key=lambda item: item["cattle_boxes"], reverse=True)[:18],
        "largest_resolution": sorted(
            records,
            key=lambda item: item["width"] * item["height"],
            reverse=True,
        )[:18],
    }


def label_path_for(data_root: Path, record: dict) -> Path:
    image_path = Path(record["relative_path"])
    return data_root / "labels" / record["split"] / f"{image_path.stem}.txt"


def render_tile(dataset_root: Path, record: dict) -> Image.Image:
    data_root = dataset_root / "WAID"
    image_path = (data_root / record["relative_path"]).resolve()
    if data_root.resolve() not in image_path.parents:
        raise ValueError("sample path escapes dataset root")
    if image_path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("sample exceeds image-size limit")

    with Image.open(image_path) as source:
        if source.format != "JPEG":
            raise ValueError(f"unexpected format {source.format!r}")
        source.load()
        image = source.convert("RGB")

    draw = ImageDraw.Draw(image)
    label_path = label_path_for(data_root, record)
    for line in label_path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 5:
            continue
        class_id = int(float(fields[0]))
        x, y, width, height = map(float, fields[1:])
        if width <= 0 or height <= 0:
            continue
        left = (x - width / 2) * image.width
        top = (y - height / 2) * image.height
        right = (x + width / 2) * image.width
        bottom = (y + height / 2) * image.height
        color = (255, 40, 40) if class_id == 1 else (120, 120, 120)
        line_width = max(2, round(max(image.width, image.height) / 500))
        draw.rectangle((left, top, right, bottom), outline=color, width=line_width)

    image.thumbnail((THUMB[0], THUMB[1] - 45), Image.Resampling.LANCZOS)
    tile = Image.new("RGB", THUMB, "white")
    x_offset = (THUMB[0] - image.width) // 2
    tile.paste(image, (x_offset, 0))
    caption = (
        f"{record['split']} | {record['width']}x{record['height']} | "
        f"cattle={record['cattle_boxes']}\n{Path(record['relative_path']).name[:65]}"
    )
    ImageDraw.Draw(tile).text((5, THUMB[1] - 42), caption, fill="black", font=ImageFont.load_default())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    audit = json.loads(args.audit_json.read_text())
    records = audit["visual_sample_manifest"]
    categories = choose(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rendered_manifest = {}

    for category, selected in categories.items():
        rendered_manifest[category] = [record["relative_path"] for record in selected]
        for page_start in range(0, len(selected), GRID[0] * GRID[1]):
            page_records = selected[page_start:page_start + GRID[0] * GRID[1]]
            sheet = Image.new("RGB", (THUMB[0] * GRID[0], THUMB[1] * GRID[1]), "white")
            for index, record in enumerate(page_records):
                tile = render_tile(args.dataset_root.resolve(), record)
                x = (index % GRID[0]) * THUMB[0]
                y = (index // GRID[0]) * THUMB[1]
                sheet.paste(tile, (x, y))
            page_number = page_start // (GRID[0] * GRID[1]) + 1
            sheet.save(args.output_dir / f"{category}-{page_number}.jpg", quality=88)

    (args.output_dir / "manifest.json").write_text(
        json.dumps(rendered_manifest, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
