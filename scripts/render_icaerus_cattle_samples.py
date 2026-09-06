#!/usr/bin/env python3
"""Render ICAERUS grazing-cow audit contact sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_WIDTH = 700
IMAGE_HEIGHT = 525
CAPTION_HEIGHT = 55
PER_PAGE = 4


def render(root: Path, record: dict) -> Image.Image:
    image_path = root / record["image"]
    with Image.open(image_path) as source:
        source.load()
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    label_path = root / record["yolo"] if record.get("yolo") else None
    if label_path:
        for line in label_path.read_text().splitlines():
            fields = line.split()
            if len(fields) != 5: continue
            _, x, y, width, height = map(float, fields)
            draw.rectangle((
                (x - width / 2) * image.width, (y - height / 2) * image.height,
                (x + width / 2) * image.width, (y + height / 2) * image.height,
            ), outline=(255, 25, 25), width=max(3, round(max(image.size) / 1200)))
    image.thumbnail((TILE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    tile = Image.new("RGB", (TILE_WIDTH, IMAGE_HEIGHT + CAPTION_HEIGHT), "white")
    tile.paste(image, ((TILE_WIDTH - image.width) // 2, 0))
    caption = f"boxes={record['boxes']} farm={record['farm']} flight={record['flight']}\n{Path(record['image']).name[:95]}"
    ImageDraw.Draw(tile).text((5, IMAGE_HEIGHT + 4), caption, fill="black", font=ImageFont.load_default())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for category, records in manifest.items():
        for start in range(0, len(records), PER_PAGE):
            page = records[start:start + PER_PAGE]
            sheet = Image.new("RGB", (TILE_WIDTH * 2, (IMAGE_HEIGHT + CAPTION_HEIGHT) * 2), "white")
            for index, record in enumerate(page):
                sheet.paste(render(args.root, record), ((index % 2) * TILE_WIDTH, (index // 2) * (IMAGE_HEIGHT + CAPTION_HEIGHT)))
            sheet.save(args.output / f"{category}-{start // PER_PAGE + 1}.jpg", quality=90)


if __name__ == "__main__":
    main()
