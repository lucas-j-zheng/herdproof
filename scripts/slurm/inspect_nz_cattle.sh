#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --job-name=herdproof-nz-inspect
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/inspect-nz-cattle-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof/data/nz-cattle

python3 - "$ROOT" <<'PY'
from collections import Counter
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
files = sorted(path for path in root.rglob('*') if path.is_file() and path.name != '.safe-extraction.json')
print('files', len(files))
print('extensions', Counter(path.suffix.lower() for path in files))
print('first paths')
for path in files[:30]: print(path.relative_to(root))
for name in ('Metadata.txt', 'license.txt'):
    path = root / name
    print(f'--- {name} ---')
    print(path.read_text(errors='replace')[:10000])
labels = [path for path in files if path.suffix.lower() == '.txt' and path.name not in {'Metadata.txt', 'license.txt'}]
print('label files', len(labels))
for path in labels[:5]:
    print(f'--- {path.relative_to(root)} ---')
    print(path.read_text(errors='replace')[:3000])
PY
