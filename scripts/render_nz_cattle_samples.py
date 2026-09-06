#!/usr/bin/env python3
"""Render New Zealand cattle point annotations as contact sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE = 520
CAPTION = 45
PER_PAGE = 4


def render(root: Path, record: dict) -> Image.Image:
    image_path = root / "dataset" / record["image"]
    label_path = root / "dataset" / record["label"]
    with Image.open(image_path) as source:
        source.load()
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    frequencies = {}
    for line in label_path.read_text().splitlines():
        x, y = (int(value) for value in line.split(","))
        frequencies[(x, y)] = frequencies.get((x, y), 0) + 1
    for (x, y), count in frequencies.items():
        color = (255, 0, 255) if count > 1 else (255, 20, 20)
        radius = 5 if count > 1 else 3
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
    tile = Image.new("RGB", (TILE, TILE + CAPTION), "white")
    tile.paste(image, ((TILE - image.width) // 2, 0))
    caption = f"points={record['points']} source={record['source_group']}\n{Path(record['image']).name[:80]}"
    ImageDraw.Draw(tile).text((5, TILE + 4), caption, fill="black", font=ImageFont.load_default())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for category, records in manifest.items():
        for start in range(0, len(records), PER_PAGE):
            page = records[start:start + PER_PAGE]
            sheet = Image.new("RGB", (TILE * 2, (TILE + CAPTION) * 2), "white")
            for index, record in enumerate(page):
                sheet.paste(render(args.root, record), ((index % 2) * TILE, (index // 2) * (TILE + CAPTION)))
            sheet.save(args.output_dir / f"{category}-{start // PER_PAGE + 1}.jpg", quality=92)


if __name__ == "__main__":
    main()
