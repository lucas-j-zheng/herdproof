# Overlapping-photo counting prototype

This local pipeline registers nearby aerial photographs and proposes which cow
observations refer to the same animal. It uses the current environment and existing
detector outputs; it does not train a model or connect to a drone.

```
Original photos + timestamps/GPS + existing detection boxes
  -> nearby same-flight, same-date candidate pairs
  -> static-background feature matching (cow boxes masked)
  -> validated image-to-image homography and overlap
  -> clip projected cow boxes to the area visible in BOTH photos
  -> compare shared visible portions + position + size + colour
  -> conservative, one-to-one matching; ambiguous matches withheld
  -> tracks containing at most one detection per photograph
  -> one count per track; choose the clearest existing view
  -> keep unresolved clipped sightings as explicit recapture targets
```

Run from the repository root:

```sh
# Check whether existing annotations can be associated across photographs.
.venv/bin/python scripts/aerial_survey.py --labels --output validation/overlap/all-labels

# Feed saved model detections through the same pipeline, with the saved threshold.
.venv/bin/python scripts/aerial_survey.py --run validation/runs/finetuned --skip-missing-predictions --output validation/overlap/all-model

# Small reproducible example: three annotated views of a 12-cow group.
.venv/bin/python scripts/aerial_survey.py --labels --flight Mauron/DJI_202311071416_061 --output validation/overlap/mauron-labels

.venv/bin/python -m unittest discover -s scripts -p 'test_aerial_survey*.py' -v
```

Inputs follow `validation/data/manifest.json`: each record has `id`, `image`,
`image_sha256`, `flight`, and normalized `boxes` (`x1,y1,x2,y2`). Original JPEGs
must retain EXIF GPS and capture time. Annotation boxes are read only in explicit
`--labels` mode. In `--run` mode the script reads `report.json`'s `selection`, then
each `<id>.json` file's matching `modes` entry and confidence scores. Missing or
mismatched predictions fail instead of falling back to annotations. Images are
SHA256 checked; invalid metadata is recorded in `quarantined` and excluded.
The existing saved model run covers 97 of the 127 photos. The explicit
`--skip-missing-predictions` option above excludes the 30 missing files and records
each exclusion. Omit that option to require predictions for every selected photo.

Output `report.json` includes configuration and source hashes, per-pair homographies,
registration quality, matches, ambiguous associations, per-flight tracks, and edge
hints. Evidence JPEGs show annotated full frames plus original-resolution matched
croppings. Detection indices are zero-based; displayed M1, M2, etc. are local to
each image pair, not persistent animal IDs. `overlap_fraction` is intersection area
divided by the smaller of the two footprints in the target image coordinate system.

The default candidate limits are 30 seconds and 160 metres. Registration requires
at least 40 background inliers, distributed spatial support and at least 12% overlap.
These are initial engineering thresholds, not parameters calibrated on identity
ground truth. Rejected registrations retain separate observations. Associations
allow small motion but do not use a learned appearance or motion model.

Clipped boxes are compared after intersection with the shared camera footprint.
The full cow's centre may be outside the other photo; this no longer disqualifies
its visible head or tail. Convex clipping is implemented locally in float64 and
handles coincident frame boundaries. Tiny shared fragments (under 4 square pixels
or 1.5 pixels in either span at working resolution) remain unmatched. Edge matches
also require shared-region IoU of at least 0.15, size consistency and a clear margin
over competing identities. The script never invents the missing portion of a cow.

## What the current data establishes

A run on all 127 local ICAERUS photographs across 25 flight groups found 96 nearby
candidate pairs and 49 pairs passing background registration. Of those, 29 have
nonempty cow labels in both photographs. The Mauron example links 36 annotated
observations from three photos into 12 proposed tracks; six photos are selected
in that flight, but three have empty annotation lists. Empty annotation files must
not be interpreted as verified empty pastures.

The data has boxes within each image, but no persistent animal identity labels
between images. This can establish overlap and exercise duplicate removal; it
cannot measure identity association accuracy or verify a true unique herd total.
Use a separately held-out set of short sequences with cross-photo IDs and known
survey counts to evaluate this layer before relying on its totals. That is an
offline validation task, not a requirement for customers to correct every upload.

Sparse selected photographs also do not establish complete property coverage.
Unmatched observations can include repeat sightings, and incorrect merges can
undercount. Different flights/dates are never associated. Do not add the output
counts across different surveys to estimate one herd's population. Full-property
counting still needs a coverage plan, property polygon, adequate visibility, and
validation of movement and detection errors.

## Edge-cow idea

`edge_recapture_hints` reports detections within 5% of an image edge. This is a
useful signal for an extra look at a partially seen animal. It is expressed in
image coordinates; converting it into a flight adjustment needs camera attitude,
a world-coordinate transform and a coverage planner. Following edge cows alone
can miss isolated cattle and revisit the same animals. Use a systematic property
sweep as the main route and recapture hints as secondary inputs. This prototype
has no flight-control or SDK commands.

Deduplication happens after capture. No adaptive drone flight is needed for the
ordinary case: upload overlapping photos, align them, and merge repeated cow
sightings. `preferred_observations` selects a view for each track. If a box is
clipped (within 0.1% of an image boundary) but the same track already has a full
view, its edge event becomes `resolved_in_another_photo`. Otherwise the track
appears in `recapture_targets`, including a reference photo, image point and edge.
It is retained in the estimate, and `count_status` is `needs_edge_recapture`.
The pending status does not establish that the sighting is a new animal; it
preserves uncertainty instead of dropping it or silently accepting a final count.

## Edge validation

```sh
# 96 deterministic cases from six original images; identity comes from source
# annotation indices, independently of what the matcher returns.
.venv/bin/python scripts/evaluate_overlap_edges.py --output validation/overlap/edge-validation/current

# Separate set from six additional flights, evaluated without threshold changes.
.venv/bin/python scripts/evaluate_overlap_edges.py --sources 007c40f9ae66 072e18aac984 29311e2ce426 29f7ef7c8fe3 2e82386f12bf 39a97e3d63d0 --output validation/overlap/edge-validation/holdout

.venv/bin/python scripts/aerial_survey.py --labels --output validation/overlap/edge-validation/real-flights --evidence-pairs 0
```

The controlled benchmark derives overlapping crops from real drone photographs
and clips every annotation to each crop. Background registration runs on those
image pixels; the true transform and identities are not given to the matcher.
It tests 20%, 50% and 80% visibility at each edge and all four corners. All visible
annotations, including nearby distractors, contribute to the exact match and count checks.

Before the fix, the first 96 cases produced 22 exact counts and missed 128 of 836
duplicate links. After the fix, all 96 cases and all 836 links pass with no false
links. The separate 96-case set passes all 457 links: 192 exact cases and 1,293
correct links combined. Unit tests additionally exercise camera rotation, scale,
small movement, ambiguous neighbors, subpixel slivers, and three-photo tracks.

The 127-photo original-flight run finds six shared-edge associations, resolves six
clipped observations with another existing view and retains 20 unresolved clipped
tracks. Some have no nearby photograph or an empty counterpart annotation file.
Two visually inspected links in separate real exposures are regression-tested.

These are geometry and edge-behavior results with supplied boxes, not YOLO accuracy
or a whole-property field trial. Controlled crops contain stationary animals;
large animal movements and long gaps still require further validation.

This script and its local outputs follow the existing ignored `scripts/` and
`validation/` workflow. No active training code or dependencies were changed.
