# Current default model: 82% precision / 78% recall

Selected by Lucas on September 6, 2026 for the current pipeline/demo.

Use the **corrected full YOLOv8n v2** checkpoint with **confidence 0.70** and **global NMS IoU 0.50**. This is the full corrected training run, not a bale/background fine-tune.

| Metric | Recorded result |
|---|---:|
| Precision | **81.92%** (about 82%) |
| Recall | **77.91%** (about 78%) |
| F1 | **79.86%** |
| Mean absolute count error | **3.03 cows/image** |

These results come from rescoring the saved predictions on 77 images containing 1,041 provisional cow annotations: 811 matches, 990 detections, 179 unmatched detections and 230 misses. This was an exploratory threshold comparison on an already inspected public test benchmark. It is not fresh blind validation, and validation F1 still favored the bale model. The user chose this operating point for its recall/counting tradeoff.

## Exact defaults

- Model configuration: `training/default_model.json`.
- Local weights: `validation/models/herdproof-yolov8n-v2.pt`.
- SHA-256: `aef3ce71f6dfc1be8c58fd600169b1454543e18f37182932f548674322f18909`.
- Oscar source: `/oscar/scratch/lzheng35/herdproof/runs/native1024-v2/yolov8n/fit/weights/best.pt`.
- Cattle class: **0** (not COCO class 19).
- Native tile size and model input: **1024 × 1024**; tile overlap **20%**.
- Per-tile NMS IoU: **0.90**; cross-tile/global NMS IoU: **0.50**.
- Raw prediction confidence floor: **0.05**, retained for traceability. Display/count cutoff: **0.70**.
- Maximum detections per tile: **1,000**.

## Pipeline

`scripts/aerial_infer.py` now uses this configuration by default. It verifies the exact weight checksum and uses the same native tiling, class filter and NMS stages as the Oscar evaluator. It never falls back to another checkpoint or uses annotations for inference.

```sh
# A new photo or a directory of photos:
.venv/bin/python scripts/aerial_infer.py --data /path/to/photos --device cpu

# The existing local dataset; restrict IDs if a smaller run is wanted:
.venv/bin/python scripts/aerial_infer.py --data validation/data --device cpu

# Equivalent package entry point:
.venv/bin/python -m training.infer --data /path/to/photos --device cpu
```

Default output is `validation/runs/default-model`. Each prediction file records image and model hashes. `selection.json` and `report.json` record the selected model and cutoff; a run refuses to mix different inputs or settings. Use a new `--output` directory for a different input set. The `boxes` array retains raw candidates after global NMS; consumers must use `selection.selected_threshold` (0.70). The recorded `count` already applies that threshold.

The overlap/survey pipeline can consume the new run explicitly:

```sh
.venv/bin/python scripts/aerial_survey.py \
  --data validation/data --run validation/runs/default-model \
  --output validation/overlap/default-model
```

On Oscar, run inference only inside an `sbatch`/`srun` GPU allocation with `--device 0`. Set `HERDPROOF_ROOT=/oscar/scratch/lzheng35/herdproof` to resolve the existing pinned checkpoint, or supply its exact path with `--weights`. Do not run inference or dataset loading on a login node.

Existing benchmark, timed-review and terrain-scene outputs retain their original predictions and review provenance. Changing the default governs **new inference**; it does not silently relabel cached scenes as results from this model. Historical COCO reproduction remains available with `scripts/aerial_infer.py --baseline`.

## Verification

All 41 inference, pipeline, runtime and tuning tests passed. A real full-resolution image (`46472379c810`) produced 22 detections at the default threshold through `scripts/aerial_infer.py` on CPU. All 22 boxes matched the saved Oscar detections at IoU ≥ 0.99, with maximum confidence difference 0.000101. The survey consumer accepted the new output and counted the same 22 detections. Evidence is recorded in `validation/default-model-smoke-2026-09-06/verification.json`.
