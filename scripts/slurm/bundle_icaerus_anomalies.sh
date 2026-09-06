#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --job-name=herdproof-icaerus-anomaly
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/bundle-icaerus-anomaly-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof
DATA="$ROOT/data/icaerus-cattle-v2/Cattle_drone_images"
OUTPUT="$ROOT/audits/icaerus-cattle-anomalies.tar"
python3 - "$DATA" "$OUTPUT" <<'PY'
import pathlib, sys, tarfile
root=pathlib.Path(sys.argv[1]).resolve()
targets=[
 ('Jalogny','DJI_20230726084333_0004_V'),
 ('Mauron','DJI_20230607162832_0053_V'),
]
paths=[]
for farm, stem in targets:
 candidates=[p.resolve() for p in (root/farm).rglob(stem+'.*') if p.suffix.lower() in {'.jpg','.xml','.txt'}]
 if len(candidates) != 3: raise ValueError(f'{farm}/{stem}: expected image, XML, and YOLO; found {candidates}')
 paths.extend(candidates)
with tarfile.open(sys.argv[2],'w') as archive:
 for path in sorted(paths):
  if root not in path.parents or not path.is_file() or path.is_symlink(): raise ValueError(path)
  archive.add(path,arcname=str(path.relative_to(root)),recursive=False)
print('files',len(paths),'bytes',pathlib.Path(sys.argv[2]).stat().st_size)
PY
