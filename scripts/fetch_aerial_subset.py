#!/usr/bin/env python3
"""Fetch a reproducible small subset of the official ZIP using HTTP ranges.

Never executes archive content; checks lengths, CRC32, and records SHA256. A
partial download cannot verify the publisher's checksum of the entire archive.
Raw source paths and EXIF remain in the ignored local data directory.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import random
import struct
import time
import urllib.request
import zipfile
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

URL = "https://zenodo.org/api/records/11048412/files/Cattle_drone_images_042024.zip/content"
SIZE = 16586848207


class RemoteReader(io.RawIOBase):
    def __init__(self, cache: Path):
        self.pos = 0
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else SIZE + offset
        if not 0 <= self.pos <= SIZE: raise ValueError("invalid seek")
        return self.pos

    def read(self, n=-1):
        if n < 0: n = SIZE - self.pos
        n = min(n, SIZE - self.pos)
        if not n: return b""
        if n > 64 * 1024 * 1024: raise ValueError("Refusing unexpectedly large range")
        start, end = self.pos, self.pos + n - 1
        cached = self.cache / f"{start}-{end}.bin"
        if cached.exists():
            data = cached.read_bytes()
        else:
            for attempt in range(5):
                try:
                    req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}", "User-Agent": "HerdProofResearch/0.1"})
                    with urllib.request.urlopen(req, timeout=45) as response:
                        if response.status != 206: raise RuntimeError("Server did not honor range; refusing full archive")
                        expected = f"bytes {start}-{end}/{SIZE}"
                        if response.headers.get("Content-Range") != expected:
                            raise RuntimeError("Unexpected content range: " + str(response.headers.get("Content-Range")))
                        data = response.read(n + 1)
                    if len(data) != n: raise RuntimeError("Short or oversized response")
                    cached.write_bytes(data)
                    time.sleep(0.65)
                    break
                except Exception:
                    if attempt == 4: raise
                    time.sleep(min(15, 2 ** attempt))
        if len(data) != n: raise RuntimeError("Corrupt range cache")
        self.pos += n
        return data

    def member(self, info):
        self.seek(info.header_offset)
        data = self.read(min(info.compress_size + 4096, SIZE - info.header_offset))
        header = struct.unpack("<4s5H3I2H", data[:30])
        if header[0] != b"PK\x03\x04": raise RuntimeError("Bad local ZIP header")
        offset = 30 + header[-2] + header[-1]
        if offset + info.compress_size > len(data):
            self.seek(info.header_offset + offset)
            body = self.read(info.compress_size)
        else:
            body = data[offset:offset + info.compress_size]
        if info.compress_type == zipfile.ZIP_DEFLATED: raw = zlib.decompress(body, -15)
        elif info.compress_type == zipfile.ZIP_STORED: raw = body
        else: raise RuntimeError("Unsupported compression")
        if len(raw) != info.file_size or zlib.crc32(raw) & 0xffffffff != info.CRC:
            raise RuntimeError("ZIP member integrity failure")
        return raw


def key(name):
    parts = PurePosixPath(name).parts
    i = parts.index("Cattle_drone_images")
    return parts[i + 1], PurePosixPath(name).stem


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("validation/data"))
    parser.add_argument("--protocol", type=Path, default=Path("validation/protocol.json"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(args.protocol.read_text())
    remote = RemoteReader(args.out / "ranges")
    with zipfile.ZipFile(remote) as archive:
        infos = archive.infolist()
    print(f"Indexed {len(infos)} archive entries", flush=True)
    image_keys = {key(i.filename) for i in infos if "/JPGImages/" in i.filename and i.filename.lower().endswith((".jpg", ".jpeg"))}
    images, labels, xmls = {}, {}, {}
    for info in infos:
        if "Cattle_drone_images/" not in info.filename: continue
        name = info.filename
        if "/JPGImages/" in name and name.lower().endswith((".jpg", ".jpeg")): target = images
        elif name.lower().endswith(".txt") and "YOLO" in name: target = labels
        elif name.lower().endswith(".xml") and "Pascal" in name: target = xmls
        else: continue
        k = key(name)
        if k not in image_keys: continue
        if k in target: raise ValueError(f"Ambiguous archive identity: {k}")
        target[k] = info
    flights = defaultdict(list)
    for k, info in sorted(images.items()):
        if k not in labels: raise ValueError("Missing label")
        flight = next(p for p in PurePosixPath(info.filename).parts if p.startswith("DJI_"))
        flights[f"{k[0]}/{flight}"].append(k)
    rng = random.Random(protocol["seed"])
    flight_names = sorted(flights)
    rng.shuffle(flight_names)
    ncal = max(1, round(len(flight_names) * protocol["calibration_fraction"]))
    calibration = set(flight_names[:ncal])
    selection = []
    for flight in sorted(flights):
        keys = flights[flight]
        for positive in (True, False):
            pool = [k for k in keys if (labels[k].file_size > 0) == positive]
            rng.shuffle(pool)
            for k in pool[:protocol["maximum_images_per_flight"] // 2]:
                selection.append((flight, k))
    frozen = [{"id": hashlib.sha256(images[k].filename.encode()).hexdigest()[:12],
               "source": images[k].filename, "label_source": labels[k].filename,
               "flight": flight, "split": "calibration" if flight in calibration else "evaluation"}
              for flight, k in selection]
    frozen_path = args.out / "selection.json"
    freeze = {"protocol_sha256": hashlib.sha256(args.protocol.read_bytes()).hexdigest(), "images": frozen}
    if frozen_path.exists() and json.loads(frozen_path.read_text()) != freeze:
        raise RuntimeError("Selection changed; use a new output directory")
    frozen_path.write_text(json.dumps(freeze, indent=2) + "\n")
    print(f"Froze {len(selection)} images across {len(flights)} flights: {ncal} calibration flights", flush=True)
    def fetch_one(item):
        (flight, k), row = item
        reader = RemoteReader(args.out / "ranges")
        image_path = args.out / (row["id"] + ".jpg")
        label_path = args.out / (row["id"] + ".txt")
        # Resolve the previously audited ambiguous VOC object before inference.
        if k in xmls:
            xml_path = args.out / (row["id"] + ".xml")
            if not xml_path.exists(): xml_path.write_bytes(reader.member(xmls[k]))
            if b"<name>unknown</name>" in xml_path.read_bytes():
                return None, {**row, "reason": "Previously audited ambiguous VOC unknown object"}
        if not image_path.exists(): image_path.write_bytes(reader.member(images[k]))
        if not label_path.exists(): label_path.write_bytes(reader.member(labels[k]))
        for path, info in ((image_path, images[k]), (label_path, labels[k])):
            raw = path.read_bytes()
            if len(raw) != info.file_size or zlib.crc32(raw) & 0xffffffff != info.CRC:
                raise RuntimeError("Cached member integrity failure")
        boxes = []
        for line in label_path.read_text().splitlines():
            fields = line.split()
            if len(fields) != 5 or fields[0] != "0": raise ValueError("Unexpected cattle label")
            x, y, w, h = map(float, fields[1:])
            if not (0 < w <= 1 and 0 < h <= 1 and -1e-6 <= x-w/2 <= x+w/2 <= 1+1e-6 and -1e-6 <= y-h/2 <= y+h/2 <= 1+1e-6):
                raise ValueError("Invalid normalized box")
            boxes.append([x-w/2, y-h/2, x+w/2, y+h/2])
        return {**row, "image": image_path.name, "boxes": boxes,
                        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                        "label_sha256": hashlib.sha256(label_path.read_bytes()).hexdigest()}, None
    records, excluded = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, (record, exclusion) in enumerate(pool.map(fetch_one, zip(selection, frozen))):
            if exclusion: excluded.append(exclusion)
            else: records.append(record)
            print(f"Downloaded {index+1}/{len(selection)}", flush=True)
    output = {"dataset": protocol["dataset_doi"], "attribution": "Louise Helary and Adrien Lebreton / Institut de l'Elevage, ICAERUS grazing cows v2, CC BY 4.0",
              "archive_size": SIZE, "integrity": "Member ZIP CRC32 and retained SHA256; entire archive MD5 not verified by this partial download",
              "protocol_sha256": freeze["protocol_sha256"], "records": records, "excluded": excluded}
    (args.out / "manifest.json").write_text(json.dumps(output, indent=2) + "\n")
    print(f"Complete: {len(records)} images, {sum(len(r['boxes']) for r in records)} annotated observations", flush=True)


if __name__ == "__main__": main()
