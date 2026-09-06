# HerdProof aerial validation results

Executed locally on 2026-09-05. This supersedes the earlier passage proposal for the current experiment.

## Reference-label problem

**These scores are provisional agreement with publisher annotations, not verified cattle-count accuracy.** Full-resolution inspection found multiple visible cows in image `161ccda3efc6`, whose correctly named YOLO and VOC files both contain no objects. Empty label files cannot be treated as confirmed empty scenes. The original scores and frozen choices are preserved; no troublesome images were selectively removed.

See the [label audit](label-audit.json) and [visual evidence](evidence/finetuned/161ccda3efc6.jpg). A fresh independently annotated test set and an audit of training/calibration labels are required before accuracy or workload claims. The extent of incomplete labels is unknown.

## Provisional annotation-agreement results

92 images from 17 evaluation flights: 49 nonempty-label images, 43 empty-label images, 1,065 annotated animal observations. The same animals may recur across images.

| Method | Label precision | Label recall | Unmatched predictions | Unmatched labels | Count MAE, all | MAE, nonempty labels | Box disagreement |
|---|---:|---:|---:|---:|---:|---:|---:|
| COCO whole image | 50.0% | 0.5% | 5 | 1060 | 11.47 | 21.53 | 1065 |
| COCO tiled | 55.8% | 2.3% | 19 | 1041 | 11.13 | 20.88 | 1060 |
| Cattle fine-tune, tiled | 63.7% | 68.0% | 413 | 341 | 3.89 | 4.92 | 754 |

Box disagreement = unmatched predictions + unmatched labels under one-to-one IoU ≥ 0.5. This is not necessarily the number of marker edits: an imperfect box may still place its marker correctly. Neither metric includes image search or inspection time.

### Marker-level diagnostic

This secondary diagnostic matches the review UI by assigning each marker to at most one annotation box. It was not used for parameter selection.

- baseline/whole: **1061 marker/reference disagreements** (3 unmatched markers, 1058 unmatched labels), against 1065 supplied annotations. This is not a verified edit count.
- baseline/tiled: **1054 marker/reference disagreements** (16 unmatched markers, 1038 unmatched labels), against 1065 supplied annotations. This is not a verified edit count.
- finetuned/tiled-finetuned: **668 marker/reference disagreements** (370 unmatched markers, 298 unmatched labels), against 1065 supplied annotations. This is not a verified edit count.

## Interpretation

The stock COCO detector recovered only 2.3% of supplied cattle annotations with tiling. Its marker proposals differ substantially from the supplied labels. The fine-tune demonstrates a working local training/inference path, but the annotation problem prevents a trustworthy product accuracy or correction-work claim from this experiment.

The domain-specific follow-up has a **754 box-disagreement proxy** against the same 1,065 supplied annotations. Recall of those annotations is **68.0%**. It produces detections on 32 of 43 empty-label images; these are not established false alarms because empty scenes were not independently verified. Missing labels may also affect training and calibration.

Six original calibration flights supplied 30 training images with 334 source annotations (176 training tiles). Two separate original calibration flights supplied five images with 62 annotations (31 validation tiles). The model trained for 20 fixed epochs; the final checkpoint was used. Calibration chose the threshold, not evaluation results.

**This is a follow-up on a known benchmark.** Baseline aggregate results and selected failure overlays had already been seen. The original 17 evaluation flights stayed out of training and threshold selection, but this is not a fresh blind external test or unseen-farm validation.

The two Mac GPU training attempts failed. Completed training used CPU and the original upstream loss implementation. Failed runs and the backend amendment are retained separately. The completed checkpoint's backend and identity are recorded in its metadata.

## What is implemented and verified

- Frozen 127-image sample, grouped by image-side flight; CRC32 and SHA-256 checks for each downloaded member. Full-archive checksum was not reverified by this partial download.
- Whole-image/tiled baselines, calibration-only threshold selection, object matching, count disagreements, detections on empty-label images, per-flight metrics, and retained raw predictions.
- Four-image manual/assisted review instrument with explicit start, visible-tab and wall timers, separate Add/Remove tools, nearest-marker removal, small outlines, full-resolution zoom, and reference labels withheld until completion. Interface v2 fixes adjacent clicks deleting existing markers.
- Synthetic inventory CSV plus dated sale, missing East evidence, supplied evidence pending review, and completed annotation-reference replay.
- Tests cover duplicate predictions, equal totals hiding mistakes, missing/stale/unreviewed observations, duplicate documents, ordering ambiguity, invalid quantities, and final marker scoring.

## Human timing

Status: **exploratory**. Completed human sessions: **1**. Browser QA is excluded. No human time-saving claim has been established.

The first participant reported both missed clustered cattle and interference between nearby clicks. Inspection confirmed the v1 interface could remove a neighbour while adding a cow. The original session is retained and annotated in [review feedback](review-feedback.json); v2 sessions are grouped separately. This session cannot establish a clean speed or accuracy comparison.

Review four images in the local page before opening the example, then run `.venv/bin/python scripts/summarize_review_sessions.py`. Mark every visible cow; automated comparisons with supplied labels are provisional. Different conditions use different images; multiple participants and counterbalancing are needed to separate condition from image difficulty.

## Limits

Results concern visible cattle in sampled still images. They do not establish whole-property coverage, unique animal identity, ownership, loan eligibility, authentic capture, or lender acceptance. Adjacent images are correlated; calibration/evaluation may share farms. Publisher annotations were spot-checked, not independently relabeled in full.

The example divides historical pasture imagery into artificial West/East image halves. It uses synthetic business records, dates, and coverage assumptions. Reference-review buttons replay publisher labels; they are neither automatic corrections nor a new human inspection. Supported input is the documented CSV schema, not arbitrary lender PDFs.

## Artifacts

- [Reproduction and protocols](README.md)
- [Portable metrics](results.json)
- [Human review status](human-review-summary.json)
- Local raw reports: `runs/baseline/report.json`, `runs/finetuned/report.json`.
- Local page: <http://127.0.0.1:18765/>

Imagery: Louise Helary and Adrien Lebreton / Institut de l'Elevage, ICAERUS grazing-cow v2, CC BY 4.0, <https://doi.org/10.5281/zenodo.11048412>. Review/overlay copies omit location metadata.
