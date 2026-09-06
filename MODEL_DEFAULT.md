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

Use `training.count` for the complete counting pipeline:

```text
Original drone photos
  -> selected YOLO model + per-image tile duplicate removal
  -> background alignment between overlapping photos
  -> compare cow observations within the shared visible area
  -> merge repeated sightings across photos
  -> estimated distinct cows + preferred views + unresolved edge captures
```

```sh
# Detect and deduplicate one original-photo folder in one command:
.venv/bin/python -m training.count \
  --data /path/to/photos --flight-id pasture-visit \
  --output validation/counting/pasture-visit --device cpu

# A manifest can describe multiple flights; each flight/date is counted separately:
.venv/bin/python -m training.count \
  --data validation/data --output validation/counting/survey --device cpu

# Rerun only overlap matching using an existing detector run:
.venv/bin/python -m training.count \
  --data validation/data --predictions validation/runs/default-model \
  --output validation/counting/from-saved
```

The input can be an original photo, a flat folder of photos, or a folder containing
`manifest.json`. Original GPS and capture-time metadata are required. Plain folders
are treated as one flight; use a manifest for multiple flights. Capture dates stay
separate. Optional `--image-ids` selects a smaller group, and `--weights` locates the
same SHA-pinned checkpoint elsewhere. Annotations are removed from the pipeline's
input manifest before inference and are never used as a prediction fallback.

The output folder contains `inputs/manifest.json`, `detections/` for new inference,
`overlap/report.json` with tracks and edge evidence, and the final `result.json`.
For one flight/date, `result.json.estimated_unique_observed` contains its estimate.
With multiple surveys that field is null; use the separate `surveys` results.
The pipeline refuses to reuse an output folder with changed inputs or settings,
and writes the final result only after both stages process all selected photos.

Cross-photo matching handles partially clipped cows using their shared visible
portion. An existing full view resolves an edge sighting; an unresolved clipped
track remains in `recapture_targets`, with status `needs_edge_recapture`. Totals are
estimates of distinct observed animals, not verified whole-property herd inventories.
The controlled edge benchmark and its separate set pass 192 cases / 1,293 known
duplicate links; these assess supplied-box geometry rather than detector accuracy.

For detections alone, the original inference commands remain available:

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

The same SLURM requirement applies to `training.count`, including runs that reuse
predictions: background registration is compute work too.

Existing benchmark, timed-review and terrain-scene outputs retain their original predictions and review provenance. Changing the default governs **new inference**; it does not silently relabel cached scenes as results from this model. Historical COCO reproduction remains available with `scripts/aerial_infer.py --baseline`.

## Verification

The integrated `training.count` command passes nine contract tests covering stage
ordering, saved predictions, annotation exclusion, flight/date separation,
failure handling and the login-node guard. The overlap stage passes 30 regression
tests in the local dataset environment.

A complete CPU run on `752332ce22a7` and `90afc33b02c0` used the pinned model at
confidence 0.70, produced 30 detections, and removed 12 repeated sightings after
registration. The resulting 18 proposed tracks include an unresolved clipped
sighting and are reported with `needs_edge_recapture`; this tests the pipeline
handoff and is not a verified 18-cow ground-truth count. Local output is
`validation/counting/pipeline-smoke-20260906/result.json`.

All 41 inference, pipeline, runtime and tuning tests passed. A real full-resolution image (`46472379c810`) produced 22 detections at the default threshold through `scripts/aerial_infer.py` on CPU. All 22 boxes matched the saved Oscar detections at IoU ≥ 0.99, with maximum confidence difference 0.000101. The survey consumer accepted the new output and counted the same 22 detections. Evidence is recorded in `validation/default-model-smoke-2026-09-06/verification.json`.
