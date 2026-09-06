#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-waid-usable
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/usability-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DATASET="$ROOT/data/waid"
OUTPUT="$ROOT/audits/waid-usability.json"
ANALYZER="$ROOT/scripts/analyze_waid_usability.py"

mkdir -p "$ROOT/audits" "$ROOT/logs"
printf 'Pinned commit: '
git -C "$DATASET" rev-parse HEAD
python3 "$ANALYZER" "$DATASET" "$OUTPUT"
