# Alternative Dataset and Gate-Counting Research

> Historical dataset research. Data observations are retained; current product
> claims, capture scope, and evaluation gates are defined in [PLAN.md](PLAN.md)
> and [FEASIBILITY.md](FEASIBILITY.md), revised 2026-09-05.

## Recommended data stack

No single public dataset safely supports every HerdProof claim. The strongest
combination is:

1. **ICAERUS grazing-cow v2** for permissively licensed, real-drone cattle
   detector training;
2. **New Zealand Cattle Detection** for dense-herd point-count supervision and
   stress testing;
3. **Uruguay Cattle MOT** for permissively licensed cattle video, count labels,
   and a manually corrected tracking sequence;
4. **CattleEyeView**, only after accepting its terms or receiving explicit
   permission, for fixed-gate tracking and line-count evaluation;
5. **first-party gate footage** for the final demo and product claim.

WAID can supplement training after cleaning, but should not be the validation
benchmark.

## Search method

The search covered Zenodo and DataCite dataset records, Mendeley Data, Bristol's
research-data catalogue, GitHub repositories/releases, Hugging Face, Kaggle,
OpenAlex scholarly records, primary papers, and the 2024 systematic survey
[*Public Computer Vision Datasets for Precision Livestock Farming*](https://arxiv.org/abs/2406.10628) (which lists
27 public cattle datasets). Candidates were checked against primary metadata,
not accepted solely from a mirror's license badge. Shortlisted archives were
checksum-verified and inspected without running publisher code.

Screening dimensions were capture geometry, continuous video availability,
box/point/track/count ground truth, farm/flight grouping, source provenance,
license scope, archive integrity, annotation consistency, split leakage, and
whether the data could test the final claim rather than only train a detector.

## Candidate assessment

### ICAERUS: Drone images and annotations of grazing cows, v2

- Source: Institut de l'Elevage / EU H2020 ICAERUS project
- DOI: <https://doi.org/10.5281/zenodo.11048412>
- License recorded by Zenodo: CC BY 4.0
- Published description: 1,385 nadir RGB images and 4,941 boxes
- Capture: DJI Mavic 3 Enterprise/Thermal, 60 m or 100 m
- Organization: four farms, with images grouped by named flight
- Labels: YOLO for all images and Pascal VOC for only part of the archive; all
  16 class-definition files declare two classes, `cow` and `calf`
- Archive: 16,586,848,207 bytes; Zenodo MD5
  `c18911fb11cb58741b9cfa16516ca8cd`
- Structural audit: all 1,385 JPEGs and 1,385 YOLO label files parsed, but they
  contain **4,747** valid boxes, not 4,941. There are 366 positive and 1,019
  negative images across 25 flights and four farm groups. Median box size is
  approximately 59×58 pixels; the 10th percentile is approximately 30×29;
  maximum image count is 90. No exact duplicate JPEGs were found.
- Layout defects: 461 YOLO files are stored under incorrectly named flight
  directories and must be paired to images by farm plus exact image stem. Only
  1,079 Pascal files exist, leaving 306 images without that advertised format.
  One paired Pascal/YOLO image has a box-count mismatch.
- Class defects: four class files say only `cow`, while twelve say `cow, calf`;
  nevertheless, every YOLO box uses class 0. Pascal contains 2,665 `cow`, one
  `red_squirrel`, and one `unknown`. Crop review shows both exceptional objects
  are small non-cattle/ambiguous targets: the squirrel is omitted from YOLO, but
  the `unknown` is apparently mapped into YOLO class 0. Exclude that image from
  a clean manifest. There is **no usable calf class** in the released YOLO
  labels.
- Visual audit: reviewed random, dense, empty, and smallest-box samples. Cow
  boxes generally align well across varied fields, farms, lighting, and camera
  rotations. Dense examples are consecutive, highly overlapping views of the
  same approximately 90-head herd, so all frames from a flight must remain in
  one split. Tiny and tree-shadow cases still need targeted review.
- Verdict: **best primary aerial detector source found, after manifest-based
  repair**. Use the YOLO labels as a one-class `cattle` pool, ignore the broken
  calf declaration, and build splits exclusively by image-side flight.

### New Zealand Cattle Detection

- DOI: <https://doi.org/10.5281/zenodo.5908869>
- License recorded by Zenodo: CC BY 4.0
- Underlying imagery: LINZ Data Service, identified as CC BY 4.0
- Data: 655 500×500 RGB tiles at 0.1 m/pixel; 29,803 cattle point lines
- Archive: 273,621,406 bytes; Zenodo MD5
  `da6d596c3a9a0ca7a220c604b5c85580`
- Audit: all images decoded at 500×500 and all point lines were in bounds;
  counts range from 1 to 257 with median 35. Visual samples show generally good
  point alignment even in dense groups.
- Audit defects: 14 point lines duplicate another coordinate in the same label
  file. Visual review confirmed that these are duplicate annotations on one
  animal, not two animals sharing a center. Also, 322 filenames are explicitly
  marked `_shifted` and visually overlap source scenes, so the 655 tiles are not
  655 independent locations.
- Verdict: **strong dense-count supplement**, not drop-in YOLO detection data.
  Deduplicate point coordinates and group original/shifted/spatially overlapping
  tiles before splitting. Point labels can train a density/point model or
  provide weak boxes, but box size must not be invented without validation.
  Orthophotos also differ from moving-drone video geometry.

### Counting cattle: Supporting Livestock Multi Object Tracking

- DOI: <https://doi.org/10.17632/dk54zg67dd.1>
- Source: Universidad Tecnológica del Uruguay / Estancia La Cordillera
- License: CC BY 4.0 in both Mendeley and DataCite metadata
- Data: 10 unique videos, approximately 3.26 minutes by decoded duration, and
  a stated total of 93 Brangus cattle
- Capture: conventional phone cameras at 30 fps on a ranch in northeastern
  Uruguay, across locations, seasons, lighting, and backgrounds
- Count ground truth: each counting video provides duration, resolution, and
  animal count
- MOT ground truth as documented: one 1920×1080, 478-frame sequence with 1,774
  manually reviewed box rows and persistent IDs for eight animals
- Archive: 275,216,868 bytes; published SHA-256
  `1fcb101ac83eb917f492e00f10b8b67d912fbb1bc881e40b11713a078868e01b`
- Annotation provenance: initial COCO-YOLOv8 detections and DeepSORT IDs were
  manually corrected frame-by-frame, including missing animals and ID switches
- Structural audit: all 11 packaged MP4s decoded, with `Toros.mp4` duplicated in
  the video and ground-truth directories, leaving 10 unique videos. The MOT file
  actually has 479 frames, 1,775 rows, and nine IDs—not the documented
  478/1,774/eight. All frames have labels, but 206 boxes extend beyond an image
  boundary and must be clipped during conversion. Detector confidence values
  remain in the ground truth and should not be interpreted as annotation
  confidence.
- Visual audit: boxes generally align well. The clips show lateral, mostly fixed
  phone views of red/black cattle moving past a camera in fields, pens, and a
  road; they include touching cattle, fence-wire occlusion, hard shadows, and
  several resolutions. This is useful line-crossing geometry even though it is
  not an overhead gate. One clip visibly contains a social-media watermark, so
  its source rights should be clarified despite the dataset-level CC license.
- Oracle crossing check: seven annotated IDs cross the frame midpoint, but only
  six complete a conservative right-entry to left-exit traversal; three IDs
  enter from the right without reaching the opposite terminal zone before their
  annotations end. This is concrete evidence that “animals seen,” raw line
  crossings, and completed passages are different quantities.
- Verdict: **best permissively licensed cattle tracking/count source found, with
  documented cleanup needs**. The archive does not include a machine-readable
  per-video table of the stated 93 counts, so independently count each selected
  clip before evaluation.

### ICAERUS passing-sheep crossing videos

- DOI: <https://doi.org/10.5281/zenodo.12094356>
- License: CC BY 4.0
- Data: four low-altitude drone videos, 639 frames (61 seconds total at 9 fps),
  and 14,365 sheep boxes
- Labels: YOLO labels for every frame plus MOT-format boxes and track IDs
- Scenario: animals passing through a fenced corridor for counting
- Archive: 157,760,285 bytes; Zenodo MD5
  `1ec2048d4975f5d68e04c3229cb03d40`
- Visual audit: the view is near-overhead and sufficiently stable, but animals
  frequently travel several abreast and touch/occlude one another; a dog and a
  human also enter some frames. This is a stronger crowding/distractor test than
  an ideal single-file gate.
- Verdict: useful for testing event-state logic, occlusion handling, reversals,
  and throughput. It is **not evidence of cattle detector accuracy** and must be
  reported only as a cross-species algorithm stress test.

### CattleEyeView

- Paper/repository: <https://github.com/AnimalEyeQ/CattleEyeView>
- Paper: <https://arxiv.org/abs/2312.08764>
- Data: 14 fixed-overhead loading-ramp videos, 30,703 frames, and 753 cattle
  instances across six breeds
- Capture: outdoor loading ramp, fixed RGB CCTV approximately 3.7 m overhead,
  collected over four months
- Ground truth: body/head boxes, track IDs, passage counts, keypoints, and
  instance masks
- Domain fit: **the closest published dataset to HerdProof's gate-counting
  design**
- Access: requires a Google form and acceptance of separate dataset terms
- Dataset terms found in the form: non-commercial research/education only; no
  redistribution; no derivative dataset without consent; imagery may only be
  shown in academic publications or presentations
- Important result: the paper reports counting MAE 20.5 for BoT-SORT and 24.0
  for ByteTrack on videos averaging about 58 cattle. It attributes substantial
  error to cattle moving back and forth across the line.
- Verdict: **best scientific benchmark, but not cleared for this demo by
  default**. Lucas must personally review/accept the terms, and explicit written
  permission is preferable for a hackathon or product-oriented presentation.

### Cows2021

- DOI: <https://doi.org/10.5523/bris.4vnrca7qw1642qlwxjadp87h7>
- License: Non-Commercial Government Licence v2
- Data: 10,402 annotated still images and 301 RGB videos
- Video capture: fixed Intel D435 approximately 4 m above the walkway between
  the milking parlour and holding pens
- Video duration: approximately 5.5 seconds at 30 fps
- Herd: 186 Holstein-Friesian cattle
- Video characteristics: average 1.45 tracklets per clip; 301 clips total,
  approximately 13.96 GB
- Bounded audit: 16 sequences sampled across all four collection days decoded
  successfully as 1280×720, 30 fps MJPEG (2,529 frames / 84.3 seconds).
- Visual audit: the camera is genuinely fixed and overhead. Clips include wet
  floor glare, partial cattle at frame edges, heavy overlap, temporary empty
  scenes, and up to several animals moving in different directions. The scene
  is more like a holding/walkway area than a guaranteed single-file crossing.
- Verdict: **useful for overhead detector adaptation and tracking stress**, but
  clips are short and average only 1.45 tracklets. It has no passage-count ground
  truth and is not a dense gate-count benchmark. Its non-commercial license
  makes it unsuitable for an unrestricted product artifact.

### OpenCows2020

- DOI: <https://doi.org/10.5523/bris.10m32xl88x2b61zlkkgz3fml17>
- License: Non-Commercial Government Licence v2
- Original detection data: 3,703 top-view indoor/outdoor frames with 6,917
  cattle instances; the archive expands to 7,043 images using synthetic data
- Labels: YOLO and Pascal VOC
- Verdict: useful fixed-overhead detector pretraining for research, but it does
  not provide a continuous multi-animal crossing benchmark. Keep originals and
  synthetic images distinguishable.

### AutoCattlogger / Purdue VADL

- Repository: <https://github.com/VADL-Purdue/AutoCattlogger>
- Provides top-view passageway sample-video instructions and 494 detector
  training/test images
- Repository code license: Apache 2.0
- Data terms: the data README requests citation but does not clearly state a
  separate data license
- Current access: all four documented Box download links returned HTTP 404
- Verdict: relevant provenance, but **not currently usable** until the authors
  restore access and clarify dataset licensing.

### Other rejected or secondary candidates

- **Aerial-livestock-dataset**: 89 large images and 4,996 boxes, but its GitHub
  release has no dataset license.
- **Soares cattle-counting data**: 5,058 aerial images from six Brazilian farm
  areas and good flight grouping, but the repository provides Google Drive
  links without an explicit dataset license.
- **Barbedo dense UAV data**: the paper reports a second set with images
  containing more than 100 cattle and calves, but no public dataset download or
  separate data license was located.
- **ICAERUS raw v1**: approximately 900 images with no labels; superseded for
  this purpose by the annotated v2 release.
- **Random Hugging Face/Roboflow/Kaggle mirrors**: several claim permissive
  licenses while filenames reveal stock-photo sources (including
  Depositphotos), omit provenance, or appear to repackage WAID. These are not
  suitable for a due-diligent model.
- **Commercial $89 GitHub listing**: no provenance or license and only preview
  files; rejected.
- **MOUNT-Cattle**: ground-level mounting/pose data rather than aerial or gate
  counting; its card claims MIT while its README still says to specify the
  license; rejected for this task.
- **MooTrack360**: a substantial top-down fisheye barn dataset with 1,500
  annotated images, 102,747 cow instances, and a one-hour annotated tracking
  video. It is CC BY-NC-SA 4.0, the core video is about 18.9 GB, and its open-barn
  occupancy geometry is less relevant than a constrained crossing. Keep it as a
  future research benchmark, not a nine-hour demo dependency.
- **CVB cattle behavior videos**: 502 outdoor 15-second clips under CC BY-NC-SA
  4.0. Useful for behavior research, but no gate-count ground truth and a weaker
  geometry match than the Uruguay and CattleEyeView data.
- **Community “AI-Based Cow Detection System”**: its README advertises
  directional line counting, but review of the current `main.py` found no line
  crossing state or `LineZone`; it reports unique tracker IDs and polygon
  occupancy instead. It is not validation evidence and should not be copied
  without independent tests.

## Implementation-license note

- Ultralytics' public repository is AGPL-3.0. That can be workable for a fully
  open hackathon artifact, but a closed commercial service needs a separate
  license or a different detector implementation.
- YOLOX is Apache-2.0; ByteTrack, BoT-SORT, and Roboflow Supervision currently
  advertise MIT licenses. This is a cleaner permissive stack, subject to the
  licenses of any pretrained weights and training data.
- Dataset and software licenses are separate. An Apache/MIT repository license
  does not automatically clear remotely linked videos, model weights, or stock
  imagery.

## Data-handling and attribution

- Keep raw datasets and EXIF outside the repository. ICAERUS images contain
  detailed drone metadata, and New Zealand filenames contain coordinates.
- Do not expose source coordinates, farm names, or unredacted EXIF in the demo,
  logs, screenshots, or generated report.
- For CC BY sources, retain creator, title, version/date, DOI, license URL, and a
  description of filtering/relabeling. Put the attribution in the model card and
  demo credits, not only in developer notes.
- Record checksums of source archives and every derived manifest. Never claim a
  dataset-level license clears separately identified third-party material.
- Do not commit imagery or restricted datasets. CattleEyeView specifically
  prohibits redistribution, and the Bristol datasets are non-commercial.

## Gate or alley counting design

A fixed camera removes camera-motion ambiguity, but a naïve virtual line is not
sufficient. CattleEyeView demonstrates that backtracking can make ordinary
tracker-based counts fail badly.

### Physical capture protocol

- Mount the camera rigidly, preferably near-nadir, with the full approach and
  departure zones visible.
- Use a one-animal-wide, operationally one-way race or alley where practical.
- Keep the count boundary away from frame edges, gates, sharp shadows, and
  locations where animals stop or turn.
- Record before the first animal enters and until the passage is visibly empty.
- Avoid jump cuts, variable playback, zoom, and camera movement.
- Capture enough resolution and shutter speed to avoid merged silhouettes and
  motion blur.
- If animals can move both directions, report separate `IN` and `OUT` events;
  never call raw crossing events a unique-animal count.

### Counting state machine

Use three spatial zones rather than a single-line trigger:

```text
ENTRY  ->  HYSTERESIS BAND  ->  EXIT     = one IN event
EXIT   ->  HYSTERESIS BAND  ->  ENTRY    = one OUT event
ENTRY  ->  BAND -> ENTRY                  = no event
EXIT   ->  BAND -> EXIT                   = no event
```

For each tracker ID:

1. require several consecutive detections in the starting zone;
2. retain history through a bounded detector dropout;
3. count only after the track reaches the opposite terminal zone;
4. emit at most one event for that completed traversal;
5. classify a track lost inside the band as `UNCERTAIN`, not as a count;
6. preserve the event frame, direction, trajectory, detector scores, and
   bounding boxes for review.

This is more robust than counting unique tracker IDs or every geometric line
intersection. It does not solve an ID switch inside the band; those events need
re-association or manual review.

### Evaluation protocol

Evaluate the count system directly, not just detector mAP. Separate failures in
three stages:

1. run the zone state machine on ground-truth track IDs and boxes (“oracle
   tracks”) to verify count semantics and zone placement;
2. run the tracker on ground-truth boxes to measure association/ID-switch error
   independently of detection;
3. run detector plus tracker to measure end-to-end count error.

Then:

- manually label the crossing frame and direction for every animal;
- use two reviewers for a subset and reconcile disagreements;
- report exact `IN`, `OUT`, net count, false events, missed events, and uncertain
  events;
- test normal flow, stopping on the boundary, reversing, two animals touching,
  detector dropout, partial entry, human occlusion, low light, and video restart;
- split training and evaluation by day/location/sequence, never by adjacent
  frame;
- require the final ranch/demo footage to be held out from training.

A sensible demo target is zero errors on the selected prerecorded clip, while
showing any uncertain event for human confirmation. That is a demo acceptance
criterion, not a claim of production accuracy.

## Recommended HerdProof evidence flow

1. Use a short drone or phone establishing shot to show the parcel and current
   challenge token. Do not derive the cattle count from unrestricted drone
   tracking.
2. Use an uninterrupted fixed-gate clip for directional passage counting.
3. Show the event ledger and allow manual correction of uncertain crossings.
4. Hash both original files and bind their hashes, the challenge, parcel ID,
   count events, and operator attestations into the signed report.
5. State explicitly that GPS/time metadata are editable assertions and that the
   operator must establish that the whole claimed herd passed through the gate.

The remaining systemic risk is procedural: a perfect gate counter only proves
how many passages were filmed. It does not prove that every collateral animal
was presented exactly once unless the physical handling protocol enforces that.
