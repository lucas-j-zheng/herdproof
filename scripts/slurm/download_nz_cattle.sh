#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-nz-cattle
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-nz-cattle-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DOWNLOADS="$ROOT/downloads"
ARCHIVE="$DOWNLOADS/nz-cattle-images.zip"
PART="$ARCHIVE.part"
DESTINATION="$ROOT/data/nz-cattle"
METADATA="$DOWNLOADS/zenodo-5908869.json"
URL=https://zenodo.org/api/records/5908869/files/images.zip/content
EXPECTED_BYTES=273621406
EXPECTED_MD5=da6d596c3a9a0ca7a220c604b5c85580

mkdir -p "$DOWNLOADS" "$ROOT/data" "$ROOT/logs"
curl --proto '=https' --tlsv1.2 --fail --location --retry 8 --retry-all-errors \
  --connect-timeout 30 https://zenodo.org/api/records/5908869 -o "$METADATA.tmp"
mv "$METADATA.tmp" "$METADATA"

if [[ ! -f "$ARCHIVE" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --retry 12 --retry-all-errors \
    --connect-timeout 30 --continue-at - "$URL" -o "$PART"
  mv "$PART" "$ARCHIVE"
fi
[[ "$(stat -c %s "$ARCHIVE")" == "$EXPECTED_BYTES" ]]
printf '%s  %s\n' "$EXPECTED_MD5" "$ARCHIVE" | md5sum --check --strict

if [[ ! -e "$DESTINATION" ]]; then
  python3 "$ROOT/scripts/safe_extract_zip.py" "$ARCHIVE" "$DESTINATION" \
    --max-bytes $((4 * 1024 * 1024 * 1024)) --max-members 20000
else
  echo "Extraction destination already exists; archive verification completed only."
fi
