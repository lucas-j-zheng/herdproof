from __future__ import annotations

import argparse
import hashlib
import math
import random
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from training.common import PACKAGE, digest, load_config, require_compute_job, write_json


def starts(length, size=1024, overlap=.2):
    if length <= size:
        return [0]
    step = max(1, int(size * (1 - overlap)))
    return sorted(set(range(0, length - size + 1, step)) | {length - size})


def parse_labels(path):
    boxes = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5 or parts[0] != "0":
            raise ValueError("Expected class-0 YOLO boxes")
        x, y, w, h = map(float, parts[1:])
        if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
            raise ValueError("Non-finite or non-positive box")
        box = [x - w / 2, y - h / 2, x + w / 2, y + h / 2]
        if min(box) < -1e-6 or max(box) > 1 + 1e-6:
            raise ValueError("Box outside image")
        boxes.append([min(1., max(0., v)) for v in box])
    if len({tuple(b) for b in boxes}) != len(boxes):
        raise ValueError("Duplicate annotation")
    return boxes


def identity(path):
    parts = path.parts
    i = parts.index("Cattle_drone_images")
    return parts[i + 1], path.stem


def catalog(source):
    source = source.resolve()
    maps = [defaultdict(list) for _ in range(3)]
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "Cattle_drone_images" not in path.parts:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Unsafe source path: {path}")
        if "JPGImages" in path.parts and path.suffix.lower() in {".jpg", ".jpeg"}:
            maps[0][identity(path)].append(path)
        elif {"YOLO_1.1", "YOLO1.1"}.intersection(path.parts) and path.suffix.lower() == ".txt":
            maps[1][identity(path)].append(path)
        elif "Pascal_VOC1.1" in path.parts and path.suffix.lower() == ".xml":
            maps[2][identity(path)].append(path)
    images, labels, xmls = maps
    rows, quarantine = [], []
    for key, paths in sorted(images.items()):
        if len(paths) != 1:
            raise ValueError(f"Ambiguous image identity: {key}")
        image_path = paths[0]
        relative = str(image_path.relative_to(source))
        farm = key[0]
        flight = next((p for p in image_path.parent.parts if p.startswith("DJI_")), None)
        day_match = re.search(r"DJI_(20\d{6})", image_path.stem)
        if not flight or not day_match:
            raise ValueError(f"Cannot establish capture group: {relative}")
        row = {"id": hashlib.sha256(relative.encode()).hexdigest()[:16], "image": relative,
               "farm": farm, "flight": f"{farm}/{flight}", "day": f"{farm}/{day_match[1]}",
               "image_sha256": digest(image_path), "eligible": False, "boxes": []}
        rows.append(row)  # Keep all images in capture-group connectivity, even excluded ones.
        try:
            with Image.open(image_path) as image:
                row["width"], row["height"] = image.size
                if image.getexif().get(274, 1) not in (None, 1):
                    raise ValueError("Nontrivial EXIF orientation; annotation coordinates need review")
                image.load()
            if len(labels[key]) != 1:
                raise ValueError("Missing or ambiguous YOLO label")
            label = labels[key][0]
            row.update(label=str(label.relative_to(source)), label_sha256=digest(label))
            boxes = parse_labels(label)
            if len(xmls[key]) > 1:
                raise ValueError("Ambiguous VOC label")
            if xmls[key]:
                objects = ET.parse(xmls[key][0]).findall(".//object")
                if any((obj.findtext("name") or "").strip() not in {"cow", "calf"} for obj in objects):
                    raise ValueError("VOC contains unknown/non-cattle objects")
                if len(objects) != len(boxes):
                    raise ValueError("YOLO/VOC counts disagree")
            if not boxes:
                raise ValueError("Empty label is not a verified negative")
            row.update(boxes=boxes, eligible=True, annotation_status="provisional")
        except (ValueError, OSError, ET.ParseError) as exc:
            quarantine.append({"id": row["id"], "image": relative, "reason": str(exc)})
    return rows, quarantine


def assign_groups(rows):
    parents = list(range(len(rows)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    seen = {}
    for i, row in enumerate(rows):
        for token in ("flight:" + row["flight"], "day:" + row["day"], "sha:" + row["image_sha256"]):
            if token in seen:
                parents[find(i)] = find(seen[token])
            else:
                seen[token] = i
    components = defaultdict(list)
    for i, row in enumerate(rows):
        components[find(i)].append(row)
    for component in components.values():
        # Stable across ordering; no dependence on predictions or split performance.
        group = hashlib.sha256("\n".join(sorted(r["image"] for r in component)).encode()).hexdigest()[:16]
        for row in component:
            row["group"] = group


def assign_splits(rows, config):
    groups = sorted({r["group"] for r in rows if r["eligible"]})
    if len(groups) < config["minimum_groups"]:
        raise ValueError("Too few independent capture groups")
    stats = {g: (sum(r["eligible"] and r["group"] == g for r in rows),
                 sum(len(r["boxes"]) for r in rows if r["eligible"] and r["group"] == g)) for g in groups}
    total = [sum(v[i] for v in stats.values()) for i in (0, 1)]
    nval = max(1, round(len(groups) * config["split_fractions"][1]))
    ntest = max(1, round(len(groups) * config["split_fractions"][2]))
    rng = random.Random(config["seed"])
    best = None
    # Balance eligible source/annotation counts, using metadata only. Group boundaries are absolute.
    for _ in range(5000):
        order = groups.copy()
        rng.shuffle(order)
        split = {g: "val" if i < nval else "test" if i < nval + ntest else "train" for i, g in enumerate(order)}
        score = sum((sum(stats[g][j] for g in groups if split[g] == s) / total[j] - fraction) ** 2
                    for s, fraction in zip(("train", "val", "test"), config["split_fractions"]) for j in (0, 1))
        farms = {r["farm"] for r in rows if r["eligible"]}
        train_farms = {r["farm"] for r in rows if r["eligible"] and split[r["group"]] == "train"}
        score += len(farms - train_farms)
        candidate = (score, tuple(sorted(split.items())))
        if best is None or candidate < best:
            best = candidate
    mapping = dict(best[1])
    for row in rows:
        row["split"] = mapping.get(row["group"], "excluded")
    return mapping


def clipped_labels(boxes, width, height, x, y, config):
    size = config["tile_size"]
    clipped, indices = [], []
    for index, (a, b, c, d) in enumerate(boxes):
        left, top, right, bottom = a * width, b * height, c * width, d * height
        l, t, r, b = max(x, left), max(y, top), min(x + size, right), min(y + size, bottom)
        if r <= l or b <= t:
            continue
        fraction = ((r - l) * (b - t)) / ((right - left) * (bottom - top))
        if fraction < config["minimum_visible_fraction"] or min(r - l, b - t) < config["minimum_visible_side"]:
            # Skip the whole crop: dropping only this label would create a false background target.
            return None, []
        clipped.append([((l + r) / 2 - x) / size, ((t + b) / 2 - y) / size, (r - l) / size, (b - t) / size])
        indices.append(index)
    return clipped, indices


def native_crop(image, x, y, size):
    # PIL crop pads beyond a small source image without resizing any source pixels.
    return image.crop((x, y, x + size, y + size))


def tile_specs(boxes, width, height, config):
    size = config["tile_size"]
    selected, tested, covered = [], {}, set()

    def candidate(x, y):
        key = (int(max(0, min(max(0, width - size), x))), int(max(0, min(max(0, height - size), y))))
        if key not in tested:
            clipped, ids = clipped_labels(boxes, width, height, *key, config)
            tested[key] = (*key, clipped, ids)
        return tested[key]

    for y in starts(height, size, config["tile_overlap"]):
        for x in starts(width, size, config["tile_overlap"]):
            item = candidate(x, y)
            if item[2]:
                selected.append(item)
                covered.update(item[3])
    # Rescue cows lost to a bad grid boundary with extra native-pixel crops, never by resizing.
    # Use only source labels; validation/test inference still scans the fixed grid without labels.
    for index, (a, b, c, d) in enumerate(boxes):
        if index in covered:
            continue
        center_x, center_y = round((a + c) * width / 2 - size / 2), round((b + d) * height / 2 - size / 2)
        options = [candidate(center_x + dx, center_y + dy)
                   for dx in (-256, -128, 0, 128, 256) for dy in (-256, -128, 0, 128, 256)]
        valid = [item for item in options if item[2] and index in item[3]]
        if valid:
            best = min(valid, key=lambda item: (-len(set(item[3]) - covered), abs(item[0] - center_x) + abs(item[1] - center_y), item[:2]))
            selected.append(best)
            covered.update(best[3])
    return selected, covered, sum(item[2] is None for item in tested.values())


def create_tiles(source, destination, rows, config):
    tiles, coverage = [], []
    size = config["tile_size"]
    for split in ("train", "val"):
        (destination / "images" / split).mkdir(parents=True)
        (destination / "labels" / split).mkdir(parents=True)
    for row in rows:
        if not row["eligible"] or row["split"] not in {"train", "val"}:
            continue
        path = source / row["image"]
        if digest(path) != row["image_sha256"]:
            raise ValueError("Source image changed during preparation")
        with Image.open(path) as original:
            image = original.convert("RGB")
        width, height = image.size
        specs, covered, skipped = tile_specs(row["boxes"], width, height, config)
        for x, y, boxes, indices in specs:
            stem = f"{row['id']}_{x}_{y}"
            image_rel = f"images/{row['split']}/{stem}.png"
            label_rel = f"labels/{row['split']}/{stem}.txt"
            native_crop(image, x, y, size).save(destination / image_rel)
            (destination / label_rel).write_text("".join("0 " + " ".join(f"{v:.9f}" for v in b) + "\n" for b in boxes))
            tiles.append({"source_id": row["id"], "group": row["group"], "split": row["split"],
                          "image": image_rel, "label": label_rel, "x": x, "y": y, "objects": len(boxes),
                          "image_sha256": digest(destination / image_rel), "label_sha256": digest(destination / label_rel)})
        coverage.append({"source_id": row["id"], "split": row["split"], "source_annotations": len(row["boxes"]),
                         "covered_annotations": len(covered), "tiles": len(specs), "rejected_boundary_tiles": skipped})
        print(f"Crops: {len(coverage)} source images, {len(tiles)} tiles", flush=True)
    return tiles, coverage


def prepare(source, output, config_path):
    config = load_config(config_path)
    if output.exists():
        raise ValueError("Output already exists; use a new directory, never overwrite a frozen dataset")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows, quarantine = catalog(source)
    if len(rows) != config["expected_source_images"]:
        raise ValueError(f"Expected full dataset ({config['expected_source_images']} images), found {len(rows)}")
    assign_groups(rows)
    mapping = assign_splits(rows, config)
    for split in ("train", "val", "test"):
        count = sum(r["eligible"] and r["split"] == split for r in rows)
        if count < (config["minimum_training_images"] if split == "train" else 10):
            raise ValueError(f"Insufficient eligible {split} source images: {count}")
    # An interrupted build remains a visibly incomplete temporary directory, never a valid dataset.
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.incomplete-", dir=output.parent))
    tiles, coverage = create_tiles(source, temporary, rows, config)
    if any(not any(t["split"] == s for t in tiles) for s in ("train", "val")):
        raise ValueError("No usable training/validation tiles")
    annotation_coverage = sum(c["covered_annotations"] for c in coverage) / sum(c["source_annotations"] for c in coverage)
    write_json(temporary / "coverage.json", coverage)
    if annotation_coverage < config["minimum_tile_annotation_coverage"]:
        raise ValueError(f"Only {annotation_coverage:.1%} of annotations survive cropping; inspect {temporary / 'coverage.json'} before training")
    summary = {"source_images": len(rows), "eligible_images": sum(r["eligible"] for r in rows),
               "quarantined_images": len(quarantine), "groups": len(mapping),
               "splits": {s: {"source_images": sum(r["eligible"] and r["split"] == s for r in rows),
                              "annotations": sum(len(r["boxes"]) for r in rows if r["eligible"] and r["split"] == s),
                              "groups": sum(v == s for v in mapping.values()),
                              "tiles": sum(t["split"] == s for t in tiles)} for s in ("train", "val", "test")},
               "quarantine_reasons": dict(Counter(q["reason"] for q in quarantine)),
               "tile_annotation_coverage": annotation_coverage,
               "evaluation_status": config["evaluation_status"]}
    for name, value in (("catalog.json", rows), ("tiles.json", tiles), ("coverage.json", coverage),
                        ("quarantine.json", quarantine), ("summary.json", summary), ("groups.json", mapping)):
        write_json(temporary / name, value)
    files = sorted(p.name for p in temporary.glob("*.json"))
    write_json(temporary / "complete.json", {"config_sha256": digest(config_path),
               "preparation_code_sha256": digest(Path(__file__)),
               "manifests": {name: digest(temporary / name) for name in files}})
    if output.exists():
        raise ValueError("Output appeared during preparation; refusing overwrite")
    temporary.rename(output)
    print(summary, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Audit, group, and prepare native-resolution cattle crops. Run under SLURM on Oscar.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PACKAGE / "config.json")
    args = parser.parse_args()
    require_compute_job()
    prepare(args.source.resolve(), args.output.resolve(), args.config.resolve())


if __name__ == "__main__":
    main()
