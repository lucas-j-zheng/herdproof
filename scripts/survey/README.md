# Survey application

The **upload → boundary → automatic world** workflow is implemented. See
[WORLD_WORKFLOW.md](WORLD_WORKFLOW.md) for its supported inputs, real model
inference, job/replay behavior and deployment limits. The evidence-checking
workflow below remains available in the same application.

Run from the HerdProof repository root, using the **existing locked terrain runtime**:

```sh
scripts/terrain/.venv/bin/python scripts/serve_survey.py
```

Open <http://127.0.0.1:18776/>. The server binds to loopback only. The counting
lab remains available at `/lab`; the generated world viewer is available from each completed job. This adds no dependencies and does not deploy or publish farm data.

## Agricultural lending context and review summary

The survey page explains the intended agricultural-lending workflow and includes
a live review summary. It shows exact-photo detector candidates or matching-world
displayed observations, declared/EXIF dates, estimated footprints, evidence
conflicts, automatic world merges and pending observation review. Results are
scoped to the selected boundary, photo batch and capture date; stale world or
coverage results cannot supply a different assessment's totals.

The lower page includes the saved two-photo 30-detection / 12-repeat / 18-estimate
example, provisional detector results, separate controlled overlap validation,
the existing paired-cow evidence image and a proposed lender/ranch pilot. The
example is labeled separately from live survey results. `/project-evidence.json`
exports a small recorded snapshot without private filesystem paths or raw media.
Displayed world observations exclude pending and outside-boundary rows and must
not be described as a verified inventory. These additions do not run new training
or alter saved assessments or models.

For the added evidence-scope regression checks:

```sh
node --test scripts/test_review_summary.cjs
```

## Two-minute walkthrough

1. Click **Use example outline** or draw at least three corners on the map.
   Use **Edit and pan** to drag vertices. Save the boundary. The example is an
   illustrative outline, not a surveyed ownership parcel.
2. Click **Use demo photo**. This loads the original, checksum-checked ICAERUS
   image dated September 26, 2023 and sets that declared camera-local date.
3. Click **Check selected photo**. Inspect GPS/date consistency and the individual
   unknown/untested findings. Camera position is displayed as an orange point.
4. Check the same photo again. Exact-byte and decoded-pixel reuse now point to
   the prior retained assessment. Reuse is a review finding, not proof of fraud.
5. Change the capture date, or draw/save a boundary elsewhere, and rerun. The
   corresponding consistency check fails. Old assessments retain the original
   boundary/date snapshot; changing the current form hides stale findings.
6. Export an assessment. **Verify exported JSON** compares it to the saved
   server record. Modifying an exported value fails even if its checksum is
   recomputed. **Verify saved assessment** checks the current displayed report.

Uploads use actual original JPEG/PNG bytes, up to 20 MiB and 32 megapixels.
DJI JPEGs with a primary image plus declared MPF thumbnails are supported;
pixel comparison uses the primary image. Missing metadata stays unknown.
GeoJSON import/export uses a single WGS84 Polygon (longitude, latitude),
without holes, with 3–128 vertices. Invalid/self-crossing boundaries are rejected.
Area is geodesic WGS84; GPS distance uses a parcel-centred metre projection.
Locations within 10 m of the boundary are inconclusive, allowing for uncertainty.

The local reference map is the existing IGN 500 m square orthophoto, with its
EPSG:2154 bounds and file checksum pinned. Pan/zoom, drag editing, numeric vertex
editing, and import work without a map service or API key. Imported boundaries
outside this extent appear over a coordinate grid. A global basemap is not part
of this demo.

## What the integrity checks establish

| Check | Mechanism | Limit |
|---|---|---|
| One-use submission token | 256-bit random token, 15-minute expiry, boundary/date binding, atomic SQLite consume + submission | A submission token does not authenticate camera capture or freshness |
| Exact reuse | Server SHA-256 of original bytes against retained submissions | Local database only; edits change the byte hash |
| Pixel reuse | SHA-256 of dimensions + primary decoded RGB pixels | Catches filename/metadata-only changes; not crops, resizing, or lossy re-encoding |
| Camera GPS | EXIF point-in-polygon and metre distance to boundary | Editable assertions; camera can stand outside the field it photographs |
| Capture date | Original EXIF camera-local date vs declared camera-local date | No timezone invented; EXIF is editable |
| Future timestamp | Explicit EXIF offset compared with server UTC receipt, 5-minute margin; gross future date checked without offset | Without an offset the exact-time comparison stays inconclusive |
| Export integrity | Compare canonical exported content and checksum with the saved server assessment | Not an independent signature; an attacker controlling the database can rewrite local history |

POSTs also require a page token, JSON content type, accepted Host/Origin, and
bounded request size. Serving uses an explicit file allowlist; raw media,
database files, and private source paths are never HTTP assets. Preview copies
strip EXIF. Arbitrary file names are labels, not filesystem paths or HTML.

A retry with the same idempotency key **and identical request** returns the
existing assessment even after token consumption. Changing the retry payload,
reusing a token for another request, expiry, or changing the bound parcel/date
is rejected. Invalid media does not consume a token. Concurrent submissions are
serialized at the check/consume/commit transaction.

The sample photo can display 22 candidates from the existing selected detector
run when its image/model hashes match. Uploads do not silently run a different
detector. The **Build world** path now runs real upload-to-inference processing.
Whole-property coverage, accounts, tenant roles, device attestation, and independent
report signatures remain outside the local application.

## State and validation

State lives in `validation/survey-demo/state/evidence.sqlite3`. It contains
original uploaded media, cleaned previews, immutable boundary snapshots,
submission tokens (hashed), and reports. Preserve it to retain duplicate history.
Use `--state /path/to/a/new/demo-state` for an isolated walkthrough rather than
deleting an existing database. `--port` selects another local port.

```sh
scripts/terrain/.venv/bin/python -m unittest discover -s scripts -p test_survey.py -v
node --check scripts/survey/web/app.js
```

Tests cover real DJI image decoding, malformed images, boundary geometry,
uncertainty edges, concave containment, EXIF consistency, exact/pixel reuse,
expiry and mismatched challenges, concurrent consumption, idempotent retries,
report modification, persistence, HTTP round trips, and origin/host/CSRF/path
boundaries. HTTP tests bind temporary loopback ports.

Application source is included in Git. Generated state, original uploads and
downloaded datasets remain local and ignored. See ../../HACKATHON.md for setup.

## Map-first and photos-first surveys

The start cards now support both orders:

- **Draw on the map**: draw/import and save a farmland boundary, then upload a
  batch. Loading a batch preserves the current boundary.
- **Upload a photo batch**: select up to 24 original JPEG/PNG files. The server
  retains and inspects each file, builds a combined photo layer in the background,
  and fits the map to the survey. Draw and save the farmland across those images.

**Try demo batch** loads six checksum-verified originals from the existing
Jalogny flight archive. **Earlier photo batches** restores images and completed
maps after a page/server restart. The map has separate survey imagery, photo-edge
and boundary layers. Amber shows estimated image coverage; teal shows the user's
farmland boundary. The app never treats the image union as the ownership parcel.

Automatic placement currently supports France, using the existing EPSG:2154 map
coordinates, near-vertical DJI photos with GPS, relative altitude, gimbal heading,
pitch/roll and EXIF 35 mm equivalent focal length. Missing or unsupported metadata
leaves photos explicitly unplaced and available for evidence checks. GPS alone is
not enough to position an image's corners. The IGN reference basemap still covers
only the cached 500 m square; supported uploaded imagery can extend beyond it.

This is an **approximate planar photo map**, not a production orthomosaic:

- Camera rays intersect a flat plane at takeoff elevation. Relative altitude is
  not a measured height above every part of the terrain; lens distortion is not
  corrected by this preview workflow.
- Existing background SIFT/homography checks refine nearby overlapping views.
  A link needs at least 40 inliers, adequate spatial support and low residuals.
  Additional footprint/35 m adjustment limits and a four-link chain limit reject
  implausible placements. Separate groups retain their approximate metadata
  positions, and the UI calls out the need to review their alignment.
- The combined raster selects pixels nearer each source image's centre. It
  preserves uncovered gaps instead of filling a convex hull. Seams, moving cows,
  differing exposure and terrain can remain visible. Do not count animals from
  this mosaic or assume that a visually complete footprint proves a full sweep.
- The saved boundary's overlap percentage is an estimate from the footprint
  union, with overlaps counted once. It is separate from the evidence report's
  unverified whole-property coverage finding.

**Check all photos** runs the existing checks once per original file against the
same saved boundary and declared date. Each photo gets its own immutable report;
reuse is checked against retained submissions, including prior batches. A failed
request can be resumed using the same per-photo token/idempotency key, avoiding
extra assessments for a lost response. Duplicate files within a batch are retained
once. A completed batch is closed to further uploads; create another batch to add
a new survey. Map generation is independent from assessment submission.

The new SQLite tables retain batches, original photo bytes, cleaned previews,
placement metadata and the completed map. A server interruption marks an unfinished
map build for retry. One map is processed at a time; each batch spans at most 5 km
and the output raster's longest side is about 1,800 pixels. No dependencies were
added and the terrain viewer, model training and existing registration module were
not modified.

Run both the original checks and the batch tests:

```sh
scripts/terrain/.venv/bin/python -m unittest discover -s scripts -p 'test_survey*.py' -v
node --check scripts/survey/web/app.js
```

The combined suite has 32 tests. Batch cases exercise camera projection direction
and scale, actual image-feature registration, disconnected transparent gaps,
footprint overlap without double counting, unsupported metadata, upload retries
and batch limits, persistence, original-byte assessments and HTTP access controls.
The world builder now has a durable local SQLite job queue and automatic elevation
acquisition. A global basemap, general camera/georeferenced-raster ingestion,
terrain-corrected photogrammetry and production authentication remain future work.

### Adding boundary vertices

In **Edit and pan**, the small **+** handles on longer boundary edges insert a
vertex at that edge's midpoint. Click a handle, or drag it straight to a bend.
**Add vertices** inserts intermediate control points around the existing outline
(up to the existing 128-vertex limit). Insertion preserves the outline until a
point is moved; extra vertices alone do not improve placement accuracy.
**Undo** restores the previous geometry for insertions, drags, coordinate edits,
removals and clearing. The current edit history keeps up to 50 geometry changes
and resets when a saved boundary is loaded. Keyboard users can focus an edge's
handle and press Enter or Space; Ctrl/Cmd+Z undoes while the map has focus.

Validated in the browser: the eight-point example expands to 16, an edge insert
creates a seventeenth point, and Undo restores the 16-point outline. JavaScript
syntax validation passed, with no browser warnings or errors during those checks.
