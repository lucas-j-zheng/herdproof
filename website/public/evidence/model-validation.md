# HerdProof: current detector evidence

Recorded September 6, 2026. Source: the project's MODEL_DEFAULT.md.

## Selected operating point

Corrected full YOLOv8n v2, confidence 0.70, global non-maximum suppression IoU 0.50.
Native image tiling: 1024 × 1024 pixels with 20% overlap.

| Metric | Result |
| --- | ---: |
| Precision | 81.92% |
| Recall | 77.91% |
| F1 | 79.86% |
| Mean absolute count error | 3.03 cows/image |

77 images with 1,041 provisional cow annotations; 811 matched observations,
990 detections, 179 unmatched detections and 230 misses.

## Interpretation

This was an exploratory threshold comparison on an already inspected public test
benchmark. It is not fresh blind validation. The source labels are incomplete in
some images, so these results measure provisional agreement with annotations,
not independently verified cattle accuracy. Independent reference labeling and
unseen-farm validation remain necessary.

Precision and recall here are detector results. The separate 192-case overlap
suite uses supplied boxes and is not an assessment of detector accuracy.

## Actual two-photo integration run

On September 6, 2026, the selected detector processed two original survey photos
from November 7, 2023. The pipeline produced 30 detections, removed 12 repeated
sightings, and proposed 18 distinct tracks, including one unresolved clipped
sighting. The run status was needs_edge_recapture. Property coverage was not
verified, and the total was not a verified 18-cow ground-truth count.

The example JSON on this site is a sanitized copy of that run's result, with
local machine paths omitted and explanatory context added.

## Scope

The prototype concerns distinct observed animals. It does not establish herd
ownership, complete property coverage, authenticated capture, loan eligibility,
or lender acceptance. No human time-saving claim has been established.

Imagery: Louise Helary and Adrien Lebreton / Institut de l'Elevage, ICAERUS
grazing-cow v2, CC BY 4.0, https://doi.org/10.5281/zenodo.11048412.
