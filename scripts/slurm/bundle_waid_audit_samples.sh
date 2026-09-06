#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --job-name=herdproof-waid-bundle
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/bundle-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DATASET="$ROOT/data/waid"
AUDIT="$ROOT/audits/waid-usability.json"
OUTPUT="$ROOT/audits/waid-visual-samples.tar"
BUNDLER="$ROOT/scripts/bundle_waid_audit_samples.py"

rm -f "$OUTPUT"
python3 "$BUNDLER" "$DATASET" "$AUDIT" "$OUTPUT"
