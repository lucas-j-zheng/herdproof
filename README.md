# HerdProof

Aerial cattle counting and evidence review for agricultural lending.

## Hackathon demo

The website includes interactive sample-photo review and an in-browser cattle
detector for uploaded images. Its ONNX model, WebAssembly runtime, sample images,
and recorded demo detections are included in this repository.

With Node.js 22.13+ and pnpm:

```sh
cd website
pnpm install --frozen-lockfile
pnpm dev
```

Open the local URL printed by the server. Use `pnpm build` for a static production
build. For Vercel, set the project root to `website`; its `vercel.json` contains the
build settings. See [website setup](website/README.md).

## Included workflows

- [Website and browser demo](website/): image review, browser inference, product story and evidence.
- [Upload → boundary → world](scripts/survey/WORLD_WORKFLOW.md): photo processing, inference and world construction.
- [Survey application](scripts/survey/README.md): metadata/reuse checks, persistence and evidence export.
- [Counting pipeline](scripts/AERIAL_SURVEY.md): tiled inference and cross-photo duplicate handling.
- [Training](training/): detector training, recovery, evaluation, tuning and SLURM scripts.
- [3D viewer](validation/world-viewer/README.md) and [terrain pipeline](validation/terrain-demo/README.md): geometry and observation review.

The browser demo is the self-contained starting point for judges. The Python
workflow also needs downloaded inputs and model weights; see
[setup and submission notes](HACKATHON.md).

## Model and validation

**Default detector:** corrected full YOLOv8n v2, confidence **0.70**, global NMS
**0.50**. Its recorded diagnostic results are approximately **82% precision /
78% recall**. See [the selected model and pipeline settings](MODEL_DEFAULT.md).
New inference uses this model by default:

```sh
.venv/bin/python scripts/aerial_infer.py --data /path/to/photos --device cpu
```

**Current finding:** some source label files omit visible cows. Recorded benchmark
scores measure agreement with those labels and remain provisional. The local
model and review workflow run; reliable accuracy requires independently checked
reference labels.

- [Current measured results](validation/RESULTS.md)
- [Crowded-cattle feedback and interface fix](validation/CROWDING.md)
- [Reproduction and study design](validation/README.md)
- [Original research](RESEARCH_2026-09-05.md)

Start the local interface after preparing the experiment outputs:

```sh
.venv/bin/python scripts/serve_validation.py --port 18765 --run validation/runs/finetuned
```

Open <http://127.0.0.1:18765/>. Timed review requires a person; automated QA is
explicitly labeled and excluded from human measurements.

`PLAN.md` and `FEASIBILITY.md` document the earlier fixed-camera passage proposal.
The aerial sprint has its own frozen protocols and measured results linked above.
