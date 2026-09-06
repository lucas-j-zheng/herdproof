"""HerdProof world CLI: prepare, persistent review, build, verify and private package."""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import shutil
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from world_core import (canonical, default_review, digest, load_config, load_review,
                        prepare, read, sha, validate_review, write)
from world_build import (HERE, ROOT, VIEWER, INPUT_KEYS, build, check_inputs,
                         lock_inputs, verify)


def prepare_field(path,refresh=False):
    start=time.perf_counter();base,cfg=load_config(path)
    if (base/"inputs.lock.json").exists() and not refresh:check_inputs(base,cfg)
    prepared,folder=prepare(path)
    review_path=base/cfg.get("review","review.json")
    if review_path.exists():
        validate_review(read(review_path),prepared)
    else:write(review_path,default_review(prepared["snapshot"]))
    lock_inputs(base,cfg)
    write(base/"preparation-timing.json",{"seconds":time.perf_counter()-start,"snapshot":prepared["snapshot"],
                                        "scope":"Cached image normalization and appearance proposals; acquisition/alignment separately recorded"})
    return {"snapshot":prepared["snapshot"],"observations":len(prepared["observations"]),"prepared":str(folder)}


def review_server(path,port):
    path=Path(path).resolve();base,cfg=load_config(path)
    prepared,_=prepare(path);dest=(base/cfg.get("output","build")).resolve()
    if not (dest/"build-manifest.json").exists():build(path)
    token=secrets.token_urlsafe(24)
    started=time.perf_counter();counts={"saves":0,"rebuilds":0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):
            if args and str(args[1]) not in ("200","304"):super().log_message(fmt,*args)

        def json(self,code,value):
            data=canonical(value);self.send_response(code);self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store")
            self.end_headers();self.wfile.write(data)

        def do_GET(self):
            try:
                url=urlparse(self.path).path
                if url=="/api/review":
                    r=load_review(base,cfg,prepared)
                    return self.json(200,{"review":r,"hash":digest(r),"token":token})
                relative=unquote(url).lstrip("/") or "index.html"
                target=(dest/relative).resolve()
                if not target.is_relative_to(dest) or not target.is_file():
                    return self.json(404,{"error":"File not found"})
                mime=mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if target.suffix in (".js",".mjs"):mime="text/javascript"
                self.send_response(200);self.send_header("Content-Type",mime)
                self.send_header("Content-Length",str(target.stat().st_size))
                self.send_header("Cache-Control","no-cache");self.send_header("X-Content-Type-Options","nosniff")
                self.end_headers()
                with target.open('rb') as stream:shutil.copyfileobj(stream,self.wfile)
            except (ValueError,OSError) as e:self.json(400,{"error":str(e)})

        def do_POST(self):
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=25_000_000:raise ValueError("Request body too large or missing")
                # Writes require a session token and the browser's same-origin context.
                origin=self.headers.get("Origin")
                if origin and origin not in (f"http://127.0.0.1:{port}",f"http://localhost:{port}"):
                    return self.json(403,{"error":"Cross-origin write rejected"})
                data=json.loads(self.rfile.read(length))
                if data.get("token")!=token:return self.json(403,{"error":"Missing review session token"})
                if self.path=="/api/review":
                    current=load_review(base,cfg,prepared)
                    if data.get("expected_hash")!=digest(current):
                        return self.json(409,{"error":"Review changed in another tab. Reload before saving."})
                    candidate=validate_review(data["review"],prepared)
                    candidate["revision"]=current["revision"]+1
                    write(base/cfg.get("review","review.json"),candidate)
                    counts["saves"]+=1
                    write(base/"review-timing.json",{"session_elapsed_seconds":time.perf_counter()-started,**counts,
                                                   "scope":"Elapsed local review session; includes idle time"})
                    return self.json(200,{"review":candidate,"hash":digest(candidate)})
                if self.path=="/api/build":
                    # A new interpreter also makes source provenance truthful during
                    # development when Python files change while review stays open.
                    import subprocess,sys
                    run=subprocess.run([sys.executable,str(HERE/'world.py'),'build','--config',str(path),'--offline'],capture_output=True,text=True)
                    if run.returncode:raise ValueError(run.stderr.strip() or run.stdout.strip())
                    result=dest;counts["rebuilds"]+=1
                    return self.json(200,{"built":True,"scene":"scene.json","verification":verify(result)})
                if self.path=="/api/validation":
                    report=data["report"]
                    report["scene_sha256"]=sha(dest/"scene.json")
                    report["snapshot"]=prepared["snapshot"]
                    write(base/"evidence/browser-validation.json",report)
                    return self.json(200,{"saved":True})
                if self.path=="/api/capture":
                    import base64
                    name=data["name"]
                    if name not in ("overview","walking","cow"):raise ValueError("Invalid capture name")
                    raw=base64.b64decode(data["png"],validate=True)
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError("Expected PNG screenshot")
                    out=base/"evidence";out.mkdir(exist_ok=True)
                    (out/(name+".png")).write_bytes(raw)
                    return self.json(200,{"saved":True})
                self.json(404,{"error":"Unknown operation"})
            except (ValueError,KeyError,OSError) as e:self.json(400,{"error":str(e)})

    server=HTTPServer(("127.0.0.1",port),Handler)
    print(f"{cfg['name']}: http://127.0.0.1:{port}/ (review: /review.html)",flush=True)
    server.serve_forever()


def package(configs,destination):
    """Private zip, including locked dependencies and inputs, never published."""
    files={p for p in HERE.glob("world*.py")}|{HERE/"pyproject.toml",HERE/"uv.lock",HERE/".python-version"}
    files|={p for p in VIEWER.iterdir() if p.is_file()}
    expected_builds=[]
    for path in configs:
        base,cfg=load_config(path);check_inputs(base,cfg)
        output=base/cfg.get("output","build")
        verify(output)
        manifest=read(output/"build-manifest.json")
        if manifest["inputs"]!=check_inputs(base,cfg) or manifest["review_sha256"]!=digest(read(base/cfg.get("review","review.json"))):
            raise ValueError("Rebuild this field before packaging: inputs or review changed")
        if any(sha(ROOT/name)!=expected for name,expected in manifest["source_sha256"].items()):
            raise ValueError("Rebuild this field before packaging: source changed")
        expected_builds.append((output/"build-manifest.json",str(base.relative_to(ROOT)/"expected-build-manifest.json")))
        files.add(Path(path).resolve())
        files|={(base/cfg[key]).resolve() for key in INPUT_KEYS if cfg.get(key)}
        for name in (cfg.get("review","review.json"),"inputs.lock.json","README.md","preparation-timing.json","review-timing.json","alignment-provenance.json","last-build.json"):
            if (base/name).is_file():files.add((base/name).resolve())
        files|={p.resolve() for folder in (base/"evidence",base.parent/"evidence") for p in folder.glob('*') if p.is_file() and p.suffix in ('.json','.png','.jpg','.txt','.md')}
    # Resolve pnpm links into ordinary archive members; no install/network needed for replay.
    modules=ROOT/"validation/terrain-demo/node_modules"
    vendor=[]
    for name in ("three","@dimforge/rapier3d-compat"):
        for p in (modules/name).rglob('*'):
            if p.is_file() and p.suffix not in (".map",".ts"):
                vendor.append((p,"validation/terrain-demo/node_modules/"+name+"/"+str(p.relative_to(modules/name))))
                vendor.append((p,"validation/world-viewer/node_modules/"+name+"/"+str(p.relative_to(modules/name))))
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    hashes={};entries=[]
    for p in sorted(files):
        if not p.is_relative_to(ROOT):raise ValueError("Package inputs must be staged inside the workspace")
        entries.append((p,str(p.relative_to(ROOT))))
    entries+=vendor+expected_builds
    with zipfile.ZipFile(destination,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p,name in sorted(entries,key=lambda x:x[1]):
            info=zipfile.ZipInfo(name,date_time=(2026,9,6,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            data=p.read_bytes();hashes[name]=sha(p);archive.writestr(info,data)
        archive.writestr("world-bundle-manifest.json",canonical({"version":"2.0.0","files":hashes}))
    return {"path":str(destination),"sha256":sha(destination),"files":len(hashes),"bytes":destination.stat().st_size}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="action",required=True)
    for command in ("prepare","build","review"):
        p=subs.add_parser(command);p.add_argument("--config",required=True,type=Path)
        if command=="prepare":p.add_argument("--refresh-inputs",action="store_true")
        if command=="build":
            p.add_argument("--output",type=Path);p.add_argument("--offline",action="store_true",help="All builds are offline; explicit for replay scripts")
        if command=="review":p.add_argument("--port",type=int,default=18771)
    p=subs.add_parser("verify");p.add_argument("--scene",required=True,type=Path)
    p=subs.add_parser("package");p.add_argument("--config",required=True,action="append",type=Path);p.add_argument("--destination",required=True,type=Path)
    args=parser.parse_args()
    try:
        if args.action=="prepare":result=prepare_field(args.config,args.refresh_inputs)
        elif args.action=="build":
            output=build(args.config,args.output);result={"output":str(output),"verification":verify(output)}
        elif args.action=="verify":result=verify(args.scene)
        elif args.action=="review":return review_server(args.config,args.port)
        else:result=package(args.config,args.destination)
        print(json.dumps(result,indent=2))
    except (ValueError,KeyError,OSError) as e:
        parser.exit(2,f"world: {e}\n")


if __name__=="__main__":main()
