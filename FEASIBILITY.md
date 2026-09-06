# HerdProof — Feasibility Assessment

> Current experiment: [aerial validation results](validation/RESULTS.md). The fixed-camera batch proposal below is retained as an earlier scope.

**Updated: 2026-09-05. Scope: the batch-review prototype in [PLAN.md](PLAN.md).**

## Verdict

**GO for an assisted cattle-passage review prototype.** Suitable footage,
established detection/tracking methods, conventional software components, and a
real inventory-monitoring workflow make it technically plausible.

**Conditional GO for automatic passage counting in a supported setup.** It
requires an end-to-end evaluation on the selected clips. The project has no new
validated cattle-count result from this review.

**Commercial feasibility remains unvalidated.** Existing businesses sell related
services, but this review establishes neither willingness to pay for HerdProof nor
savings relative to manual video review, EID records, or existing inspections.

**The original unrestricted whole-herd verification claim is unsupported.**
Video passages alone cannot establish unique pledged animals, ownership,
completeness, or capture truth. Changing the wording does not solve those gaps.

## Evidence by component

| Component | Evidence available | Assessment |
|---|---|---|
| Fixed-camera passage proposals | Licensed phone footage; tracking literature; prior annotation audit | Plausible; final pipeline and review burden unmeasured |
| Human review and evidence ledger | Ordinary video timestamps, database records, and correction UI | Straightforward to implement; usable speed still needs testing |
| Batch manifest comparison | Deterministic arithmetic | Feasible if batch, direction, time, and coverage match |
| Whole-ranch inventory | No complete capture or independently verified baseline | Outside MVP |
| Exact-media duplicate detection | SHA-256; new local test shows its byte-level boundary | Feasible for exact retained files; not general replay detection |
| Challenge state | Conventional server state and atomic writes | Feasible; implementation not present or tested here |
| Capture time/location | New local metadata-edit probe; platform documentation | Report asserted metadata and consistency, not proof |
| Animal identity/ownership | EID integration possible; ownership needs separate records/checks | Outside vision claim |
| Price-based illustration | Deterministic units and quantity calculation | Feasible; inputs and eligibility remain assumptions |
| Loan approval | Additional underwriting and lender policies required | Outside MVP |
| Export integrity | Standard hashing/signing primitives | Feasible; signatures do not establish truthful inputs |

## What was tested in this review

[Reproducible probe](scripts/probe_video_metadata.py) and
[JSON results](research/2026-09-05/provenance_probe.json).

A two-second, ten-frame synthetic MP4 was generated locally. It contains no
cattle or private media. Existing FFmpeg/ffprobe and Python standard-library
functions were used; no packages were installed.

All six checks passed:

1. Editing metadata changed the file SHA-256.
2. Decoded frames and their timestamps remained identical.
3. The reported creation time changed.
4. The reported location changed.
5. Removing metadata preserved the decoded video.
6. Creation time and location were absent in the stripped version.

This establishes a concrete limitation of file hashes and ordinary MP4 tags.
It does not demonstrate a bypass of a complete challenge system: a reused nonce
could still cause rejection. QR compositing, screen recapture, native attestation,
and cattle detection were not tested in this experiment.

The default local Python lacks the previously used CV packages, and the selected
Uruguay video is not in this checkout. No new detector benchmark, model training,
or ranch field trial was performed in this review.

## Prior experiments retained from the 2026-09-02 assessment

These are historical results reported in the earlier assessment, not rerun here.
The supporting raw videos and full run artifacts are not present in this checkout.
Use them as development evidence rather than independently reproduced benchmarks.

Reported stack: Ultralytics 8.3.200, YOLOv8n COCO weights, OpenCV, FFmpeg 7.1.5,
and Shapely 2.1.2.

| Historical test | Reported result | Implication |
|---|---|---|
| QR generated in initial video frames | Decoded successfully | Token observation is mechanically feasible |
| QuickTime time/location tags written/read | Successful | Editable fields can be parsed, not trusted as capture proof |
| Metadata-stripping transcode | GPS/time disappeared, QR remained readable | Missing data needs an explicit unknown state |
| Free-moving aerial clip, roughly 20–25 visible cattle | Best sampled frame: 26 / 20 / 17 detections at thresholds 0.10 / 0.25 / 0.50 | Threshold sensitivity; not a calibrated count interval |
| Tracking sampled aerial footage | 51 ByteTrack IDs; 72 BoT-SORT IDs | Fragmented tracks cannot be summed as unique cattle |
| Dense feedlot footage with hundreds visible | 63 / 33 / 9 detections at the same thresholds in one frame | Stock model did not support the dense aerial claim |
| Runtime | 101 inference frames: 11.4 s; two 226-frame tracking passes: 55.4 s total | Short processing may be practical; not a phone-device benchmark |

Historical model hash:
`f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`.

The tracker reportedly attempted to install `lap` automatically. Disable
automatic dependency fetching and prepare pinned dependencies before a demo;
follow the user's package/install protections.

The subsequent dataset audit reported 9 annotated identities, 7 midpoint
crossers, and 6 completed traversals in the Uruguay MOT sequence. This was an
event-definition check on annotation tracks, not evidence of detector accuracy.
See [DATASET_SEARCH.md](DATASET_SEARCH.md) for the audit and licensing history.

## What the further research changes

Detailed source analysis is in [RESEARCH_2026-09-05.md](RESEARCH_2026-09-05.md).

- **Counting:** published work supports feasibility under constrained conditions,
  but good detection does not establish accurate passage counting. Full-clip
  review is the credible initial fallback.
- **Workflow:** receiving and handling sessions are a more plausible capture
  opportunity than an on-demand whole-herd video.
- **Lending:** monitoring records can be useful, while ownership, collateral
  evaluation, and inspection independence remain separate requirements.
- **Provenance:** app/device integrity and signed content history strengthen
  evidence about origin and modification. They do not establish that the scene
  represents the claimed collateral.
- **Differentiation:** cattle counting for lenders is already offered. The
  proposed opportunity is reduced work reviewing a defined batch and preparing
  its evidence, which requires customer testing.

## Validation required before stage claims

### 1. Freeze the observation definition

Independently label every forward/reverse passage and incomplete track on the
chosen clip. Use a second reviewer for the demo ground truth. Preserve disagreements
and their resolution. Label whether the video is a full batch or only a passage
example. Public footage does not establish a real borrower's collateral.

### 2. Run the full pipeline

Evaluate annotation tracks, then tracker with annotation boxes where practical,
then pixels through the detector/tracker/event rules. Retain per-event results
and all evaluated clips, including failures. Freeze tuning and evaluation clips
before adjusting thresholds. A curated stage clip is separate from the evaluation.

At small counts, demand exact event matches for an automatic-count stage claim.
One missed event among six is a 16.7% error. A 5% tolerance is not useful shorthand
for that sample. The assisted demo can show model errors if the correction is
visible and the reviewed result agrees with independent labels.

### 3. Measure the work

Compare manual video counting/report preparation with the assisted workflow.
Include full-clip review, setup, recording, uploads, corrections, and recaptures.
A model runtime alone is not time saved. A pilot target such as halving review
time is a proposed acceptance goal, not a measured result or industry standard.

### 4. Preserve abstention

Test incomplete footage, unobservable recirculation, unresolved reversals,
overlap, camera movement, wrong manifest scope, and missing capture data.
If available evidence cannot resolve the relevant quantity, export an incomplete
review and withhold any result presented as verified eligible collateral.

### 5. Test submission integrity separately

Test exact file reuse, renamed files, changed encoding, same-request retries,
expired/reused challenges, and concurrent submissions. Byte-different media may
not match. A legitimate retry should return its prior result. A duplicate finding
is not a fraud finding.

## MVP scope and decision gates

Build the reviewer, batch manifest, and evidence export first. Optional maps,
native capture, EID hardware, polished PDFs, signatures, and LLM prose follow
only if the core works. Keep exact real-media counts separate from synthetic
business assumptions.

Proceed to a pilot only after an operator can capture suitable batches without
material extra handling and a lender/inspection firm identifies a concrete use
for the report. If they already obtain reliable EID counts and see no additional
value in the video evidence, revise the product hypothesis.

If the automatic count underperforms but assisted review saves time, the assisted
product remains viable. If review does not save work, do not describe the product
as an efficiency improvement. If the intended buyer requires a complete
independent inspection, borrower-supplied video is insufficient for that claim.
