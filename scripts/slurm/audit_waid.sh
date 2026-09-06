#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-waid-audit
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/audit-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DATASET="$ROOT/data/waid"
AUDIT="$ROOT/audits/waid-validation.json"
VALIDATOR="$ROOT/scripts/validate_waid.py"

mkdir -p "$ROOT/audits" "$ROOT/logs"

# Verify Git's content-addressed object graph before reading working-tree data.
git -C "$DATASET" fsck --full --strict
git -C "$DATASET" status --short
printf 'Pinned commit: '
git -C "$DATASET" rev-parse HEAD

# This validator uses only Python's standard library. It parses bounded JPEG
# headers and YOLO text; it does not execute repository files or decode pixels.
python3 "$VALIDATOR" "$DATASET" "$AUDIT"
