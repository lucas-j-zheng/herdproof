#!/usr/bin/env python3
"""Summarize real review sessions separately from browser/automated QA."""
import json
from pathlib import Path


def mode_totals(sessions):
    modes = {}
    for mode in ("manual","assisted"):
        rows = [r for s in sessions for r in s["results"] if r["mode"] == mode]
        modes[mode] = {"trials":len(rows), "active_seconds":sum(r["active_seconds"] for r in rows),
                       "reference_observations":sum(r["accuracy"]["reference"] for r in rows),
                       "false_marks":sum(r["accuracy"]["false_marks"] for r in rows),
                       "missed":sum(r["accuracy"]["missed"] for r in rows)}
    return modes


def main():
    sessions = []
    for path in Path("validation/sessions").glob("*.json"):
        s = json.loads(path.read_text())
        if s.get("participant_type") == "human" and s.get("trials") and len(s.get("results",[])) == len(s["trials"]):
            sessions.append(s)
    pipelines = sorted({s.get("pipeline","legacy_unspecified") for s in sessions})
    by_pipeline = {p:mode_totals([s for s in sessions if s.get("pipeline","legacy_unspecified")==p]) for p in pipelines}
    interfaces = sorted({s.get("ui_version","1") for s in sessions})
    by_interface = {v:mode_totals([s for s in sessions if s.get("ui_version","1")==v]) for v in interfaces}
    feedback_path=Path("validation/review-feedback.json")
    feedback=json.loads(feedback_path.read_text())["feedback"] if feedback_path.exists() else []
    relevant=[f for f in feedback if f["session_id"] in {s["id"] for s in sessions}]
    result = {"complete_human_sessions":len(sessions),"status":"exploratory" if sessions else "not_measured",
              "modes":mode_totals(sessions),"by_pipeline":by_pipeline,"by_interface":by_interface,
              "interface_feedback":relevant,"time_savings_claim":None,
              "note":"Different images per condition, incomplete reference labels, and reported v1 marker interference prevent a clean efficiency comparison. Interface versions are separated. Automated QA excluded."}
    Path("validation/human-review-summary.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__": main()
