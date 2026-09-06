#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:10:00
#SBATCH --job-name=herdproof-icaerus-inspect
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/inspect-icaerus-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof/data/icaerus-cattle-v2
python3 - "$ROOT" <<'PY'
from collections import Counter
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
files=sorted(p for p in root.rglob('*') if p.is_file() and p.name != '.safe-extraction.json')
dirs=sorted(p for p in root.rglob('*') if p.is_dir())
print('directory names',Counter(p.name for p in dirs))
for suffix in ['.jpg','.txt','.xml','.data','.names','.xlsx']:
 xs=[p for p in files if p.suffix.lower()==suffix]
 print(f'--- {suffix}: {len(xs)} ---')
 for p in xs[:20]:print(p.relative_to(root))
 if suffix in {'.txt','.xml','.data','.names'}:
  for p in xs[:2]:
   print(f'CONTENT {p.relative_to(root)}')
   print(p.read_text(errors='replace')[:3000])
PY
