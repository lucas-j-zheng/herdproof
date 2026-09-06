#!/usr/bin/env python3
"""Render a small, reproducibly selected error audit with no location metadata."""
from __future__ import annotations
import json
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((BASE / "validation/data/manifest.json").read_text())
    p=argparse.ArgumentParser()
    p.add_argument("--run",type=Path,default=BASE / "validation/runs/baseline")
    args=p.parse_args()
    report = json.loads((args.run / "report.json").read_text())
    mode = report["selection"]["selected_mode"]
    rows = report["results"][mode]["images"]
    records = {r["id"]:r for r in manifest["records"]}
    # Largest failure plus a range of positive/negative scenes, selected transparently.
    selected = []
    for pool in (sorted(rows,key=lambda r:(-r["correction_operations"],r["id"])),
                 sorted((r for r in rows if r["truth"]),key=lambda r:(r["truth"],r["id"])),
                 sorted((r for r in rows if not r["truth"]),key=lambda r:(-r["fp"],r["id"]))):
        added = 0
        for r in pool:
            if r["id"] not in {x["id"] for x in selected}:
                selected.append(r)
                added += 1
            if added == 3: break
    target = BASE / "validation/evidence" / args.run.name
    target.mkdir(parents=True,exist_ok=True)
    panels = []
    for r in selected:
        with Image.open(BASE / "validation/data" / records[r["id"]]["image"]) as source:
            photo = source.convert("RGB")
        photo.thumbnail((800,600))
        w,h = photo.size
        panel = Image.new("RGB",(800,654),"#f4f6ef")
        panel.paste(photo,(0,54))
        draw = ImageDraw.Draw(panel)
        draw.text((14,10),f"{r['id']}  Labels {r['truth']} | Predictions {r['predicted']} | FP {r['fp']} | FN {r['fn']}",fill="#17352a")
        draw.text((14,30),"GREEN = publisher annotation; MAGENTA = model proposal",fill="#17352a")
        for color,boxes in (("#00ff72",records[r["id"]]["boxes"]),("#ff36de",r["predictions"])):
            for b in boxes: draw.rectangle((b[0]*w,b[1]*h+54,b[2]*w,b[3]*h+54),outline=color,width=2)
        panel.save(target / f"{r['id']}.jpg",quality=92)
        panels.append(panel)
    sheet = Image.new("RGB",(1600,654*((len(panels)+1)//2)),"white")
    for i,panel in enumerate(panels): sheet.paste(panel,((i%2)*800,(i//2)*654))
    sheet.save(target / "audit-contact-sheet.jpg",quality=90)
    (target / "selection.json").write_text(json.dumps({"method":"Three largest correction failures, three additional sparse positives, three additional negatives", "image_ids":[r["id"] for r in selected],"attribution":manifest["attribution"]},indent=2)+"\n")
    print(f"Rendered {len(selected)} audit images")


if __name__ == "__main__": main()
