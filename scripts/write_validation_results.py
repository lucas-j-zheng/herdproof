#!/usr/bin/env python3
"""Generate a portable report from completed runs, without inventing human data."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main():
    baseline = json.loads((BASE / "validation/runs/baseline/report.json").read_text())
    fine_path = BASE / "validation/runs/finetuned/report.json"
    fine = json.loads(fine_path.read_text()) if fine_path.exists() else None
    human = json.loads((BASE / "validation/human-review-summary.json").read_text())
    audit = json.loads((BASE / "validation/label-audit.json").read_text())
    methods = {"COCO whole image": baseline["results"]["whole"], "COCO tiled": baseline["results"]["tiled"]}
    if fine: methods["Cattle fine-tune, tiled"] = fine["results"]["tiled-finetuned"]
    lines = ["# HerdProof aerial validation results", "", "Executed locally on 2026-09-05. This supersedes the earlier passage proposal for the current experiment.", "",
             "## Reference-label problem", "", "**These scores are provisional agreement with publisher annotations, not verified cattle-count accuracy.** Full-resolution inspection found multiple visible cows in image `161ccda3efc6`, whose correctly named YOLO and VOC files both contain no objects. Empty label files cannot be treated as confirmed empty scenes. The original scores and frozen choices are preserved; no troublesome images were selectively removed.", "", "See the [label audit](label-audit.json) and [visual evidence](evidence/finetuned/161ccda3efc6.jpg). A fresh independently annotated test set and an audit of training/calibration labels are required before accuracy or workload claims. The extent of incomplete labels is unknown.", "",
             "## Provisional annotation-agreement results", "", "92 images from 17 evaluation flights: 49 nonempty-label images, 43 empty-label images, 1,065 annotated animal observations. The same animals may recur across images.", "",
             "| Method | Label precision | Label recall | Unmatched predictions | Unmatched labels | Count MAE, all | MAE, nonempty labels | Box disagreement |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    portable = {}
    for name, result in methods.items():
        s = result["summary"]
        lines.append(f"| {name} | {100*(s['precision'] or 0):.1f}% | {100*(s['recall'] or 0):.1f}% | {s['fp']} | {s['fn']} | {s['count_mae']:.2f} | {result['positive_only']['count_mae']:.2f} | {s['correction_operations']} |")
        portable[name] = {"threshold":result["threshold"],"summary":s,"positive_only":result["positive_only"]}
    workloads={}
    for name in ("baseline","finetuned"):
        p=BASE/"validation/runs"/name/"review-workload.json"
        if p.exists():workloads[name]={k:v["summary"] for k,v in json.loads(p.read_text())["modes"].items()}
    lines += ["", "Box disagreement = unmatched predictions + unmatched labels under one-to-one IoU ≥ 0.5. This is not necessarily the number of marker edits: an imperfect box may still place its marker correctly. Neither metric includes image search or inspection time.", "", "### Marker-level diagnostic", "", "This secondary diagnostic matches the review UI by assigning each marker to at most one annotation box. It was not used for parameter selection.", ""]
    for run,modes in workloads.items():
        for mode,s in modes.items():
            lines.append(f"- {run}/{mode}: **{s['marker_additions_and_removals']} marker/reference disagreements** ({s['false_marks']} unmatched markers, {s['missed']} unmatched labels), against {s['reference']} supplied annotations. This is not a verified edit count.")
    lines += ["", "## Interpretation", "", "The stock COCO detector recovered only 2.3% of supplied cattle annotations with tiling. Its marker proposals differ substantially from the supplied labels. The fine-tune demonstrates a working local training/inference path, but the annotation problem prevents a trustworthy product accuracy or correction-work claim from this experiment.", ""]
    if fine:
        s = fine["results"]["tiled-finetuned"]["summary"]
        lines += [f"The domain-specific follow-up has a **{s['correction_operations']} box-disagreement proxy** against the same 1,065 supplied annotations. Recall of those annotations is **{100*(s['recall'] or 0):.1f}%**. It produces detections on {s['negative_images_with_false_alarms']} of {s['negative_images']} empty-label images; these are not established false alarms because empty scenes were not independently verified. Missing labels may also affect training and calibration.", "",
                  "Six original calibration flights supplied 30 training images with 334 source annotations (176 training tiles). Two separate original calibration flights supplied five images with 62 annotations (31 validation tiles). The model trained for 20 fixed epochs; the final checkpoint was used. Calibration chose the threshold, not evaluation results.", "",
                  "**This is a follow-up on a known benchmark.** Baseline aggregate results and selected failure overlays had already been seen. The original 17 evaluation flights stayed out of training and threshold selection, but this is not a fresh blind external test or unseen-farm validation.", "",
                  "The two Mac GPU training attempts failed. Completed training used CPU and the original upstream loss implementation. Failed runs and the backend amendment are retained separately. The completed checkpoint's backend and identity are recorded in its metadata.", ""]
    else: lines += ["The cattle-specific follow-up has no completed evaluation yet.", ""]
    lines += ["## What is implemented and verified", "",
              "- Frozen 127-image sample, grouped by image-side flight; CRC32 and SHA-256 checks for each downloaded member. Full-archive checksum was not reverified by this partial download.",
              "- Whole-image/tiled baselines, calibration-only threshold selection, object matching, count disagreements, detections on empty-label images, per-flight metrics, and retained raw predictions.",
              "- Four-image manual/assisted review instrument with explicit start, visible-tab and wall timers, separate Add/Remove tools, nearest-marker removal, small outlines, full-resolution zoom, and reference labels withheld until completion. Interface v2 fixes adjacent clicks deleting existing markers.",
              "- Synthetic inventory CSV plus dated sale, missing East evidence, supplied evidence pending review, and completed annotation-reference replay.",
              "- Tests cover duplicate predictions, equal totals hiding mistakes, missing/stale/unreviewed observations, duplicate documents, ordering ambiguity, invalid quantities, and final marker scoring.", "",
              "## Human timing", "", f"Status: **{human['status']}**. Completed human sessions: **{human['complete_human_sessions']}**. Browser QA is excluded. No human time-saving claim has been established.", "",
              "The first participant reported both missed clustered cattle and interference between nearby clicks. Inspection confirmed the v1 interface could remove a neighbour while adding a cow. The original session is retained and annotated in [review feedback](review-feedback.json); v2 sessions are grouped separately. This session cannot establish a clean speed or accuracy comparison.", "",
              "Review four images in the local page before opening the example, then run `.venv/bin/python scripts/summarize_review_sessions.py`. Mark every visible cow; automated comparisons with supplied labels are provisional. Different conditions use different images; multiple participants and counterbalancing are needed to separate condition from image difficulty.", "",
              "## Limits", "", "Results concern visible cattle in sampled still images. They do not establish whole-property coverage, unique animal identity, ownership, loan eligibility, authentic capture, or lender acceptance. Adjacent images are correlated; calibration/evaluation may share farms. Publisher annotations were spot-checked, not independently relabeled in full.", "",
              "The example divides historical pasture imagery into artificial West/East image halves. It uses synthetic business records, dates, and coverage assumptions. Reference-review buttons replay publisher labels; they are neither automatic corrections nor a new human inspection. Supported input is the documented CSV schema, not arbitrary lender PDFs.", "",
              "## Artifacts", "", "- [Reproduction and protocols](README.md)", "- [Portable metrics](results.json)", "- [Human review status](human-review-summary.json)",
              "- Local raw reports: `runs/baseline/report.json`, `runs/finetuned/report.json`.", "- Local page: <http://127.0.0.1:18765/>", "",
              "Imagery: Louise Helary and Adrien Lebreton / Institut de l'Elevage, ICAERUS grazing-cow v2, CC BY 4.0, <https://doi.org/10.5281/zenodo.11048412>. Review/overlay copies omit location metadata.", ""]
    (BASE / "validation/RESULTS.md").write_text("\n".join(lines))
    files = ["pyproject.toml","uv.lock","validation/protocol.json","validation/finetune-protocol.json"]
    files += [str(p.relative_to(BASE)) for p in (BASE / "scripts").glob("*aerial*.py")]
    hashes = {f:hashlib.sha256((BASE/f).read_bytes()).hexdigest() for f in sorted(files)}
    (BASE / "validation/results.json").write_text(json.dumps({"evaluation_images":92,"evaluation_flights":17,"reference_audit":audit,"methods":portable,"marker_workloads":workloads,"human_review":human,"file_sha256":hashes,"known_benchmark_finetune":bool(fine)},indent=2)+"\n")
    print("Wrote validation/RESULTS.md and validation/results.json")


if __name__ == "__main__": main()
