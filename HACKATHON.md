# Hackathon submission guide

## Start with the website

From `website/`, use Node.js 22.13+ and run `pnpm install --frozen-lockfile`,
then `pnpm dev`. The terminal prints the local URL. `pnpm build` creates the static
site in `dist/client`. Vercel should use `website` as its root directory.

The repository includes sample photos, recorded detections, the ONNX detector,
and its browser runtime. Sample review uses saved detections; uploading an image
to the browser detector runs actual tiled inference locally in the browser.
The browser demo does not run the Python survey backend or reconstruct 3D worlds.

## Full Python survey and world workflow

Source, dependency locks, viewer code and cow mesh assets are included. Downloaded
source imagery, raster data, trained PyTorch checkpoints, generated experiments,
and private uploaded/session state are not included.

Install the pinned Python environments and viewer dependencies:

```sh
uv sync --frozen --no-build --python 3.12
uv sync --project scripts/terrain --frozen --no-build --python 3.12
cd validation/terrain-demo
pnpm install --frozen-lockfile
cd ../..
```

The current local survey server requires a reference map and demo photograph at
startup, even when you intend to upload your own images. These scripts acquire
its public sample inputs (network access and substantial disk space required):

```sh
.venv/bin/python scripts/fetch_aerial_subset.py
scripts/terrain/.venv/bin/python scripts/terrain/lookup_field.py
scripts/terrain/.venv/bin/python scripts/terrain/acquire_terrain.py
scripts/terrain/.venv/bin/python scripts/terrain/acquire_flight.py
```

The server verifies the reference map against its recorded checksum. An upstream
map change requires deliberate review of its bounds/checksum, not bypassing the
check. World construction also needs the selected `.pt` checkpoint at the path
and SHA-256 recorded in `training/default_model.json`. The browser ONNX export
cannot substitute for that PyTorch checkpoint. See `MODEL_DEFAULT.md`; the
trained checkpoint is not currently distributed by this Git repository.

Once the prerequisites are present:

```sh
scripts/terrain/.venv/bin/python scripts/serve_survey.py --port 18778
```

Open http://127.0.0.1:18778/. Follow
[survey instructions](scripts/survey/README.md) and the
[upload-to-world walkthrough](scripts/survey/WORLD_WORKFLOW.md).
The historical terrain replay additionally requires the original inputs listed
in `validation/terrain-demo/inputs.lock.json`; setup alone does not restore them.

## Evidence and scope

The selected detector's recorded approximately 82% precision / 78% recall are
provisional agreement with previously inspected labels, not fresh blind field
validation. A detection is not ownership, an individual animal identity, full
property coverage, or a lending decision. The world view retains exclusions and
uncertain observations for review. The business example is illustrative.

See `website/public/evidence/`, `validation/RESULTS.md`, `MODEL_DEFAULT.md`, and
`validation/world-viewer/ASSETS.json` for results, provenance and asset credits.
Public sample photos are derived from ICAERUS grazing cows v2, credited to Louise
Helary and Adrien Lebreton / Institut de l'Elevage under CC BY 4.0. Cow mesh assets
are CC0. The browser uses ONNX Runtime Web; see its upstream license at
https://github.com/microsoft/onnxruntime/blob/main/LICENSE.

## Regression checks

```sh
.venv/bin/python -m unittest discover -s training -p 'test_*.py'
.venv/bin/python -m unittest discover -s scripts -p 'test_validation.py'
scripts/terrain/.venv/bin/python -m unittest discover -s scripts -p 'test_survey*.py'
node --test scripts/test_marker_tools.cjs scripts/test_review_summary.cjs
```

Some integration tests require downloaded local fixtures and loopback HTTP ports.
