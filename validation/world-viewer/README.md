**HerdProof reproducible worlds, version 2.0.0**

This private source/input bundle builds two walkable fields from saved drone observations. The same image, detector snapshot, camera, terrain and review produce the same exported scene. The training repository's publication rules are unchanged. The existing `validation/terrain-demo` remains available separately.

Run commands from the extracted bundle/workspace root. Preparation and builds never download imagery, call an AI service, retrain a model or run ODM. Python 3.12.11 and the locked Python packages are required; Node 22 was used for geometry checks. Browser dependencies are included in the private bundle.

**Environment**

In the existing workspace, use `scripts/terrain/.venv/bin/python`. On a fresh machine, create that environment once:

```sh
uv sync --project scripts/terrain --python 3.12.11 --frozen
```

That environment setup can need network access if its wheels/interpreter are not cached. After setup, all replay commands below work offline. Dependency versions are pinned in `scripts/terrain/uv.lock` and `validation/world-viewer/pnpm-lock.yaml`. Do not relax the release-age floor or use remote one-shot execution. If browser dependencies were omitted from a source-only copy, run `pnpm install --frozen-lockfile --ignore-scripts` in `validation/terrain-demo` and `validation/world-viewer`; the included bundle needs neither install.

**Prepare, build, review and verify**

```sh
scripts/terrain/.venv/bin/python scripts/terrain/world.py prepare --config validation/worlds/jalogny-south/field.json
scripts/terrain/.venv/bin/python scripts/terrain/world.py build --config validation/worlds/jalogny-south/field.json --offline
scripts/terrain/.venv/bin/python scripts/terrain/world.py verify --scene validation/worlds/jalogny-south/build
scripts/terrain/.venv/bin/python scripts/terrain/world.py review --config validation/worlds/jalogny-south/field.json --port 18771
```

Open `http://127.0.0.1:18771/` to walk; open `/review.html` to edit observations. For the other field, replace `jalogny-south` with `jalogny-north` and use port 18772. Run each review server in a separate terminal. The exported `build` folder can also be served by any static HTTP server; writing reviews requires the local review server.

The review editor supports acceptance/rejection, duplicate merging, adding a missing cow, apparent coat color, angle/180-degree flip/head click, image-space position anchors, foreground/background brush strokes, ground-cleanup rectangles and vegetation settings. Save stores corrections; Save and rebuild updates the scene. An added observation becomes selectable after rebuilding its crop. Review updates use optimistic concurrency: another tab's changes require a reload. A failed rebuild leaves the previous scene intact and retains the correction file for repair.

`prepare` freezes the input hashes and appearance proposals. Changed inputs require an explicit `prepare --refresh-inputs`; changing the image or semantic detection snapshot also requires an explicit review migration. Reordering an otherwise identical observation list preserves IDs and its semantic snapshot. IDs are supplied in the detection snapshot and never assigned from current confidence sorting. A new image is never treated as the same animal population solely because array indices match.

`build --output /path/to/new-directory` makes an independent export. It refuses to overwrite an unrelated directory. Replays cache segmentation and ground texture separately, so color and head corrections reuse the ground texture. Input/review/asset/code hashes, runtime package versions and every output file's hash are recorded in `build-manifest.json`. Operational timing is kept outside deterministic scene content. Identical local exports are tested; cross-platform bitwise identity of image codecs and GPU screenshots is not promised.

**Preparing another field**

Copy an example configuration and supply these explicit inputs:

- Original photograph, with retained EXIF. The builder records all eight EXIF orientation transforms and creates normalized crops. Detection snapshots declare `raw_image` or `normalized_image` coordinates; camera files declare their pixel convention.
- `detections.json`: image SHA256, detector/model provenance and `observations` containing stable `id`, normalized `box: [x1,y1,x2,y2]`, and `confidence`. Use saved model predictions or mark manual additions explicitly; label annotations are not a fallback detection source.
- Numeric north-up terrain raster in a projected metric CRS, `[row, column, height, width]` window, metric origin and vertical-reference description. Invalid cells are excluded from mesh triangles and walker movement. Unsupported placements fail rather than inventing heights.
- A camera JSON with `K`, five Brown distortion coefficients, `world_to_camera_R`, `camera_centre_enu`, `origin_enu`, source-image hash and provenance/limitations. In this convention, browser coordinates are `[east, up, -north]`. A solved camera is a cached preparation input; it does not require solving again during replay. The earlier `scripts/terrain/solve_camera.py` workflow can prepare calibration in the full workspace. The private replay bundle supplies both solved example cameras.
- Optional reference orthophoto plus projected bounds, source manifest, image-space fence/tree annotations and source/reference cleanup masks. Supply compatible reference coverage or omit reference imagery explicitly; unseen ground then has a neutral illustrative appearance. Do not claim it was photographed.

The explicit `world_acquire.py` command can obtain IGN data for compatible French coordinates; it is not called by prepare/build. Example of the already cached north acquisition:

```sh
scripts/terrain/.venv/bin/python scripts/terrain/world_acquire.py --easting 826944 --northing 6590826 --output validation/worlds/jalogny-north/ign
```

Field-specific values belong in configuration/review files. Both provided fields use the exact same source code and asset. The south and north walking footprints are spatially disjoint pastures on the same farm, with camera locations approximately 245 m apart. This demonstrates field portability, not geography-independent elevation acquisition or performance across all breeds.

**Verification**

```sh
scripts/terrain/.venv/bin/python scripts/terrain/world_tests.py
node validation/world-viewer/test_world.mjs validation/worlds/jalogny-south/build validation/worlds/jalogny-north/build
scripts/terrain/.venv/bin/python scripts/terrain/world_validate.py --config validation/worlds/jalogny-south/field.json --config validation/worlds/jalogny-north/field.json --report validation/worlds/evidence/reproducibility.json
```

Python tests exercise observation reordering, incorrect source images/review snapshots, crop orientation, masks and coat colors, camera conventions, missing cells/inputs, empty scenes, manual additions, merge rules, corrupted exports, repeatability and edit isolation. Node checks independent material state, non-planar triangle sampling and 1,000 collider samples per field. The real-field audit runs two fresh builds per field, compares complete manifests/hashes and independently compares exported elevations against the source rasters. The viewer's Check demo button exercises hoof contact, walking, boundaries and performance at 1920 × 1080, saving evidence through the local server.

Shared evidence is under `validation/worlds/evidence`; browser reports/screenshots are under each field's `evidence` directory. Review session timers include idle time. Acquisition and manual alignment done before timing instrumentation are explicitly unmeasured; do not present replay timings as end-to-end new-field preparation time.

**Known limits**

Both real examples contain predominantly white cattle. Synthetic light/dark coat fixtures verify foreground extraction and material independence; broad coat-color robustness still needs diverse real imagery. Seven head directions in each example remain provisional. A reviewed ID confirms an image observation, not a farm tag or cross-flight identity. The south example is an incomplete detected herd; the north source's empty publisher label file is not evidence that it contains no cattle.

Two failed automatic masks in the south example (JAL-012 and JAL-020) were corrected with saved foreground brush strokes. Their coat colors are now estimated from the corrected cow pixels. `evidence/appearance-corrections.json` records those corrections; the original automatic proposals remain cached for comparison.

The north camera is transferred through a cached connected ODM reconstruction from the south reference fit. Its absolute accuracy has no independent north survey control. The source/reference images can differ in date, and the IGN vertical metadata is not fully resolved. Grid spacing and round-trip projection error are implementation properties, not cow-position accuracy claims.

Grass growth/species, tree heights, unseen coat markings, body height and the standing asset's representation of resting cows are approximate. Repairs underneath photographed cows and the marked reference-image groups are synthesized. The appearance estimator can need mask/color review in shadows, crowds and clipped boxes. Original photographs remain unchanged. Asset authors/licenses/checksums are recorded in `ASSETS.json` and per-field manifests.

**Private packaging**

```sh
scripts/terrain/.venv/bin/python scripts/terrain/world.py package --config validation/worlds/jalogny-south/field.json --config validation/worlds/jalogny-north/field.json --destination validation/worlds/deliverables/herdproof-world-v2.zip
```

The archive includes source, locked inputs, reviews, licenses/provenance, verification evidence and browser dependency files. `world-bundle-manifest.json` hashes every archive member. Each field includes `expected-build-manifest.json` for comparing every output hash after replay. Packaging verifies both current builds and refuses stale inputs, reviews or source. It does not publish anything or change Git ignore rules. Extract into a fresh folder, use a prepared Python environment, run prepare/build, and compare `build/build-manifest.json` with the field's `expected-build-manifest.json`.
