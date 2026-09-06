#!/usr/bin/env python3
"""Render perceptual-leakage candidate pairs with cattle boxes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = 20_000_000
TILE_WIDTH = 480
IMAGE_HEIGHT = 300
CAPTION_HEIGHT = 55
PAIRS_PER_PAGE = 6


def render(root: Path, relative: str, heading: str) -> Image.Image:
    image_path = root / "WAID" / relative
    split = Path(relative).parts[1]
    label_path = root / "WAID" / "labels" / split / f"{image_path.stem}.txt"
    with Image.open(image_path) as source:
        source.load()
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for line in label_path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "1":
            continue
        _, x, y, width, height = map(float, fields)
        if width <= 0 or height <= 0:
            continue
        draw.rectangle(
            (
                (x - width / 2) * image.width,
                (y - height / 2) * image.height,
                (x + width / 2) * image.width,
                (y + height / 2) * image.height,
            ),
            outline=(255, 25, 25),
            width=max(2, round(max(image.size) / 500)),
        )
    image.thumbnail((TILE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    tile = Image.new("RGB", (TILE_WIDTH, IMAGE_HEIGHT + CAPTION_HEIGHT), "white")
    tile.paste(image, ((TILE_WIDTH - image.width) // 2, 0))
    caption = f"{heading}\n{split}: {Path(relative).name[:62]}"
    ImageDraw.Draw(tile).text((5, IMAGE_HEIGHT + 4), caption, fill="black", font=ImageFont.load_default())
    return tile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    pairs = json.loads(args.report.read_text())["closest_cross_split_pairs"][:24]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(pairs), PAIRS_PER_PAGE):
        page_pairs = pairs[start:start + PAIRS_PER_PAGE]
        sheet = Image.new(
            "RGB",
            (TILE_WIDTH * 2, (IMAGE_HEIGHT + CAPTION_HEIGHT) * len(page_pairs)),
            "white",
        )
        for row, pair in enumerate(page_pairs):
            metric = f"pair {start + row + 1} | score={pair['score']} d={pair['dhash_distance']} a={pair['ahash_distance']}"
            sheet.paste(render(args.root, pair["left"], metric), (0, row * (IMAGE_HEIGHT + CAPTION_HEIGHT)))
            sheet.paste(render(args.root, pair["right"], metric), (TILE_WIDTH, row * (IMAGE_HEIGHT + CAPTION_HEIGHT)))
        sheet.save(args.output_dir / f"pairs-{start // PAIRS_PER_PAGE + 1}.jpg", quality=90)


if __name__ == "__main__":
    main()
