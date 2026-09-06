# Post-capture cow overlap and edge validation

Implementation: `scripts/aerial_survey.py`, written locally. No external cattle
counting implementation was downloaded or imported. Existing OpenCV, NumPy,
SciPy and Pillow primitives are used; no dependencies or YOLO models were changed.

| Evidence | Result |
| --- | --- |
| Original code, controlled crop suite | 22/96 exact cases; 128 missed links |
| Fixed code, same crop suite | 96/96 exact cases; 836/836 links; zero wrong links |
| Separate six-flight crop suite | 96/96 exact cases; 457/457 links; zero wrong links |
| Unit and original-photo regression tests | 30 tests pass |
| Original 127-photo run | 49 registered overlaps; six edge associations |
| Original-photo edge outcomes | Six clipped sightings resolved; 20 tracks retained for recapture |

The bug was comparing complete and clipped box centres/sizes. The fix compares
both observations only within their shared image footprint. A numerical failure
in nearly collinear boundary intersection was also reproduced and replaced with
local float64 convex clipping. Each accepted track contributes one count, and
cannot contain two detections from the same photograph. A clearer existing view
resolves a clipped sighting; otherwise the edge remains explicit and pending.

The controlled suites run background registration on image pixels. Source
annotation indices provide independent identity truth. They test all four edges
at 20%, 50% and 80% visibility and all four corners, including other annotated
cows in each crop. Additional tests cover camera rotation and scale, small motion,
new cows outside the overlap, ambiguous neighbors, tiny fragments, conflicting
associations, and a three-photo clipped/full/clipped sequence counted once.

The original-photo regression test checks two visually inspected cow links across
separate exposures. `real-edge-matches.jpg` shows all six proposed edge links for
inspection. Remaining clipped tracks can lack a nearby image, lack annotations
in the counterpart, or lack a reliable match. They are not silently discarded.

Reports and provenance: `baseline/report.json`, `current/report.json`,
`holdout/report.json`, and `real-flights/report.json`. The latter two were checked
against the current implementation hash. Every original-flight track was checked
for count conservation, one observation per photo, and consistent recapture state.

These results establish tested post-capture overlap and edge handling with supplied
boxes. They do not establish YOLO accuracy, completeness of the sparse property
survey, or arbitrary moving-cow identity accuracy. No drone control is required
for ordinary deduplication, and no flight commands are issued by this code.
