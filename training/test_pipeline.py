from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from training.common import PACKAGE, digest, load_config, require_compute_job, verify_prepared, write_json
from training.data import assign_groups, assign_splits, catalog, clipped_labels, create_tiles, native_crop, parse_labels, prepare, starts, tile_specs
from training.fetch import safe_extract
from training.metrics import matched_count, summarize
from training.run import training_arguments, write_dataset_yaml


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = load_config()

    def tearDown(self):
        self.temporary.cleanup()

    def test_flight_day_and_duplicate_links_are_transitive(self):
        rows = [dict(image=str(i), flight=f, day=d, image_sha256=h) for i, (f, d, h) in enumerate([
            ("farm/flight1", "farm/day1", "a"), ("farm/flight1", "farm/day2", "b"),
            ("farm/flight2", "farm/day2", "c"), ("other/flight", "other/day", "c"),
            ("separate/flight", "separate/day", "z")])]
        assign_groups(rows)
        self.assertEqual(len({r["group"] for r in rows[:4]}), 1)
        self.assertNotEqual(rows[0]["group"], rows[-1]["group"])

    def test_split_reproducibility_and_group_isolation(self):
        rows = [dict(group=f"g{i}", eligible=True, farm=f"farm{i % 2}", boxes=[[0, 0, .5, .5]])
                for i in range(12) for _ in range(10)]
        a = assign_splits(rows, self.config)
        b = assign_splits(list(reversed(rows)), self.config)
        self.assertEqual(a, b)
        self.assertEqual({r["split"] for r in rows}, {"train", "val", "test"})
        for group in a:
            self.assertEqual(len({r["split"] for r in rows if r["group"] == group}), 1)

    def test_no_gaps_and_native_pixels_with_padding(self):
        self.assertEqual(starts(400), [0])
        positions = starts(5280)
        self.assertEqual(positions[-1], 5280 - 1024)
        self.assertTrue(all(b - a <= 1024 for a, b in zip(positions, positions[1:])))
        image = Image.new("RGB", (5, 3))
        for x in range(5):
            for y in range(3): image.putpixel((x, y), (x * 30, y * 60, 10))
        crop = native_crop(image, 0, 0, 1024)
        self.assertEqual(crop.size, (1024, 1024))
        self.assertEqual(crop.crop((0, 0, 5, 3)).tobytes(), image.tobytes())

    def test_boundary_sliver_rejects_whole_tile(self):
        boxes = [[.1, .1, .2, .2], [.499, .1, .6, .2]]
        clipped, ids = clipped_labels(boxes, 2048, 1024, 0, 0, self.config)
        self.assertIsNone(clipped)
        self.assertEqual(ids, [])
        clipped, ids = clipped_labels(boxes[:1], 2048, 1024, 0, 0, self.config)
        self.assertEqual(ids, [0])
        self.assertAlmostEqual(clipped[0][2], .2)

    def test_extra_native_crops_rescue_grid_boundary_cows(self):
        boxes = [[1000 / 2048, .2, 1100 / 2048, .3], [800 / 2048, .2, 822 / 2048, .3],
                 [1020 / 2048, .5, 1025 / 2048, .6]]
        grid_covered = set()
        for x in starts(2048):
            _, indices = clipped_labels(boxes, 2048, 1024, x, 0, self.config)
            grid_covered.update(indices)
        self.assertNotIn(0, grid_covered)
        specs, covered, _ = tile_specs(boxes, 2048, 1024, self.config)
        self.assertEqual(covered, {0, 1, 2})
        self.assertTrue(any(x not in starts(2048) for x, _, _, _ in specs))

    def test_label_validation(self):
        label = self.root / "label.txt"
        for value in ("0 nan .5 .1 .1", "1 .5 .5 .1 .1", "0 .01 .5 .5 .1", "0 .5 .5 -.1 .1"):
            label.write_text(value)
            with self.assertRaises(ValueError): parse_labels(label)
        label.write_text("0 .5 .5 .2 .2\n")
        self.assertEqual(len(parse_labels(label)), 1)

    def make_source(self, index, label, voc_name="cow"):
        stem = f"DJI_2023010{index}120000_0001_V"
        base = self.root / "Cattle_drone_images/Farm"
        image = base / f"JPGImages/DJI_2023010{index}_001/{stem}.JPG"
        yolo = base / f"YOLO_1.1/obj/{stem}.txt"
        xml = base / f"Pascal_VOC1.1/Annotations/{stem}.xml"
        for path in (image, yolo, xml): path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2048, 1024), (index * 30, 20, 10)).save(image)
        yolo.write_text(label)
        xml.write_text("<annotation>" + (f"<object><name>{voc_name}</name></object>" if label else "") + "</annotation>")
        return image

    def test_empty_and_unknown_labels_quarantined(self):
        self.make_source(1, "")
        self.make_source(2, "0 .5 .5 .1 .1", "unknown")
        self.make_source(3, "0 .5 .5 .1 .1")
        rows, quarantine = catalog(self.root)
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r["eligible"] for r in rows), 1)
        self.assertEqual(len(quarantine), 2)
        with self.assertRaisesRegex(ValueError, "Expected full dataset"):
            prepare(self.root, self.root / "prepared", PACKAGE / "config.json")

    def test_tiles_never_include_test_or_empty_background(self):
        image = self.make_source(3, "0 .25 .5 .1 .1")
        rows, _ = catalog(self.root)
        row = rows[0]
        row.update(group="g1", split="train")
        tiles, _ = create_tiles(self.root, self.root / "out", rows + [{**row, "split": "test"}], self.config)
        self.assertTrue(tiles)
        self.assertTrue(all(t["split"] == "train" and t["objects"] > 0 for t in tiles))
        with Image.open(image) as original, Image.open(self.root / "out" / tiles[0]["image"]) as crop:
            expected = native_crop(original.convert("RGB"), tiles[0]["x"], tiles[0]["y"], 1024)
            self.assertEqual(crop.tobytes(), expected.tobytes())

    def test_frozen_manifests_and_tiles_detect_changes(self):
        (self.root / "tile.png").write_bytes(b"test image")
        (self.root / "tile.txt").write_text("0 .5 .5 .1 .1")
        tiles = [{"image": "tile.png", "label": "tile.txt", "image_sha256": digest(self.root / "tile.png"),
                  "label_sha256": digest(self.root / "tile.txt")}]
        write_json(self.root / "tiles.json", tiles)
        write_json(self.root / "complete.json", {"config_sha256": digest(PACKAGE / "config.json"),
                   "manifests": {"tiles.json": digest(self.root / "tiles.json")}})
        verify_prepared(self.root, PACKAGE / "config.json")
        (self.root / "tile.txt").write_text("")
        with self.assertRaisesRegex(ValueError, "tile changed"):
            verify_prepared(self.root, PACKAGE / "config.json")

    def test_arguments_disable_resizing_and_yaml_has_no_test(self):
        args = training_arguments(self.config, "data.yaml", "runs", "test")
        for key in ("scale", "translate", "mosaic", "mixup", "multi_scale", "perspective", "degrees", "shear"):
            self.assertFalse(args[key])
        self.assertEqual(args["imgsz"], 1024)
        import yaml
        path = write_dataset_yaml(self.root, self.root)
        self.assertNotIn("test", yaml.safe_load(path.read_text()))

    def test_maximum_matching_does_not_reward_duplicate_markers(self):
        truth = [[0, 0, .5, .5], [.1, 0, .6, .5]]
        self.assertEqual(matched_count([truth[0]] * 3, [truth[0]]), 1)
        self.assertEqual(matched_count([[.05, 0, .55, .5], [0, 0, .4, .5]], truth), 2)
        self.assertEqual(matched_count([], truth), 0)
        report = summarize([dict(group="g", matched=1, predicted=3, annotated=2)])
        self.assertEqual(report["annotation_disagreements"], 3)

    def test_archive_path_traversal_rejected(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as z: z.writestr("../escape.txt", "bad")
        with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
            safe_extract(archive, self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_login_node_guard(self):
        with patch("socket.getfqdn", return_value="login001.oscar.ccv.brown.edu"), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "login node"):
                require_compute_job()


if __name__ == "__main__":
    unittest.main()
