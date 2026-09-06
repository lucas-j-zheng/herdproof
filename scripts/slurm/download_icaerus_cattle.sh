#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=06:00:00
#SBATCH --job-name=herdproof-icaerus
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-icaerus-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DOWNLOADS="$ROOT/downloads"
ARCHIVE="$DOWNLOADS/Cattle_drone_images_042024.zip"
PART="$ARCHIVE.part"
DESTINATION="$ROOT/data/icaerus-cattle-v2"
METADATA="$DOWNLOADS/zenodo-11048412.json"
URL=https://zenodo.org/api/records/11048412/files/Cattle_drone_images_042024.zip/content
EXPECTED_BYTES=16586848207
EXPECTED_MD5=c18911fb11cb58741b9cfa16516ca8cd

mkdir -p "$DOWNLOADS" "$ROOT/data" "$ROOT/logs"
curl --proto '=https' --tlsv1.2 --fail --location --retry 8 --retry-all-errors \
  --connect-timeout 30 https://zenodo.org/api/records/11048412 -o "$METADATA.tmp"
mv "$METADATA.tmp" "$METADATA"

if [[ ! -f "$ARCHIVE" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --retry 20 --retry-all-errors \
    --connect-timeout 30 --continue-at - "$URL" -o "$PART"
  mv "$PART" "$ARCHIVE"
fi
[[ "$(stat -c %s "$ARCHIVE")" == "$EXPECTED_BYTES" ]]
printf '%s  %s\n' "$EXPECTED_MD5" "$ARCHIVE" | md5sum --check --strict

if [[ ! -e "$DESTINATION" ]]; then
  python3 "$ROOT/scripts/safe_extract_zip.py" "$ARCHIVE" "$DESTINATION" \
    --max-bytes $((100 * 1024 * 1024 * 1024)) --max-members 100000
else
  echo "Extraction destination already exists; archive verification completed only."
fi
