"""Offline, hash-locked field builds. No network calls or implicit paid services."""
from pathlib import Path
import argparse,hashlib,json,os,platform,re,shutil,subprocess,sys,tempfile,zipfile
from importlib.metadata import version

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['lock-inputs','build','package']);parser.add_argument('--project',type=Path,default=ROOT/'validation/terrain-demo/project.json');parser.add_argument('--check-repeatability',action='store_true');args=parser.parse_args()
project_path=args.project.resolve();base=project_path.parent;p=json.loads(project_path.read_text());evidence=base/'evidence';evidence.mkdir(exist_ok=True)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
keys=['source_image','detections','terrain','reference_ortho','source_manifest','landmarks','cow_review','calibration','features','texture_masks','cow_model','cow_normal']
inputs={'project.json':project_path}
for k in keys:
    path=(base/p[k]).resolve()
    if not path.is_file():raise SystemExit(f'Missing required input {k}: {path}. Restore it or run the documented acquisition step; build never downloads implicitly.')
    inputs[os.path.relpath(path,base)]=path
fingerprint={name:sha(path) for name,path in sorted(inputs.items())}
lock=base/'inputs.lock.json'
if args.action=='lock-inputs':
    lock.write_text(json.dumps({'schema_version':1,'files':fingerprint},indent=2)+'\n');print(f'Locked {len(fingerprint)} inputs in {lock}');sys.exit()
if not lock.exists():raise SystemExit('No input lock. Review the inputs, then run lock-inputs explicitly.')
expected=json.loads(lock.read_text())['files']
if expected!=fingerprint:
    changed=[k for k in sorted(set(expected)|set(fingerprint)) if expected.get(k)!=fingerprint.get(k)]
    raise SystemExit('Input lock mismatch: '+', '.join(changed)+'. Review the change and explicitly run lock-inputs; refusing a silent replacement.')
reviews=json.loads((base/p['cow_review']).read_text())['observations']
for row in reviews:
    if row['status']=='accepted' and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',row['sceneCowId']):raise SystemExit('Unsafe or empty scene cow ID')
def run(command,log):
    result=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log.append({'command':command[0:1]+[os.path.relpath(x,ROOT) if isinstance(x,str) and x.startswith(str(ROOT)) else x for x in command[1:]],'exit_code':result.returncode,'output':result.stdout})
    if result.returncode:print(result.stdout[-3000:]);raise RuntimeError('Build stage failed: '+command[1])
def hashes(folder):return {str(f.relative_to(folder)):sha(f) for f in sorted(folder.rglob('*')) if f.is_file()}
def build_once():
    stage=Path(tempfile.mkdtemp(prefix='herdproof-field-build-',dir=base/'data'));log=[]
    try:
        run([sys.executable,str(HERE/'solve_camera.py'),'--project',str(project_path)],log)
        run([sys.executable,str(HERE/'export_scene.py'),'--project',str(project_path),'--output',str(stage)],log)
        (stage/'assets').mkdir();shutil.copy2(base/p['cow_model'],stage/'assets/cow-original.glb');shutil.copy2(base/p['cow_normal'],stage/'assets/cow-normal.png')
        run([sys.executable,str(HERE/'validate_export.py'),'--project',str(project_path),'--output',str(stage)],log)
        run(['node',str(base/'validate.mjs'),str(stage)],log)
        return stage,log
    except:
        (evidence/'failed-build.json').write_text(json.dumps(log,indent=2)+'\n');raise
if args.action=='build':
    stage,log=build_once();first=hashes(stage);repeat={'requested':args.check_repeatability}
    if args.check_repeatability:
        second,second_log=build_once();second_hashes=hashes(second);changed=[f for f in set(first)|set(second_hashes) if first.get(f)!=second_hashes.get(f)]
        repeat={'requested':True,'passed':not changed,'outputs_compared':len(first),'mismatched_files':changed,'output_sha256':first,'scope':'Two clean exports on this machine with locked inputs and runtime versions; not a cross-platform bitwise guarantee'}
        if changed:(evidence/'reproducibility.json').write_text(json.dumps(repeat,indent=2)+'\n');raise SystemExit('Non-reproducible outputs: '+', '.join(changed))
        shutil.rmtree(second)
    manifest={'schema_version':1,'input_sha256':fingerprint,'output_sha256':first,'python':platform.python_version(),'node':subprocess.check_output(['node','--version'],text=True).strip(),'packages':{k:version(k) for k in ['numpy','scipy','opencv-python-headless','rasterio','pyproj','pillow','trimesh']},'dependency_locks':{'uv':sha(HERE/'uv.lock'),'pnpm':sha(base/'pnpm-lock.yaml')},'source_sha256':{str(f.relative_to(ROOT)):sha(f) for f in sorted(list(HERE.glob('*.py'))+list(base.glob('*.js'))+list(base.glob('*.mjs')))},'repeatability':repeat}
    (stage/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    previous=base/'data'/('previous-public-'+sha(stage/'scene.json')[:12])
    if previous.exists():previous=Path(tempfile.mkdtemp(prefix='previous-public-',dir=base/'data'));previous.rmdir()
    if (base/'public').exists():os.replace(base/'public',previous)
    try:os.replace(stage,base/'public')
    except:
        if previous.exists():os.replace(previous,base/'public')
        raise
    (evidence/'build-log.json').write_text(json.dumps(log,indent=2)+'\n')
    (evidence/'reproducibility.json').write_text(json.dumps(repeat,indent=2)+'\n')
    print(f'Published validated scene: {base}/public')
    if args.check_repeatability:print(f"Repeatability passed: {len(first)} output files are byte-identical across two clean builds.")
else:
    deliver=base/'deliverables';deliver.mkdir(exist_ok=True);dest=deliver/'herdproof-terrain-demo-reproducible.zip'
    files=set(inputs.values())|set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{HERE/'pyproject.toml',HERE/'uv.lock',HERE/'.python-version',lock}
    files|={ROOT/'scripts/fetch_aerial_subset.py',ROOT/'scripts/aerial_survey.py'}
    files|={f for f in [base/'data/odm/evaluation.json',base/'data/flight/manifest.json',base/'data/ign/origin.json'] if f.exists()}
    files|={f for f in base.iterdir() if f.is_file() and f.suffix in ['.html','.css','.js','.mjs','.json','.yaml','.md']}
    files|={f for f in evidence.iterdir() if f.is_file() and f.suffix in ['.json','.md']}
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(files):z.write(f,str(f.relative_to(ROOT)))
    print(f'Portable source/input bundle: {dest} ({dest.stat().st_size/1e6:.1f} MB) SHA256 {sha(dest)}')
