#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=herdproof-nz-audit
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/audit-nz-cattle-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof
"$ROOT/envs/waid-audit/bin/python" "$ROOT/scripts/analyze_nz_cattle.py" \
  "$ROOT/data/nz-cattle" \
  "$ROOT/audits/nz-cattle.json" \
  "$ROOT/audits/nz-cattle-samples.json"
