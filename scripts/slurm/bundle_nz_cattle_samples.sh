#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --job-name=herdproof-nz-samples
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/bundle-nz-cattle-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof
python3 "$ROOT/scripts/bundle_nz_cattle_samples.py" \
  "$ROOT/data/nz-cattle" \
  "$ROOT/audits/nz-cattle-samples.json" \
  "$ROOT/audits/nz-cattle-samples.tar"
