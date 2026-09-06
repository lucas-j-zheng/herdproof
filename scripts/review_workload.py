#!/usr/bin/env python3
"""Secondary marker-level workload diagnostic matching the review UI.

Primary benchmark selection remains frozen on box IoU. A correctly placed point
can need no marker edit even when the detector box has imperfect extent, so the
box FP+FN count is not necessarily the number of clicks a reviewer needs.
"""
import argparse
import json
from pathlib import Path
from serve_validation import point_accuracy

BASE=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run",type=Path,default=BASE/"validation/runs/baseline")
    args=p.parse_args()
    report=json.loads((args.run/"report.json").read_text())
    manifest=json.loads((BASE/"validation/data/manifest.json").read_text())
    records={r["id"]:r for r in manifest["records"]}
    modes={}
    for mode,result in report["results"].items():
        rows=[]
        for r in result["images"]:
            points=[[(b[0]+b[2])/2,(b[1]+b[3])/2] for b in r["predictions"]]
            score=point_accuracy(points,records[r["id"]]["boxes"])
            rows.append({"id":r["id"],**score})
        totals={k:sum(r[k] for r in rows) for k in ("marked","reference","matched","false_marks","missed")}
        totals["marker_additions_and_removals"]=totals["false_marks"]+totals["missed"]
        totals["images_with_no_marker_errors"]=sum(r["false_marks"]+r["missed"]==0 for r in rows)
        modes[mode]={"summary":totals,"images":rows}
    output={"method":"Secondary one-to-one marker containment in publisher boxes, matching the review UI; not used to select confidence or model",
            "time_saved":None,"modes":modes}
    (args.run/"review-workload.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({m:r["summary"] for m,r in modes.items()},indent=2))


if __name__=="__main__":main()
