#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --job-name=herdproof-icaerus-audit
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/audit-icaerus-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof
PYTHON="$ROOT/envs/waid-audit/bin/python"
REPORT="$ROOT/audits/icaerus-cattle.json"
MANIFEST="$ROOT/audits/icaerus-cattle-samples.json"
RENDERED="$ROOT/audits/icaerus-cattle-rendered"
rm -rf "$RENDERED"

set +e
"$PYTHON" "$ROOT/scripts/analyze_icaerus_cattle.py" \
  "$ROOT/data/icaerus-cattle-v2" "$REPORT" "$MANIFEST"
status=$?
set -e
if [[ -f "$MANIFEST" ]]; then
  "$PYTHON" "$ROOT/scripts/render_icaerus_cattle_samples.py" \
    "$ROOT/data/icaerus-cattle-v2" "$MANIFEST" "$RENDERED"
  tar -C "$ROOT/audits" -cf "$ROOT/audits/icaerus-cattle-audit.tar" \
    icaerus-cattle.json icaerus-cattle-samples.json icaerus-cattle-rendered
fi
exit "$status"
