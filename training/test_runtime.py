"""Regression coverage for interrupted jobs and numerical completion gates."""
from contextlib import ExitStack
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.common import PACKAGE, atomic_output, configure_runtime, digest, exclusive_lock, load_config, read_json, write_json
from training.run import training_arguments
from training.runtime import TrainingMonitor, checked_trainer, ensure_finite, read_recovery, restore_recovery
import training.evaluate as evaluation
import training.run as runner


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.TemporaryDirectory()
        configure_runtime(Path(cls.cache.name))
        import torch
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        cls.cache.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_atomic_write_failure_preserves_previous_json(self):
        target = self.root / "state.json"
        write_json(target, {"epoch": 1})
        with self.assertRaisesRegex(RuntimeError, "interruption"):
            with atomic_output(target) as temporary:
                temporary.write_text("partial")
                raise RuntimeError("interruption")
        self.assertEqual(read_json(target), {"epoch": 1})
        self.assertEqual(list(self.root.iterdir()), [target])
        with self.assertRaises(ValueError):
            write_json(target, {"loss": float("nan")})
        self.assertEqual(read_json(target), {"epoch": 1})

    def test_lock_blocks_concurrent_writer_and_releases_after_exception(self):
        path = self.root / "stage.lock"
        with self.assertRaisesRegex(ValueError, "interruption"):
            with exclusive_lock(path):
                with self.assertRaisesRegex(RuntimeError, "Another process"):
                    with exclusive_lock(path):
                        self.fail("Acquired a busy lock")
                raise ValueError("interruption")
        with exclusive_lock(path):
            pass

    def test_smoke_reaches_two_accumulated_updates_after_warmup(self):
        import numpy as np
        from ultralytics.cfg import get_cfg
        for batch in (1, 2, 4, 8, 16):
            config = {**load_config(), "batch": batch}
            args = get_cfg(overrides=training_arguments(config, "data", "runs", "fit", smoke=True))
            self.assertEqual(args.warmup_bias_lr, 0.)
            self.assertEqual(args.patience, 0)
            nb = math.ceil(32 / batch)
            warmup = max(round(args.warmup_epochs * nb), 100)
            last, after = -1, 0
            for ni in range(args.epochs * nb):
                accumulation = max(round(args.nbs / batch), 1)
                if ni <= warmup:
                    accumulation = max(1, int(np.interp(ni, [0, warmup], [1, args.nbs / batch]).round()))
                if ni - last >= accumulation:
                    last = ni
                    after += ni > warmup
            self.assertGreaterEqual(after, 2)

    def test_nan_loss_and_gradients_fail_before_optimizer_mutation(self):
        import torch
        for value in (float("nan"), {"loss": [torch.tensor(float("inf"))]}):
            with self.assertRaisesRegex(RuntimeError, "Nonfinite"):
                ensure_finite(value, "probe")
        model = torch.nn.Linear(1, 1)
        before = model.weight.detach().clone()
        model.weight.grad = torch.full_like(model.weight, float("nan"))
        fake = SimpleNamespace(loss=torch.tensor(1.), loss_items=torch.ones(3), model=model)
        with self.assertRaisesRegex(RuntimeError, "gradients"):
            checked_trainer().optimizer_step(fake)
        self.assertTrue(torch.equal(before, model.weight))
        with torch.no_grad():
            model.weight.fill_(float("nan"))
        with self.assertRaisesRegex(RuntimeError, "checkpoint"):
            ensure_finite(model, "checkpoint")

    def test_validation_workers_respect_slurm_cpu_allocation(self):
        from ultralytics.models.yolo.detect import DetectionTrainer
        cls = checked_trainer()
        trainer = object.__new__(cls)
        trainer.args = SimpleNamespace(workers=4)
        def upstream(instance, dataset, batch, rank, mode):
            return instance.args.workers * (2 if mode == "val" else 1)
        with patch.dict("os.environ", {"SLURM_CPUS_PER_TASK": "4"}), patch.object(DetectionTrainer, "get_dataloader", upstream):
            self.assertEqual(trainer.get_dataloader("unused", mode="val"), 4)
            self.assertEqual(trainer.get_dataloader("unused", mode="train"), 4)
        self.assertEqual(trainer.args.workers, 4)

    def test_smoke_cannot_complete_without_updates_and_steady_state(self):
        monitor = TrainingMonitor(self.root)
        with self.assertRaisesRegex(RuntimeError, "weight updates"):
            monitor.completion_checks(True)
        monitor.state.update(weights_changed=True, optimizer_steps=7)
        with self.assertRaisesRegex(RuntimeError, "post-warmup"):
            monitor.completion_checks(True)
        monitor.state["post_warmup_steps"] = 2
        self.assertTrue(monitor.completion_checks(True)["weights_changed"])

    def snapshot_fixture(self):
        import torch
        write_json(self.root / "recipe.json", {"test": "recovery"})
        weights = self.root / "fit/weights"
        weights.mkdir(parents=True)
        for name in ("last", "best"):
            (weights / (name + ".pt")).write_bytes(name.encode())
        trainer = SimpleNamespace(model=torch.nn.Linear(1, 1), epoch=0, stop=False,
                                  metrics={"map": .5}, fitness=.5, last=weights / "last.pt", best=weights / "best.pt",
                                  stopper=SimpleNamespace(best_epoch=1, best_fitness=.5, possible_stop=False))
        monitor = TrainingMonitor(self.root, device_type="cpu")
        return trainer, monitor

    def test_epoch_timing_includes_validation_and_save_once(self):
        trainer, monitor = self.snapshot_fixture()
        with patch("training.runtime.time.monotonic", side_effect=[10., 12., 17.]):
            monitor.start_epoch(trainer)
            monitor.end_training(trainer)
            monitor.finish_epoch(trainer)
            monitor.finish_epoch(trainer)  # final_eval callback is not another epoch
        times = read_json(self.root / "timing.json")
        self.assertEqual(times, [{"epoch": 1, "training_seconds": 2., "epoch_seconds": 7., "validation_and_save_seconds": 5.}])

    def test_recovery_survives_torn_latest_write_and_preserves_recipe(self):
        trainer, monitor = self.snapshot_fixture()
        for epoch in range(2):
            trainer.epoch = epoch
            monitor.start_epoch(trainer)
            monitor.end_training(trainer)
            monitor.finish_epoch(trainer)
        recipe = digest(self.root / "recipe.json")
        latest = read_recovery(self.root, recipe)
        self.assertEqual(latest["epoch"], 2)
        trainer.last.write_bytes(b"torn upstream write")
        self.assertEqual(read_recovery(self.root, recipe)["epoch"], 2)
        (self.root / latest["last"]).write_bytes(b"damaged snapshot")
        fallback = read_recovery(self.root, recipe)
        self.assertEqual(fallback["epoch"], 1)
        with self.assertRaisesRegex(ValueError, "different recipe"):
            read_recovery(self.root, "changed")
        (self.root / "fit/results.csv").write_text("epoch,loss\n1,0.5\n2,0.4\n")
        restore_recovery(self.root, fallback)
        self.assertEqual((self.root / "fit/results.csv").read_text(), "epoch,loss\n1,0.5\n")
        self.assertEqual(read_json(self.root / "timing.json")[0]["epoch"], 1)
        monitor = TrainingMonitor(self.root, device_type="cpu", restored=fallback["monitor"])
        trainer.epoch = 1
        monitor.start_epoch(trainer)
        monitor.end_training(trainer)
        monitor.finish_epoch(trainer)
        pointers = read_json(self.root / "recovery.json")["checkpoints"]
        self.assertEqual(pointers[1]["last"], fallback["last"])
        self.assertEqual(len(list((self.root / "recovery").iterdir())), 2)

    def test_smoke_retry_before_first_checkpoint_preserves_failed_attempt(self):
        prepared = self.root / "prepared"
        prepared.mkdir()
        write_json(prepared / "complete.json", {})
        write_json(prepared / "tiles.json", [{"split": "train", "image": "tile.png", "objects": 1},
                                              {"split": "val", "image": "tile.png", "objects": 1}])
        weights = self.root / "weights"
        weights.mkdir()
        weight = weights / "yolov8n.pt"
        weight.write_bytes(b"inert fixture")
        args = SimpleNamespace(config=PACKAGE / "config.json", prepared=prepared, weights=weights,
                               runs=self.root / "runs", mode="smoke", variant="yolov8n", resume=False, resume_if_needed=True)
        original_read = runner.read_json

        def read(path):
            return {"weights": {"yolov8n": {"sha256": digest(weight)}}} if path == PACKAGE / "assets.json" else original_read(path)

        class InterruptedYOLO:
            def __init__(self, checkpoint): self.callbacks = {}
            def train(self, **kwargs):
                fit = Path(kwargs["project"]) / "fit"
                fit.mkdir()
                (fit / "attempt.txt").write_text("preserve")
                raise RuntimeError("injected pre-checkpoint interruption")

        with ExitStack() as stack:
            stack.enter_context(patch.object(runner, "cuda_environment", return_value={"slurm_job_id": "test"}))
            stack.enter_context(patch.object(runner, "verify_prepared"))
            stack.enter_context(patch.object(runner, "read_json", side_effect=read))
            stack.enter_context(patch("ultralytics.YOLO", InterruptedYOLO))
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "pre-checkpoint interruption"):
                    runner.run(args)
        folder = args.runs / "smoke-yolov8n"
        self.assertEqual(len(list((folder / "interrupted").glob("*/fit/attempt.txt"))), 1)
        self.assertFalse((folder / "complete.json").exists())

    def evaluation_fixture(self):
        prepared = self.root / "prepared"
        prepared.mkdir()
        write_json(prepared / "complete.json", {})
        rows = [dict(id=split, split=split, eligible=True, group="g", flight="f", boxes=[[.1, .1, .3, .3]])
                for split in ("val", "test")]
        write_json(prepared / "catalog.json", rows)
        checkpoint = self.root / "checkpoint.pt"
        checkpoint.write_bytes(b"inert fixture")
        output = self.root / "evaluation"
        output.mkdir()
        args = SimpleNamespace(config=PACKAGE / "config.json", prepared=prepared, source=self.root,
                               runs=self.root / "runs", output=output, stage="select")
        return args, load_config(), checkpoint

    def test_evaluation_prerequisite_failure_does_not_poison_stage(self):
        args, config, _ = self.evaluation_fixture()
        with patch.object(evaluation, "checkpoint_for", side_effect=RuntimeError("transient checkpoint error")):
            with self.assertRaisesRegex(RuntimeError, "transient"):
                evaluation.evaluate_stage(args, config, {})
        self.assertFalse((args.output / "select.started.json").exists())

    def test_evaluation_retries_keep_winner_and_skip_completed_stages(self):
        args, config, checkpoint = self.evaluation_fixture()

        def predict(checkpoint, source, records, config, cache=None):
            return {row["id"]: [[.1, .1, .3, .3, .9]] for row in records}

        with patch.object(evaluation, "checkpoint_for", return_value=checkpoint), patch.object(evaluation, "predict_sources", side_effect=predict):
            evaluation.evaluate_stage(args, config, {"job": "first"})
        winner_hash = digest(args.output / "winner.json")
        args.stage = "test"
        with patch.object(evaluation, "checkpoint_for", return_value=checkpoint), patch.object(evaluation, "predict_sources", side_effect=RuntimeError("interruption")):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                evaluation.evaluate_stage(args, config, {})
        with patch.object(evaluation, "checkpoint_for", return_value=checkpoint), patch.object(evaluation, "predict_sources", side_effect=predict) as predictor:
            args.stage = "select"
            evaluation.evaluate_stage(args, config, {"job": "retry"})
            predictor.assert_not_called()
            args.stage = "test"
            evaluation.evaluate_stage(args, config, {"job": "retry"})
            self.assertEqual(predictor.call_count, 1)
            evaluation.evaluate_stage(args, config, {})
            self.assertEqual(predictor.call_count, 1)
        self.assertEqual(digest(args.output / "winner.json"), winner_hash)
        (args.output / "winner.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "output changed"):
            evaluation.completed_stage(args.output, "select")

    def test_evaluation_rejects_changed_recipe_after_interruption(self):
        args, config, checkpoint = self.evaluation_fixture()
        with patch.object(evaluation, "checkpoint_for", return_value=checkpoint), patch.object(evaluation, "predict_sources", side_effect=RuntimeError("interruption")):
            with self.assertRaises(RuntimeError):
                evaluation.evaluate_stage(args, config, {})
            checkpoint.write_bytes(b"different model")
            with self.assertRaisesRegex(ValueError, "different experiment"):
                evaluation.evaluate_stage(args, config, {})

    def test_prediction_retry_reuses_completed_images(self):
        from PIL import Image
        import torch
        rows = []
        for i in range(2):
            image, label = self.root / f"{i}.png", self.root / f"{i}.txt"
            Image.new("RGB", (1024, 1024)).save(image)
            label.write_text("0 .5 .5 .1 .1")
            rows.append(dict(id=str(i), image=image.name, label=label.name,
                             image_sha256=digest(image), label_sha256=digest(label)))
        calls = []
        class Predictor:
            def __init__(self, checkpoint): pass
            def predict(self, *args, **kwargs):
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError("interrupted second image")
                return [SimpleNamespace(boxes=SimpleNamespace(data=torch.tensor([[10., 10., 20., 20., .9, 0.]])))]
        with patch("ultralytics.YOLO", Predictor):
            with self.assertRaisesRegex(RuntimeError, "second image"):
                evaluation.predict_sources(self.root / "unused.pt", self.root, rows, load_config(), self.root / "cache")
            result = evaluation.predict_sources(self.root / "unused.pt", self.root, rows, load_config(), self.root / "cache")
        self.assertEqual(len(calls), 3)
        self.assertEqual(set(result), {"0", "1"})


if __name__ == "__main__":
    unittest.main()
