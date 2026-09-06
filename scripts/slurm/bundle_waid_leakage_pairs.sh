#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --job-name=herdproof-waid-pairs
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/bundle-pairs-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
OUTPUT="$ROOT/audits/waid-leakage-pairs.tar"
rm -f "$OUTPUT"
python3 "$ROOT/scripts/bundle_waid_leakage_pairs.py" \
  "$ROOT/data/waid" \
  "$ROOT/audits/waid-perceptual-leakage.json" \
  "$OUTPUT"
