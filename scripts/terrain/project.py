"""Versioned field input contract shared by reproducible preprocessing stages."""
from pathlib import Path
import argparse, json

DEFAULT=Path(__file__).resolve().parents[2]/'validation/terrain-demo/project.json'
def load_project():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,default=DEFAULT)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    path=args.project.resolve(); data=json.loads(path.read_text())
    if data.get('schema_version')!=1:raise ValueError('Unsupported field project schema')
    if args.output:data['_output']=str(args.output.resolve())
    return path.parent,data

def resolve(base,project,key):
    return (base/project[key]).resolve()

def ray_interval(origin,direction,bounds):
    """Intersect a forward ray with the valid XY footprint before height solving."""
    lo,hi=0.,10000.
    for o,d,a,b in zip(origin,direction,bounds[::2],bounds[1::2]):
        if abs(d)<1e-12:
            if not a<=o<=b:raise ValueError('Ray outside measured footprint')
        else:
            t1,t2=sorted(((a-o)/d,(b-o)/d));lo=max(lo,t1);hi=min(hi,t2)
    if hi<=lo:raise ValueError('No forward footprint intersection')
    return lo+1e-6,hi-1e-6
