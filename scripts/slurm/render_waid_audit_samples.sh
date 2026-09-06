#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=herdproof-waid-visual
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/visual-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DATASET="$ROOT/data/waid"
AUDIT="$ROOT/audits/waid-usability.json"
OUTPUT="$ROOT/audits/waid-visual-samples"
RENDERER="$ROOT/scripts/render_waid_audit_samples.py"

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT" "$ROOT/logs"
printf 'Pinned commit: '
git -C "$DATASET" rev-parse HEAD
python3 -c 'import PIL; print("Pillow", PIL.__version__)'
python3 "$RENDERER" "$DATASET" "$AUDIT" "$OUTPUT"
find "$OUTPUT" -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
