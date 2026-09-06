# Upload photos → draw boundary → walk the field

This is a working local production-style flow, including real model inference.
It extends the existing survey application; it does not use prebuilt example worlds
as the output of an upload.

Run from the repository root:

```sh
scripts/terrain/.venv/bin/python scripts/serve_survey.py --port 18778 --state validation/survey-world-demo/state
```

Open **http://127.0.0.1:18778/**. Upload original flight photos, click the boundary
corners on their combined map, name the field, then choose **Build world**. An
unsaved boundary is saved automatically. Follow the progress and choose **Enter
world** when it finishes. **Review findings** shows the original crops behind all
sightings, including observations that could not be rendered reliably. This first
upload flow offers inspection of findings; it does not yet provide correction and
approval tools for the multi-photo world. Existing single-photo review editors
remain available separately.

A build uses the exact currently selected checkpoint and operating point from
`training/default_model.json`: native 1024-pixel tiles, class 0, threshold 0.70 and
0.50 global NMS. `training.infer` checks the model checksum and reads the uploaded
pixels. No annotations or sample detection snapshots are substituted. The root
`.venv` is the locked detector environment; `scripts/terrain/.venv` is the locked
geometry environment. No additional packages were installed.

## What happens automatically

1. Original bytes and metadata are retained. Supported camera metadata positions
   photos; checked background matches refine overlapping views. The photo map is
   an approximate ground-plane composite, not an orthorectified survey.
2. The polygon and photo placements become an immutable job snapshot. Repeated
   requests for that snapshot and pipeline version return the same saved job.
3. The selected model runs on each original image. Model/source checksums and all
   raw predictions are retained, including candidates below the display cutoff.
4. Numeric IGN elevation is selected from cached coverage or downloaded for the
   boundary through the IGN WMS raster service. It is resampled to a 1 m grid.
   Elevation covering less than 98% of the polygon stops the build. There is no
   invented flat-ground fallback.
5. Cow positions use the map's planar photo transforms and are grounded on that
   elevation. Original crop pixels supply foreground coat color and undirected
   body axes. Actual head direction remains unknown. IDs identify observations.
6. Conservative duplicate matching requires a direct accepted background link,
   captures within 30 seconds, projected box IoU ≥ 0.5, and centers within 1.2 m.
   Matching sightings retain links to every source. This is not animal identity.
7. Unreliable masks and intersecting standing models are retained as review
   findings. Cow models are never moved to make the layout look plausible.
   Observations outside the polygon or without enough ground for their feet are
   also retained, with the reason they were not displayed. Displayed cows are a
   subset of sightings and must not be presented as a verified herd count.
8. Cow pixels are repaired in texture copies before those images are combined.
   Uploaded originals are unchanged. The ground mesh and walker respect the
   polygon and missing elevation. Grass is illustrative and limited by apparent
   ground color. Trees, fences and hidden geometry are not inferred.
9. Every output is hashed and original crops are compared against their source
   photos. A static viewer and a private replay archive are produced.

## Supported inputs and limits

- 1–24 original JPEG/PNG photos, at most 20 MiB and 32 MP each.
- Near-vertical DJI camera metadata: GPS, relative altitude (5–500 m), gimbal
  yaw/pitch/roll, 35 mm equivalent focal length, unrotated camera pixels.
- France (EPSG:2154); imagery from the same date within a ten-minute survey.
- One valid polygon without holes, 3–128 vertices, at least 100 m², at most
  800 m across, overlapping at least 100 m² of the photo footprints.
- Downloaded elevation is limited to a fixed IGN endpoint, bounded dimensions,
  response size and timeout. Unsupported metadata or absent elevation produces an
  actionable failure. IGN service reference:
  https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/diffusion/wms-raster/

This supports the same workflow for compatible new uploads; it is not an arbitrary
photograph-to-accurate-world reconstruction system. GPS, relative takeoff altitude,
terrain slope, lens distortion, registration error, animal motion and different
capture dates can affect apparent placement. Elevation spacing is not a promise
of cow-position accuracy. National terrain/reference data do not come from the
uploaded photograph itself.

## Jobs, storage and replay

SQLite retains `world_jobs`, batch photos and boundary snapshots. Originals,
predictions, terrain and manifests are stored under `<state>/worlds/<job-id>/`.
One worker runs per state directory, with at most three queued/processing jobs.
A process lock is inherited by the geometry worker so a parent crash cannot start
a competing build while its worker still runs. Startup resumes interrupted jobs;
completed inference and terrain inputs are reused. Failures remain visible and can
be retried. The web page reconnects to saved job progress after refresh.

**Download replay bundle** includes source, both dependency locks, originals,
predictions, measured terrain, cow assets and browser dependencies. It does not
include model weights because offline replay uses the recorded predictions. The
archive contains private original images and GPS metadata; downloading it does
not publish them. Follow its `REPLAY.txt` after extracting to a fresh directory.
Environment installation can require network; replay needs none.

From this workspace, replay a job into a separate directory:

```sh
scripts/terrain/.venv/bin/python scripts/survey/world_pipeline.py \
  --job validation/survey-world-demo/state/worlds/JOB_ID --offline \
  --output /tmp/herdproof-replay
```

Compare the two complete `build-manifest.json` files. Changing the boundary,
pipeline code or model creates a new version; changed locked inputs fail instead
of silently changing an old world. The bundle preserves the original source for
later replay. Cross-platform codec bit identity is not promised.

## What remains for a public deployment

The user journey and processing run locally. This is not a deployed multi-tenant
service. Before exposing it publicly, add account/tenant authorization, private
object storage with upload quotas and retention controls, authenticated job and
asset access, isolated workers, operational monitoring/backups, and deployment
configuration. The loopback server and its page token are not substitutes for
those controls. Production accuracy also needs blind field/camera testing and a
multi-photo correction/approval flow. No farm data or application was published.

## Checks

```sh
scripts/terrain/.venv/bin/python -m unittest discover -s scripts -p 'test_survey*.py' -v
node --check scripts/survey/web/app.js
node --check validation/world-viewer/app.js
node validation/world-viewer/test_world.mjs PATH_TO_BUILD
```

Tests cover upload/metadata limits, polygon geometry, preserved source crops,
model/source binding, empty worlds, failed masks, crowded placements, duplicate
matching, offline replay, tampering, idempotent creation, interrupted-job recovery,
HTTP authorization and private file boundaries. Browser testing uses actual file
uploads and a hand-drawn polygon, then walks the generated scene.

## Verified local example, September 6, 2026

The browser uploaded six original DJI JPEGs and an eight-vertex, 1.71 ha polygon
was drawn across them. Job `d906ecd5af2c22cd78647c17` retained 87 sightings and
rendered 7 usable standing cow observations; exclusions and uncertain placements
remain inspectable. A disk-space failure was recovered through the actual Retry
button after clearing temporary artifacts. The retry reused saved inference and
terrain; its 6.6 seconds is not fresh end-to-end preparation time.

All 42 survey/workflow tests and 10 existing world tests pass. Independent geometry
checks sampled 522 valid locations, with collider/elevation disagreement below
0.000002 m. This checks implementation consistency, not geolocation accuracy.
The actual viewer approached a cow to 2.7 m, displayed its original crop and coat
color, and completed the greeting without browser errors.

The private replay archive was extracted into a fresh directory, verified against
its archive manifest, and rebuilt offline: all 596 output files and the complete
build manifest matched. The temporary extraction was removed after verification
to conserve disk space. Evidence is in `validation/survey-world-demo/`.
