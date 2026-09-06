#!/usr/bin/env python3
"""Render selected Uruguay Cattle MOT ground-truth frames."""

from __future__ import annotations

import argparse
import csv
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FRAMES = (0, 76, 100, 160, 240, 320, 400, 478)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    annotations = defaultdict(list)
    with args.ground_truth.open(newline="") as source:
        for row in csv.reader(source):
            values = [value.strip() for value in row]
            frame, track_id, x, y, width, height = map(int, values[:6])
            annotations[frame].append((track_id, x, y, width, height))

    rendered = []
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        for frame in FRAMES:
            image_path = temporary / f"{frame:04d}.png"
            subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(args.video),
                "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", str(image_path),
            ], check=True)
            with Image.open(image_path) as source:
                source.load()
                image = source.convert("RGB")
            draw = ImageDraw.Draw(image)
            for track_id, x, y, width, height in annotations[frame]:
                draw.rectangle((x, y, x + width, y + height), outline=(255, 25, 25), width=5)
                draw.text((max(0, x), max(0, y - 14)), f"ID {track_id}", fill=(255, 255, 0), font=ImageFont.load_default())
            image.thumbnail((640, 360), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (660, 395), "white")
            tile.paste(image, ((660 - image.width) // 2, 0))
            ImageDraw.Draw(tile).text((8, 365), f"frame {frame}; boxes {len(annotations[frame])}", fill="black")
            rendered.append(tile)

    sheet = Image.new("RGB", (1320, 1580), "white")
    for index, tile in enumerate(rendered):
        sheet.paste(tile, ((index % 2) * 660, (index // 2) * 395))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)


if __name__ == "__main__":
    main()
