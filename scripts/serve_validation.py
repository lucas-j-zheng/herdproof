#!/usr/bin/env python3
"""Loopback-only review instrument. Raw EXIF, source paths, and labels are not served."""
from __future__ import annotations
import argparse
import json
import math
import random
import secrets
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parents[1]
RUN = BASE / "validation/runs/baseline"
SESSIONS = BASE / "validation/sessions"


def point_accuracy(points, boxes):
    # Point-in-box maximum matching. Each animal and each mark may match once.
    assigned = {}
    edges = [[i for i,b in enumerate(boxes) if b[0] <= x <= b[2] and b[1] <= y <= b[3]] for x,y in points]
    def assign(p, seen):
        for g in edges[p]:
            if g in seen: continue
            seen.add(g)
            if g not in assigned or assign(assigned[g], seen):
                assigned[g] = p
                return True
        return False
    for p in range(len(points)): assign(p,set())
    return {"marked":len(points),"reference":len(boxes),"matched":len(assigned),
            "false_marks":len(points)-len(assigned),"missed":len(boxes)-len(assigned)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file(self, path, content_type):
        if not path.is_file(): return self.send({"error":"Not found"},404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/": return self.file(BASE / "validation/review.html","text/html; charset=utf-8")
        if path == "/marker-tools.js": return self.file(BASE / "validation/marker-tools.js","text/javascript; charset=utf-8")
        if path == "/api/summary":
            report_path = RUN / "report.json"
            if not report_path.exists(): return self.send({"status":"running"})
            r = json.loads(report_path.read_text())
            results={k:v["summary"] for k,v in r["results"].items()}
            if r["selection"]["selected_mode"]=="tiled-finetuned":
                original=json.loads((BASE/"validation/runs/baseline/report.json").read_text())
                results={**{k:v["summary"] for k,v in original["results"].items()},**results}
            workload_path=RUN/"review-workload.json"
            workloads=json.loads(workload_path.read_text())["modes"] if workload_path.exists() else {}
            default_model = json.loads((BASE / "training/default_model.json").read_text())
            return self.send({"status":"ready","model":r["selection"]["selected_mode"],"domain_finetuned":r["selection"]["selected_mode"]=="tiled-finetuned",
                              "benchmark_run":RUN.name,
                              "default_model":{"model_id":default_model["model_id"],"mode":default_model["mode"],
                                               "confidence":default_model["confidence"],
                                               "metrics":default_model.get("recorded_metrics")},
                              "reference_status":"provisional_incomplete_labels",
                              "sample_images":r["sample_images"],
                              "marker_workload":{k:v["summary"] for k,v in workloads.items()},"results":results})
        if path == "/api/demo":
            if not (RUN / "demo.json").exists(): return self.send({"error":"Benchmark is still running"},409)
            return self.send(json.loads((RUN / "demo.json").read_text()))
        if path.startswith("/images/"):
            name = path.removeprefix("/images/")
            if len(name) != 16 or not name.endswith(".jpg") or any(c not in "0123456789abcdef" for c in name[:-4]):
                return self.send({"error":"Invalid image"},400)
            return self.file(BASE / "validation/review-assets" / name,"image/jpeg")
        return self.send({"error":"Not found"},404)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}:
            return self.send({"error":"Origin rejected"},403)
        try:
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 200000: raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(length))
            private_path = RUN / "review-private.json"
            if not private_path.exists(): return self.send({"error":"Benchmark is still running"},409)
            private = json.loads(private_path.read_text())
            if self.path == "/api/start":
                if body.get("participant_type") not in {"human","automated_qa"}: raise ValueError("Participant type required")
                if body.get("ui_version", "1") not in {"1", "2"}: raise ValueError("Unknown review interface version")
                sid = secrets.token_hex(12)
                rng = random.Random(int(sid,16))
                ids = private["trial_ids"][:]
                rng.shuffle(ids)
                modes = ["manual","assisted"] * 2
                if rng.randrange(2): modes.reverse()
                state = {"id":sid,"participant_type":body["participant_type"],"created":datetime.now(timezone.utc).isoformat(),
                         "ui_version":body.get("ui_version","1"),
                         "pipeline":RUN.name,"model":private["model"],"threshold":private["threshold"],
                         "weights_sha256":json.loads((RUN/"metadata.json").read_text()).get("weights_sha256"),
                         "trials":[{"image_id":i,"mode":m} for i,m in zip(ids,modes)],"results":[]}
                SESSIONS.mkdir(parents=True,exist_ok=True)
                (SESSIONS / f"{sid}.json").write_text(json.dumps(state,indent=2)+"\n")
                return self.send({"session":sid,"trials":[{**r,"points":[[(b[0]+b[2])/2,(b[1]+b[3])/2] for b in private["predictions"][r["image_id"]]] if r["mode"] == "assisted" else []} for r in state["trials"]]})
            sid = body.get("session","")
            if len(sid) != 24 or any(c not in "0123456789abcdef" for c in sid): raise ValueError("Invalid session")
            path = SESSIONS / f"{sid}.json"
            state = json.loads(path.read_text())
            if (state.get("pipeline"),state.get("model"),state.get("threshold")) != (RUN.name,private["model"],private["threshold"]):
                raise ValueError("The active model changed; reload and start a new session")
            index = body.get("index")
            if index != len(state["results"]) or index >= len(state["trials"]): raise ValueError("Trial order invalid")
            if self.path == "/api/begin":
                state["began"] = time.time()
                path.write_text(json.dumps(state,indent=2)+"\n")
                return self.send({"ok":True})
            if self.path != "/api/finish": return self.send({"error":"Not found"},404)
            if "began" not in state: raise ValueError("Start trial first")
            points = body["points"]
            if len(points) > 1000 or any(len(p) != 2 or any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) or not 0 <= x <= 1 for x in p) for p in points):
                raise ValueError("Invalid markers")
            active = float(body["active_seconds"])
            wall = time.time()-state["began"]
            if not math.isfinite(active) or not 0 <= active <= wall+2: raise ValueError("Invalid timing")
            trial = state["trials"][index]
            result = {**trial,"active_seconds":active,"wall_seconds":wall,
                      "points":points,"accuracy":point_accuracy(points,private["records"][trial["image_id"]]["boxes"])}
            state["results"].append(result)
            del state["began"]
            path.write_text(json.dumps(state,indent=2)+"\n")
            complete = len(state["results"]) == len(state["trials"])
            return self.send({"complete":complete,"results":state["results"] if complete else None,
                              "interpretation":"Exploratory timing on different images. Reference labels are known to be incomplete, so mark/reference disagreements are provisional, not verified human errors. Independent annotation and more participants are needed before accuracy or time-saving claims."})
        except (ValueError,KeyError,TypeError,FileNotFoundError) as e:
            return self.send({"error":str(e)},400)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=18765)
    parser.add_argument("--run",type=Path,default=RUN)
    args = parser.parse_args()
    RUN = args.run.resolve()
    print(f"HerdProof validation: http://127.0.0.1:{args.port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()
