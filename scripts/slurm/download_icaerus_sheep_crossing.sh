#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-sheep-cross
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-sheep-cross-%j.out

set -euo pipefail
ROOT=/oscar/scratch/lzheng35/herdproof
DOWNLOADS="$ROOT/downloads"
ARCHIVE="$DOWNLOADS/icaerus-sheep-crossing.zip"
PART="$ARCHIVE.part"
DESTINATION="$ROOT/data/icaerus-sheep-crossing"
URL=https://zenodo.org/api/records/12094356/files/Sheep_video_annotations_datasets.zip/content
EXPECTED_BYTES=157760285
EXPECTED_MD5=1ec2048d4975f5d68e04c3229cb03d40
mkdir -p "$DOWNLOADS" "$ROOT/data" "$ROOT/logs"
curl --proto '=https' --tlsv1.2 --fail --location --retry 8 --retry-all-errors \
  --connect-timeout 30 https://zenodo.org/api/records/12094356 \
  -o "$DOWNLOADS/zenodo-12094356.json.tmp"
mv "$DOWNLOADS/zenodo-12094356.json.tmp" "$DOWNLOADS/zenodo-12094356.json"
if [[ ! -f "$ARCHIVE" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --retry 12 --retry-all-errors \
    --connect-timeout 30 --continue-at - "$URL" -o "$PART"
  mv "$PART" "$ARCHIVE"
fi
[[ "$(stat -c %s "$ARCHIVE")" == "$EXPECTED_BYTES" ]]
printf '%s  %s\n' "$EXPECTED_MD5" "$ARCHIVE" | md5sum --check --strict
if [[ ! -e "$DESTINATION" ]]; then
  python3 "$ROOT/scripts/safe_extract_zip.py" "$ARCHIVE" "$DESTINATION" \
    --max-bytes $((5 * 1024 * 1024 * 1024)) --max-members 100000
else
  echo "Extraction destination already exists; archive verification completed only."
fi
