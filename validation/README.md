# Aerial validation sprint

The current experiment tests **visible cattle in individual aerial images** and
one inventory-reconciliation example. It does not test whole-property coverage,
ownership, capture authenticity, animal re-identification, or loan eligibility.

**Post-evaluation audit:** a correctly paired empty YOLO/VOC annotation contains
multiple visible cattle. See [label-audit.json](label-audit.json). Preserve the
frozen run for reproducibility, but treat its scores as provisional annotation
agreement. Empty-label images are not confirmed negative scenes. Audit labels and
use a fresh independently annotated test set before accuracy or workload claims.

## Reproduce

The Python dependencies are pinned in `../uv.lock`. The resolver retains a
2026-08-22 release cutoff (at least 14 days before the sprint), and installation
uses wheels only. No JavaScript dependencies or remote execution scaffolders are
needed.

From the repository root:

```sh
uv sync --frozen --no-build --python 3.12
.venv/bin/python scripts/fetch_aerial_subset.py
# Download the official release's yolov8n.pt into validation/models/ first.
.venv/bin/python scripts/aerial_infer.py --baseline --device mps
.venv/bin/python scripts/aerial_report.py
.venv/bin/python scripts/build_validation_demo.py
.venv/bin/python scripts/render_aerial_evidence.py
.venv/bin/python -m unittest discover -s scripts -p 'test_validation.py' -v
.venv/bin/python scripts/serve_validation.py --port 18765
```

Use `--device cpu` on machines without a supported GPU. Use a different
`--output` directory when changing hardware or configuration; the default run
refuses to mix configurations. `aerial_report.py --run <directory>` scores a
different run. Demo generation, error overlays, and the local server accept
`--run <directory>`; their default is the baseline run.

Official weights:
<https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt>

Expected SHA-256:
`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`.

The commands above reproduce the historical baseline. New inference without
`--baseline` now uses the [selected corrected full model](../MODEL_DEFAULT.md)
at confidence 0.70, with output in `validation/runs/default-model`.

Inference has automatic package installation and Ultralytics telemetry disabled.
It uses the downloaded local weights. No dataset code is executed.

## Study design

`protocol.json` was written before inference. The downloader deterministically
selects up to three images with nonempty labels and three with empty labels from
each flight. Flight identities come from image directories because some label
directories in the source archive are incorrectly named. Eight of the 25 flights
are used for confidence/mode selection; 17 are reserved for evaluation.

The baseline is official COCO-pretrained YOLOv8n, with **no cattle-specific
fine-tuning**. It compares 1280-pixel whole-image inference against 1024-pixel
overlapping tiles with global NMS. Confidence thresholds are chosen on calibration
flights by minimizing bounding-box false positives plus misses, then count MAE; the choice is saved
before evaluation metrics are computed. Both modes are reported.

This is a stratified exploratory sample, not a farm-population estimate. The same
animals can recur within a flight, and calibration/evaluation farms may overlap.
Report image observations and flight groups, not a number of distinct cattle.
Do not claim an unseen-farm benchmark or that publisher annotations are infallible.

Matching requires one-to-one bounding-box IoU of at least 0.5. A correct total can
still have false detections and missed animals. Report those separately.

## Domain-specific follow-up

After the weak COCO result, `finetune-protocol.json` freezes one 20-epoch follow-up.
`scripts/train_aerial_finetune.py` takes six original calibration flights for
training and reserves two other calibration flights for threshold selection.
The original 17 evaluation flights remain excluded from both. Because baseline
results and error overlays were already inspected, this is explicitly a follow-up
on a known benchmark, not a fresh blind external test.

Two GPU training attempts failed. The completed path uses CPU with unchanged
upstream math. The script records an execution amendment and retains failed runs.
The abandoned partial CPU-loss experiment is not used by the successful path.

```sh
.venv/bin/python scripts/train_aerial_finetune.py
.venv/bin/python scripts/evaluate_aerial_finetune.py
.venv/bin/python scripts/review_workload.py --run validation/runs/finetuned
.venv/bin/python scripts/build_validation_demo.py --run validation/runs/finetuned
.venv/bin/python scripts/render_aerial_evidence.py --run validation/runs/finetuned
.venv/bin/python scripts/summarize_review_sessions.py
.venv/bin/python scripts/write_validation_results.py
.venv/bin/python scripts/serve_validation.py --port 18765 --run validation/runs/finetuned
```

The evaluation checks a calibration tile using **independent** CPU and MPS
predictors before scoring; merely changing a cached predictor's `device` argument
is insufficient. Final results include backend metadata and parity output.

`review_workload.py` adds a secondary point-containment diagnostic matching the
reviewer's marker interface. It does not select model settings. Box IoU errors
can overstate marker edits when only box extent is inaccurate; the two metrics
are reported separately, and neither measures human time.

## Human review

See [crowded-cattle follow-up](CROWDING.md) for the first participant's feedback,
the adjacent-marker bug, interface v2, and the unsuccessful calibration-only
detector probe. The frozen detector is unchanged. New sessions record the
interface version; the original session remains intact.

Open <http://127.0.0.1:18765/> and choose **Timed review**, before viewing the
reconciliation example. Four images from four evaluation flights are selected
using label density, never model success. The order and alternating condition are
randomized per session. Different conditions use different images to avoid
remembering a count; multiple participants and counterbalancing are needed to
separate image difficulty from condition.

Time starts after image loading and the participant's explicit start. The
browser records active visible-tab time and the server records wall time. Every
mark is scored by one-to-one containment in a reference box, with final false
marks and misses reported. Reference counts are withheld until completion.

Use **Add** to mark cows and **Remove** to delete the closest marker. Add never
deletes an adjacent marker. Keyboard shortcuts are A/R, H for marker visibility,
and Command/Ctrl+Z for Undo. Markers use small hollow outlines; the 1:1 pixel
button and zoom support close inspection.

`?qa=1` creates **automated QA** sessions, which are excluded from human results.
The agent must not present its UI interactions as human timing measurements.
Run `.venv/bin/python scripts/summarize_review_sessions.py` to summarize completed
human sessions. Sessions record their pipeline, confidence threshold, and weight
hash; summaries also separate pipeline groups. Regenerate the report with
`.venv/bin/python scripts/write_validation_results.py` after a human review.

Correction operations (`FP + FN`) are only an error-workload proxy. Inspection,
searching for misses, moving markers, and checking empty areas also take time.
No measured time-saving claim is supported without actual human review.

## Reconciliation example

Real historical pasture imagery is divided into artificial West/East image
halves. These are **not actual pens or surveyed parcel boundaries**. A synthetic
CSV contains inventory and a subsequent sale. The demonstration deliberately
omits East evidence, then supplies it. Reference-review steps replay publisher
annotations and are explicitly labeled; they do not pretend the model was correct
or a person performed a new inspection.

The parser supports the stated CSV schema only. Arbitrary PDF extraction,
automatic parcel discovery, flight control, blur/occlusion classification, and
real lender records are outside this sprint.

## Data and outputs

- `data/selection.json`: frozen sample and protocol hash.
- `data/manifest.json`: source mapping, labels, checksums (local only).
- `runs/baseline/`: per-image raw predictions, runtime, frozen calibration choice,
  report, and private review data.
- `review-assets/`: full-resolution review copies without EXIF/GPS.
- `evidence/`: selected error-audit overlays with attribution.
- `sessions/`: locally saved review sessions.

The partial downloader verifies the ZIP CRC32 of each selected member and records
SHA-256. It **cannot verify the publisher's checksum of the whole 16.6 GB archive**.
Raw imagery, metadata, models, and sessions are ignored by Git. Source GPS and
farm names are not served by the review page.

Dataset: Louise Helary and Adrien Lebreton / Institut de l'Elevage,
*Drone images and their annotations of grazing cows*, v2, ICAERUS, CC BY 4.0,
<https://doi.org/10.5281/zenodo.11048412>.

Ultralytics code/weights licensing applies separately from dataset licensing;
this local research prototype is not a decision about proprietary distribution.
