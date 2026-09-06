> HISTORICAL SNAPSHOT — superseded on 2026-09-05. Contains withdrawn claims.
> Follow the current root PLAN.md, FEASIBILITY.md, and RESEARCH_2026-09-05.md.

# HerdProof demo feasibility and red-team review

**Review date:** 2026-09-02
**Scope:** the two-scenario collateral-verification demo only

## Verdict

**GO for a tightly staged hackathon demo, with conditions.**

The records, valuation, challenge lookup, QR decoding, geofence, hashing, UI,
and PDF portions are straightforward. A fixed-camera **gate crossing** can make
counting credible enough for a demo if the footage is secured and manually
labeled before development starts.

**NO-GO in nine hours for any of these stronger claims:**

- exact or statistically defensible counting of an arbitrary 250-head drone pass
  with stock COCO YOLOv8 weights;
- automatic cow/calf/bull classification from COCO (COCO has only `cow`);
- trustworthy capture provenance from editable MP4 GPS/timestamp metadata;
- a production lending or appraisal decision.

The honest demo claim is: **“automated provenance checks and a calibrated visual
inventory estimate produce an auditable collateral-review packet.”** It must not
claim that ordinary video metadata proves where or when a video was captured.

## What was actually tested

Tests were run locally on 2026-09-02 with Ultralytics 8.3.200, YOLOv8n COCO
weights, OpenCV, FFmpeg 7.1.5, and Shapely 2.1.2.

| Test | Result | Consequence |
|---|---|---|
| Generate a QR, place it in initial video frames, decode frame 1 with `QRCodeDetector` | Pass | Mechanically feasible; keep QR large and on screen for 1–2 seconds. |
| Write/read QuickTime `creation_time` and ISO-6709 `location` tags with FFmpeg/ffprobe | Pass | ffprobe is sufficient for a controlled fixture. Actual phone/drone files still need device testing. |
| SHA-256 the uploaded file and test point-in-polygon with Shapely | Pass | Hash the original bytes before any transcoding. Use `covers`, not `contains`, at parcel boundaries. |
| Transcode while stripping metadata | GPS and timestamp disappeared while QR remained readable | Missing metadata must be `INCONCLUSIVE` or `FAIL`, never silently accepted. Social/video platforms commonly destroy this evidence. |
| YOLOv8n on a 100.48-second CC aerial clip with roughly 20–25 visible cattle | Best sampled frame: 26 detections at confidence 0.10, 20 at 0.25, 17 at 0.50 | The apparent count is highly threshold-dependent. Model confidence is not a count confidence interval. |
| Track every fifth frame from seconds 10–55 of that moving-drone clip | 51 unique ByteTrack IDs and 72 unique BoT-SORT IDs for a herd of roughly 20–25 | Unique track IDs drastically overcount because tracks fragment. Do not use this algorithm for a free-moving drone census. |
| YOLOv8n on a CC feedlot clip visibly containing hundreds of cattle | At second 20: 63 detections at 0.10, 33 at 0.25, 9 at 0.50; many other sampled views had fewer than 15 | Stock COCO weights cannot support the stated 250-head drone demo. Distant/small/occluded cattle are missed. |
| Runtime smoke test | 101 frames at 1280 inference size took 11.4 seconds; two 226-frame tracking passes took 55.4 seconds total on the test Mac | A precomputed demo is comfortable. Upload-time processing of a short sampled clip is plausible, but must have a progress UI and cached fallback. |

The Ultralytics tracker attempted to install `lap` automatically on first use.
Dependencies and model weights therefore need to be installed, pinned, and cached
before demo day. The exact tested YOLOv8n weights had SHA-256:

```text
f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36
```

## The demo that is actually buildable

### Choose one count geometry

#### Recommended: fixed gate camera

- Camera is fixed; cattle move through one narrow lane in one direction.
- Detect one `cattle` class, but use an `ENTRY -> BAND -> EXIT` state machine
  rather than counting every geometric line intersection.
- Count only a completed traversal into the opposite terminal zone. Treat
  `ENTRY -> BAND -> ENTRY` as a reversal with no count; retain separate `IN` and
  `OUT` ledgers if two-way movement is allowed.
- Remember completed tracker IDs, tolerate only bounded dropouts, and classify a
  track lost inside the band as `UNCERTAIN` rather than guessing.
- Flag reverse movement, prolonged occlusion, ID switches, and simultaneous
  crossings for manual review.
- Sample every third frame only after confirming that a fast animal remains
  visible in enough sampled frames to establish a track. Do not blindly skip
  five frames.
- Pre-label the entire demo clip by hand. The demo cannot be evaluated without
  ground truth.

ByteTrack is reasonable here because the camera is fixed and the line prevents
“number of all IDs ever seen” from becoming the count. This is materially easier
than a drone pass.

#### Fallback: drone visual census estimate

If no gate clip exists, change the UI wording from “tracking count” to **“visual
census estimate.”** Select one or a few frames in which the whole pledged herd is
visible, tile the high-resolution image with overlap, detect cattle, and merge
boxes with NMS. Do not sum frames and do not count unique tracker IDs. Add a manual
correction step.

A custom aerial-cattle detector is still required for dense or distant herds.
The stock COCO test missed most animals in the 250+ head feedlot footage.

### Do not infer animal class from COCO

COCO class 19 is `cow`; it does not distinguish cows, calves, steers, heifers, or
bulls. For this demo:

1. computer vision produces a total cattle estimate;
2. records provide the expected class composition;
3. the report explicitly says class composition is record-derived, not
   vision-derived;
4. valuation uses a conservative head count (normally the lower end of the
   visual range) and documented allocation policy.

Building a three-class model is out of scope unless labeled, view-matched data and
a trained checkpoint already exist.

## A defensible “confidence range” for the demo

Raw YOLO confidence scores are not a confidence interval for herd size. Tracking
errors are correlated across frames, so a binomial formula is also inappropriate.

For the hackathon, report an **uncertainty band**, not a “95% confidence
interval”:

- lower bound: high-confidence, stable, direction-valid line crossings;
- upper bound: lower-confidence candidate crossings after duplicate suppression;
- point estimate: reviewed threshold selected on held-out labeled footage.

Label it `algorithmic uncertainty range`. To call it a calibrated confidence
interval later, hand-label representative clips from every supported capture
geometry and estimate interval coverage on a held-out test set.

**Pre-build kill criterion:** on the exact demo clip, the chosen count method must
put the manual ground truth inside its range and keep point error at or below 5%.
If it does not, do not show a live model result; use another clip or change the
claim.

## Provenance design and limits

### Challenge record

Use an opaque 128-bit random challenge, rendered as a short QR payload such as
`HP1:<base32 nonce>`. Store only its hash in SQLite with:

```text
challenge_id, nonce_hash, loan_id, parcel_id, issued_at, expires_at,
used_at, accepted_video_sha256
```

A raw human-chosen code is guessable. A signed token is optional if the portal
always looks the opaque challenge up server-side. Mark it used atomically only
when a submission is accepted.

### Deterministic checks

Each check gets its own `PASS`, `FAIL`, or `INCONCLUSIVE` result:

1. QR decodes from the first configured time window.
2. Challenge exists, matches this loan, has not expired, and has not been used.
3. Capture timestamp is after issuance (allowing explicit clock skew) and before
   expiry; upload arrives within a defined grace period.
4. GPS parses unambiguously and falls inside the pledged parcel.
5. The original uploaded bytes have a SHA-256 digest.
6. Container/frame timestamps are monotonic and no obvious discontinuity is
   present.

Hashing binds the report to the uploaded bytes. It does **not** prove those bytes
came directly from a camera.

### GPS details

- `exifread` is primarily for still-image EXIF. Use ffprobe for standard video
  tags and ExifTool as the development/debugging reference.
- iPhone/QuickTime files may use `com.apple.quicktime.location.ISO6709`.
- Drone GPS may be in ordinary tags, proprietary timed metadata, a subtitle/SRT
  track, or a separate flight log. Test the exact device before demo day.
- Downloaded or transcoded clips usually have no useful capture metadata.
- Shapely assumes Cartesian coordinates. Point-in-polygon topology is acceptable
  for a small parcel with `(longitude, latitude)` ordering, but any distance or
  tolerance calculation should project both geometries to a local CRS first.
- Use `polygon.covers(point)` so a boundary point is not rejected by definition.
- A single GPS point shows camera location, not that all cattle shown are on the
  parcel. A telemetry trajectory is stronger if available.

### What this does not stop

An attacker can edit GPS/timestamps, composite a current QR onto old footage, or
film a replay screen beside the QR. Therefore the UI should say **“provenance
checks passed”**, not “capture authenticity proven.”

A production version needs a controlled capture app or supported drone adapter,
device/app attestation, signed capture manifests or flight logs, server time,
continuity checks, and ideally C2PA-style credentials. None belongs in the
nine-hour demo.

## Fraud scenario

Use an **exact replay** of the accepted first submission. It gives the clearest
contrast:

- QR challenge: `FAIL — already used`;
- file hash: `FAIL — exact match to accepted report HP-…`;
- alert queue: a new high-severity replay case linked to the prior report.

An off-parcel fixture is a useful extra prerecorded test, but it is weaker if its
GPS is merely synthetic. Never alter the model result to manufacture the fraud
case; alter only the controlled test fixture and label it as such.

## Records and reconciliation

Choose SQLite as the source of truth and seed it from CSV. Keep the schema small:

```text
inventory_snapshot(as_of, animal_class, head_count)
inventory_event(event_at, event_type, animal_class, head_count, document_id)
```

Allowed events are `birth`, `sale`, and `death`. Compute, per class and in total:

```text
expected = last_count + births - sales - deaths
variance_heads = observed_point - expected
variance_pct = variance_heads / expected
```

Reject duplicate document IDs, negative head counts, events before the selected
snapshot, and an expected count below zero. Keep sale receipt and calf-crop data
as seeded demo records; document extraction is out of scope.

## Valuation: units matter

USDA AMS livestock quotes are commonly **dollars per hundredweight**, not dollars
per animal. Convert them before applying the formula:

```text
per_head_value = average_live_weight_lb / 100 * price_per_cwt
collateral_value = sum(head_count_i * per_head_value_i)
max_loan = advance_rate * collateral_value
```

Replacement cattle may instead be quoted directly `Per Unit`; do not multiply
those quotes by weight.

### A $400K scenario that is arithmetically possible

The following illustrative snapshot uses USDA AMS report 2069, Mid-South
Livestock Regional Center, Unionville, Tennessee, dated 2026-08-31. It is a demo
fixture, not a current automated appraisal.

| Record-derived class | Expected head | Selected quote | Per-head value | Extended value |
|---|---:|---|---:|---:|
| Bred cows | 180 | 2–4 yr, T2, `Per Unit`, selected lower reference | $2,800.00 | $504,000.00 |
| Feeder calves | 65 | 533 lb × $369.63/cwt | $1,970.13 | $128,058.31 |
| Slaughter bulls | 5 | 1,803 lb × $196.68/cwt | $3,546.14 | $17,730.70 |
| **Total** | **250** |  |  | **$649,789.02** |

At a 65% policy advance rate, all 250 expected head support a maximum of
**$422,362.86**.

For a visual estimate of `247` with an uncertainty range of `241–253`, value no
more than the lower bound. A conservative missing-head allocation removes the
highest-value animals first: five bulls and four cows. The resulting collateral
is `$620,858.31`, and the maximum loan is approximately **$403,557.90**. The
$400K request passes by only about $3,558, which makes uncertainty consequential
instead of decorative.

Caveats that must appear in the report:

- class counts came from records, not vision;
- the selected market report has a date, region, grade, weight, and source URL;
- the bred-cow line in this local report has a small sample and is illustrative;
- advance rate is lender policy, not supplied by USDA;
- transport, health, lien priority, concentration, and other lender haircuts are
  omitted from the hackathon calculation.

Pin the price snapshot in code with an `as_of` date, source report ID, source URL,
unit, weight, and retrieval hash. USDA “latest report” URLs can change in place.
Do not call an old hardcoded table “current.”

## PDF and narrative

### PDF

Use ReportLab for the demo. Folium maps are JavaScript-driven and do not reliably
become a map image merely by passing HTML to a PDF renderer. Render a static parcel
polygon, GPS point, and legend with Matplotlib for the PDF; use Folium only in the
interactive UI.

ReportLab and WeasyPrint generate PDFs but do not by themselves provide a trusted
embedded digital signature. The nine-hour implementation should:

1. create canonical assessment JSON;
2. sign it with an Ed25519 demo key;
3. render report ID, signature, public-key fingerprint, and a verification QR in
   the PDF;
4. sign the final PDF hash and store the detached signature in the verification
   record.

Do not claim PAdES/certificate signing unless it is actually implemented and
verified with a PDF signature tool.

### Claude

All calculations, statuses, flags, and loan limits remain deterministic code.
Send Claude only sanitized aggregate JSON—not videos, ranch coordinates, borrower
names, or arbitrary receipt text—and ask for prose in a constrained JSON schema.
Validate the result. Keep a deterministic template fallback and precompute the
demo response. Claude must never invent a price, clear a failed check, or make the
credit decision.

## Footage and data sources

### Directly usable, licensed evaluation/demo footage

1. [Grazing Cattle in Sado Island, Japan — Aerial Video](https://commons.wikimedia.org/wiki/File:Grazing_Cattle_in_Sado_Island,_Japan_-_Aerial_Video.webm) — Wikimedia Commons, CC BY 3.0, 1280×720, 100.48 s, 15.7 MB. Used in the small-herd detector/tracker test.
2. [ANZCO Wakanui feedlot drone footage](https://commons.wikimedia.org/wiki/File:ANZCO_Wakanui_feedlot_drone_footage.webm) — Wikimedia Commons, CC BY-SA 3.0, 1920×1080, 125.16 s, 108.3 MB. Contains hundreds of cattle and was used for the scale stress test; it is not a single pledged herd and has no supplied count ground truth.
3. [Cows reacting to a drone](https://commons.wikimedia.org/wiki/File:Cows_reacting_to_a_drone.webm) — Wikimedia Commons, CC BY 3.0, 1920×1080, approximately 375 MB.
4. [(Drone Aerial) Herd Of Cows In Rural Tamale](https://commons.wikimedia.org/wiki/File:%28Drone_Aerial%29_Herd_Of_Cows_In_Rural_Tamale.webm) — Wikimedia Commons, CC BY-SA 4.0, 1920×1080, approximately 133 MB.
5. [4K Free Stock Footage: cows grazing near a lake](https://archive.org/details/4k-free-stock-footage-cows-eating-near-lake-drone-mariojrmatos) — Internet Archive item with a directly downloadable original. The item metadata and description disagree between CC BY-ND 4.0 and CC BY 4.0, so resolve the license with the creator before modifying it.

Honor attribution/share-alike requirements in the app and report. YouTube’s terms
prohibit downloading content except when the service or rights holder expressly
permits it. Do not make “download some YouTube clips” the footage plan.

None of these clips contains the portal’s newly issued QR or trustworthy pledged
parcel metadata. For an honest provenance demo, either record owned footage on a
known parcel or explicitly label the QR/GPS version as a synthetic test fixture.

### Labeled-data candidates

See `DATASET_SEARCH.md` for the full provenance and license audit.

- [ICAERUS annotated grazing cows v2](https://doi.org/10.5281/zenodo.11048412): 1,385 Mavic 3 images and 4,941 boxes, grouped by farm/flight under CC BY 4.0. This is the strongest permissively licensed aerial-detector source found.
- [Uruguay Cattle MOT](https://doi.org/10.17632/dk54zg67dd.1): ten ranch videos covering 93 Brangus cattle under CC BY 4.0, plus one manually corrected 478-frame MOT sequence with persistent IDs. Its geometry still needs visual review.
- [New Zealand Cattle Detection](https://doi.org/10.5281/zenodo.5908869): 655 aerial tiles and 29,803 point lines under CC BY 4.0. It is useful for dense counting, but an audit found 14 duplicate point coordinates that must be reviewed.
- [CattleEyeView](https://github.com/AnimalEyeQ/CattleEyeView): the closest gate benchmark—14 loading-ramp sequences with boxes, IDs, and counts—but access terms restrict it to non-commercial research/education and limit display/redistribution. Do not use it without personally accepting the terms or obtaining written permission.
- [Cows2021](https://doi.org/10.5523/bris.4vnrca7qw1642qlwxjadp87h7) and [OpenCows2020](https://doi.org/10.5523/bris.10m32xl88x2b61zlkkgz3fml17) provide fixed overhead walkway imagery under a non-commercial license. Cows2021 videos are short and average only 1.45 tracklets each.
- [WAID](https://github.com/xiaohuicui/WAID) contains usable cattle signal, but its dataset license is absent and manually confirmed near-identical cattle views cross its published splits.
- The strongest dataset for the final demo remains 100–300 hand-labeled frames extracted from footage with the same camera, breed, density, and gate geometry as the final clip. Split by source video, not random adjacent frames.

### Parcel data

For the demo, use a lender-supplied GeoJSON fixture. Production parcel boundaries
would come from the loan/title record, a county assessor GIS service, or a licensed
parcel provider; there is no dependable uniform public nationwide parcel API to
build during a hackathon.

### Price data

- [USDA AMS Livestock, Poultry & Grain Market News](https://www.ams.usda.gov/market-news/livestock-poultry-grain)
- [USDA AMS report 2069](https://mymarketnews.ams.usda.gov/viewReport/2069)
- [National Feeder & Stocker Cattle Dashboard](https://mymarketnews.ams.usda.gov/National_Feeder_Stocker_Dashboard)

Hardcode one reviewed, dated snapshot. Do not build an ingestion pipeline.

## Licensing and operational constraints

- The Ultralytics repository and package are AGPL-3.0. An open hackathon project
  can comply, but a lender-facing proprietary deployment needs a licensing review
  and may require an Ultralytics enterprise license.
- Streamlit upload defaults to 200 MB per file. Two candidate CC clips exceed or
  approach that limit. Configure a deliberate maximum and reject oversized files
  early rather than loading them fully into memory.
- Use chunked hashing and temporary files. Never call `uploaded_file.read()` on a
  multi-gigabyte drone video and retain multiple copies in RAM.
- Business-use drone operations in the US can implicate FAA Part 107 requirements.
  Use existing licensed footage for the hackathon unless the operator and flight
  are properly handled.
- Ranch coordinates, inventory, and financing data are sensitive. Keep exact GPS
  and borrower identity out of the LLM request and define demo-file deletion.

## Required test matrix

| Area | Cases that must be prerecorded or automated |
|---|---|
| QR/challenge | valid; absent; blurred; wrong loan; appears too late; expired; already used |
| Video | unsupported codec; corrupt/truncated; zero frames; very large; metadata stripped; non-monotonic timestamps |
| GPS | inside; outside; exactly on boundary; missing; malformed ISO-6709; latitude/longitude swapped; multiple conflicting tags |
| Freshness | capture before challenge; within window; expired; missing timezone; clock-skew boundary |
| Replay | exact accepted hash; same nonce on a different file; same file under a different filename |
| Count | no cattle; crowded crossing; two simultaneous cattle; occlusion; reverse crossing; animal stops on line; camera moves; detection disappears/reappears |
| Records | no snapshot; duplicate receipt; negative event; events before snapshot; expected count zero; variance threshold boundary |
| Valuation | per-cwt conversion; per-unit quote; stale price; missing class; uncertainty lower bound; rounding only at presentation |
| Report | deterministic fallback without Claude; Claude timeout/malformed JSON; special characters; long explanation; signature verification; keyframe/map present |

## Nine-hour execution plan

### Hour 0–1: asset gate

Before application code:

- secure the exact fixed-gate clip and written license/permission;
- manually establish its ground-truth count;
- test a file from the actual capture device with ffprobe;
- freeze the parcel GeoJSON, record events, price snapshot, attribution, model
  weights, and both scenario files;
- run the detector and enforce the ≤5% count kill criterion.

If there is no suitable footage or the criterion fails, switch immediately to a
visual census estimate with manual correction. Do not spend the day hoping stock
YOLO will improve.

### Hours 1–4: parallel work

- **A:** fixed-camera detector, tracker, directional line crossing, reviewed
  uncertainty band, annotated output.
- **B:** challenge store, QR scan, ffprobe normalization, freshness, SHA-256,
  geofence, replay rules.
- **C:** Streamlit shell, SQLite fixtures, deterministic reconciliation and
  unit-correct valuation.
- **D if available:** report template, static map, keyframes, signature verifier.

### Hours 4–6: integrate one typed assessment object

Every layer consumes the same immutable assessment JSON. Do not let UI, Claude,
or PDF recompute business values independently.

### Hours 6–7: report and fraud queue

Generate the accepted report, submit the exact replay, and verify that it creates
a linked high-severity alert.

### Hours 7–8: failure rehearsal and caching

Run the test matrix, cache annotations and Claude prose, disable network-dependent
paths by default, and keep one button to load each precomputed scenario.

### Hours 8–9: pitch and rehearsal

Five slides:

1. livestock collateral is expensive to verify;
2. challenge-bound visual inventory workflow;
3. accepted 250-head loan scenario and transparent math;
4. exact replay rejected and linked to prior hash;
5. path from metadata checks to controlled, attestable capture.

## Final go/no-go checklist

Do not begin the full build until all are true:

- [ ] final footage permission/license is documented;
- [ ] final clip has manual ground truth and one pledged herd only;
- [ ] fixed-gate point error is ≤5% and truth falls inside the reported range;
- [ ] actual device GPS/timestamp extraction has been tested, or the UI clearly
      labels provenance data as a synthetic fixture;
- [ ] challenge/replay behavior is deterministic and pretested;
- [ ] price units, weights, date, region, and source are displayed;
- [ ] the $400K result is reproduced from a single deterministic function;
- [ ] no UI or prose claims automatic cow/calf/bull classification;
- [ ] no UI claims editable metadata proves capture authenticity;
- [ ] the demo runs with network and Claude unavailable;
- [ ] accepted and replay scenarios are precomputed and rehearsed twice.
