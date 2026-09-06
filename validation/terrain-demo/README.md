# Reproducible measured-field demo

The renderer is a view of saved field data. The elevation raster, camera
calibration, alignment landmarks, detections, review decisions and asset files are
inputs to a repeatable build. No paid service or generative-world API is used. An ordinary rebuild is offline and does not run model training or ODM.

From the repository root:

```sh
# Once on a new machine: install the locked dependencies.
scripts/terrain/demo.sh setup

# Rebuild twice from the saved inputs and compare every generated file.
scripts/terrain/demo.sh build --check-repeatability

# Run the result locally; then open http://127.0.0.1:18770/.
scripts/terrain/demo.sh serve
```

Tested runtime: Python 3.12.11, Node 22.19.0, pnpm 10.23.0. Python dependencies
are isolated in `scripts/terrain/.venv` and pinned by `uv.lock`. Browser packages
are pinned by `pnpm-lock.yaml`. Setup respects the package release-age floor and
disabled lifecycle scripts. It needs network access only to obtain missing locked
dependencies. Subsequent builds need the local input snapshot, not an API key.

The build uses a fresh staging directory, checks its geometry and collision mesh,
and publishes only after validation succeeds. The previous `public` directory is
retained under `data/previous-public-*`. Reload an already open browser after a
rebuild. Do not treat a stale browser tab as the rebuilt result.

## What is saved, and what is rebuilt

| File | Purpose |
| --- | --- |
| `project.json` | Paths, coordinate origin, terrain crop, texture resolution and field metadata |
| `inputs.lock.json` | SHA256 of every required input; missing or changed inputs fail the build |
| `data/ign/terrain.tif` | Frozen IGN numeric elevation subset, 0.5 m cells |
| `data/ign/reference-ortho.jpg` | Frozen reference imagery and its bounds in `project.json` |
| `camera-calibration.json` | Saved Brown intrinsics from the ODM experiment, with source hash |
| `landmarks.json` | Original-image/reference-image pixel pairs, fit/holdout roles and pick uncertainty |
| `cow-review.json` | Accepted/rejected detector candidates, stable IDs, head vectors and uncertainty |
| `texture-masks.json` | Publisher boxes used only to erase photographed cows from the ground texture |
| `features.json` | Reviewed image anchors for fences, tree and pond; estimated dimensions are explicit |
| `assets/` | Frozen CC0 cow mesh and surface normal texture |
| `public/` | Generated terrain, orthorectified appearance, cow positions/crops and build manifest |
| `evidence/` | Rebuild comparison, geometry/collision checks, browser tests and screenshots |

The build fits the camera pose to the saved landmarks, projects the photograph
onto measured terrain, removes cattle/shadow candidate patches from that texture,
intersects reviewed detections with the terrain plus an explicit body-height
assumption, and exports the scene. The browser creates one canonical triangle
mesh and gives its exact buffers to Rapier. Grass uses a fixed seed; walking uses
a fixed 60 Hz simulation timestep. Frame timing and wind animation are not
promised to yield identical screenshots on different GPUs.

`build --check-repeatability` verifies byte identity of generated scene files on
the tested machine and locked runtime. It is not a claim that an unpinned future
ODM run or a different GPU will be bit-for-bit identical.

## Reusing the pipeline for another field

Copy the demo directory as a template, then replace the inputs referenced by its
`project.json`. The offline preprocessing commands accept `--project PATH`.

Required data:

1. A north-up **projected, metric** ground-elevation GeoTIFF with square cells.
   Provide a valid crop without nodata holes, its actual CRS/vertical reference,
   a local coordinate origin and a reference orthophoto with matching map bounds.
   Reproject incompatible rasters before this stage. DSM/canopy heights should
   not be substituted for a ground DTM.
2. The original drone image and detector JSON containing normalized
   `predictions: [[x1, y1, x2, y2, confidence], ...]`. Preserve original pixels and
   reverse any detector letterboxing/cropping before writing this contract.
3. Brown/OpenCV intrinsics and distortion coefficients in original-image pixels.
   Supply at least six well-spread static fitting landmarks and separate held-out
   landmarks. The current pipeline fits a nadir camera prior; it does not infer
   trustworthy elevation or calibration from a single arbitrary photograph.
4. A review entry for every detection. Accepted observations need a unique
   `sceneCowId`, an image-space head/axis vector, heading uncertainty and a body
   height assumption. Real farm identities remain separate. Rejected detections
   retain their reason. This review is an explicit input, not hidden code.
5. Optional mapped feature anchors and a suitable cow asset. The current visual
   template is white/cream cattle on pasture; other coats, crops or asset rigs need
   corresponding visual configuration. It is not an automatic crop classifier.

After deliberately changing inputs:

```sh
# Review the changes before accepting a new snapshot.
scripts/terrain/demo.sh lock-inputs --project /path/to/field/project.json
scripts/terrain/demo.sh build --project /path/to/field/project.json --check-repeatability
```

A changed hash never silently updates its lock. The build will stop and name the
changed input. It also rejects malformed IDs, unreviewed detections, missing
height cells, invalid projection rays and failed geometry checks. Acquiring data
and picking/validating landmarks remain separate from the renderer.

## Original Jalogny acquisition and ODM experiment

The bundled snapshot is sufficient for rebuilding the demo. The acquisition
adapters in `scripts/terrain/` are specific to this public sample; they are not
needed for every build. The 53-photo acquisition manifest records member CRC32
and SHA256. This does not verify the full 16.6 GB publisher archive checksum.
The IGN WMS URLs and elevation hashes are in `data/ign/source-manifest.json`.
The frozen files are preferable for reproduction because public imagery and
terrain services may change editions.

For the optional experiment, `acquire_flight.py` downloads only the selected
flight, and `prepare_odm.py` creates isolated input copies and conservative
bright-candidate masks. The pinned official container was run as follows:

```sh
docker run --rm --network none --cpus 4 --memory 6g --memory-swap 6g \
  -v "$PWD/validation/terrain-demo/data/odm:/datasets" \
  opendronemap/odm@sha256:f3503aab96ab09144e85a17f4e57dbe3883e65ca7542b1a1be12898e02be5a10 \
  --project-path /datasets --end-with opensfm --feature-quality medium \
  --feature-type sift --max-concurrency 4 --matcher-neighbors 12 \
  --gps-accuracy 5 --skip-report field
```

This reconstructed 42/53 photos in nine initially separate groups. The demo
belongs to a six-image group. ODM's later georeferenced merge does not prove
photogrammetric connectivity between those groups. The experiment supplied
calibration evidence; IGN supplies the ground. Dense reconstruction was not
promoted to a terrain measurement. See `data/odm/evaluation.json`.

## Verification and portable backup

The build runs `validate_export.py` and `validate.mjs`. In the browser, **Check
demo** verifies the actual runtime collider, hoof markers and walking, then
measures a 1920 × 1080 rendering workload for ten seconds. Check in both overview
and walking modes. **Capture** saves the rendered scene in `evidence/`.

```sh
scripts/terrain/demo.sh package
```

This creates `deliverables/herdproof-terrain-demo-reproducible.zip`, containing
the source, dependency locks, required frozen input snapshot, review files and
reports. It excludes the 53-photo flight, Docker outputs, installed dependencies,
training data and training work. Extract it into an empty directory and run the
same three setup/build/serve commands. The repository intentionally ignores local
research/demo artifacts; this archive provides a portable backup without
changing the training repository's publication policy.

Attribution: drone imagery by Louise Helary and Adrien Lebreton / Institut de
l'Elevage, [ICAERUS grazing cows v2](https://zenodo.org/records/11048412), CC BY
4.0; elevation/reference imagery by [IGN](https://cartes.gouv.fr/), Licence
Ouverte 2.0; cow model by Lyndon Daniels,
[Realtime Ranchers](https://opengameart.org/content/realtime-ranchers-3d-model-pack),
CC0. The coat adjustment and simple rig are local approximations, not recovered
photographic detail. Original `cow.zip` SHA256:
`27b2c953b6805ee0389e34da820c6013c8ae9e15b2ea58482e2bccaaf3e19950`.
