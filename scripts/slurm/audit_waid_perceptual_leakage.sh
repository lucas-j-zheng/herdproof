#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-waid-phash
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/phash-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
ENV="$ROOT/envs/waid-audit"
WHEEL_DIR="$ROOT/wheels"
WHEEL="$WHEEL_DIR/pillow-11.1.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
WHEEL_URL=https://files.pythonhosted.org/packages/8c/aa/7f29711f26680eab0bcd3ecdd6d23ed6bce180d82e3f6380fb7ae35fcf3b/pillow-11.1.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
WHEEL_SHA256=7fdadc077553621911f27ce206ffcbec7d3f8d7b50e0da39f10997e8e2bb7f6a
DATASET="$ROOT/data/waid"
ANALYZER="$ROOT/scripts/analyze_waid_perceptual_leakage.py"
OUTPUT="$ROOT/audits/waid-perceptual-leakage.json"

mkdir -p "$ROOT/envs" "$WHEEL_DIR" "$ROOT/audits" "$ROOT/logs"
if [[ ! -f "$WHEEL" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    "$WHEEL_URL" -o "$WHEEL.tmp"
  mv "$WHEEL.tmp" "$WHEEL"
fi
printf '%s  %s\n' "$WHEEL_SHA256" "$WHEEL" | sha256sum --check --strict

if [[ ! -x "$ENV/bin/python" ]]; then
  rm -rf "$ENV"
  python3 -m venv "$ENV"
  "$ENV/bin/python" -m pip install --no-index --no-deps "$WHEEL"
fi
"$ENV/bin/python" -c 'import PIL; assert PIL.__version__ == "11.1.0"; print("Pillow", PIL.__version__)'
printf 'Pinned dataset commit: '
git -C "$DATASET" rev-parse HEAD
"$ENV/bin/python" "$ANALYZER" "$DATASET" "$OUTPUT"
