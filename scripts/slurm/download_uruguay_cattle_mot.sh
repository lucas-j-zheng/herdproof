#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --job-name=herdproof-cattle-mot
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-cattle-mot-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DOWNLOADS="$ROOT/downloads"
ARCHIVE="$DOWNLOADS/uruguay-cattle-mot.zip"
PART="$ARCHIVE.part"
DESCRIPTION="$DOWNLOADS/uruguay-cattle-mot-description.pdf"
DESTINATION="$ROOT/data/uruguay-cattle-mot"
ARCHIVE_URL=https://data.mendeley.com/public-files/datasets/dk54zg67dd/files/447679ea-783a-4702-bdd8-285dab542906/file_downloaded
DESCRIPTION_URL=https://data.mendeley.com/public-files/datasets/dk54zg67dd/files/10f85eea-c352-4e28-aee8-0f209e09f05e/file_downloaded
EXPECTED_BYTES=275216868
EXPECTED_SHA256=1fcb101ac83eb917f492e00f10b8b67d912fbb1bc881e40b11713a078868e01b
DESCRIPTION_SHA256=7bb1f9cb2a69ba8cb88e5b27d1d21311b0d59b0fc51808b9a3d8abbd2eb91b79

mkdir -p "$DOWNLOADS" "$ROOT/data" "$ROOT/logs"
curl --proto '=https' --tlsv1.2 --fail --location --retry 8 --retry-all-errors \
  --connect-timeout 30 https://data.mendeley.com/public-api/datasets/dk54zg67dd/snapshot/1 \
  -o "$DOWNLOADS/mendeley-dk54zg67dd-v1.json.tmp"
mv "$DOWNLOADS/mendeley-dk54zg67dd-v1.json.tmp" "$DOWNLOADS/mendeley-dk54zg67dd-v1.json"

if [[ ! -f "$DESCRIPTION" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --retry 8 --retry-all-errors \
    --connect-timeout 30 "$DESCRIPTION_URL" -o "$DESCRIPTION.tmp"
  mv "$DESCRIPTION.tmp" "$DESCRIPTION"
fi
printf '%s  %s\n' "$DESCRIPTION_SHA256" "$DESCRIPTION" | sha256sum --check --strict

if [[ ! -f "$ARCHIVE" ]]; then
  curl --proto '=https' --tlsv1.2 --fail --location --retry 12 --retry-all-errors \
    --connect-timeout 30 --continue-at - "$ARCHIVE_URL" -o "$PART"
  mv "$PART" "$ARCHIVE"
fi
[[ "$(stat -c %s "$ARCHIVE")" == "$EXPECTED_BYTES" ]]
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum --check --strict

if [[ ! -e "$DESTINATION" ]]; then
  python3 "$ROOT/scripts/safe_extract_zip.py" "$ARCHIVE" "$DESTINATION" \
    --max-bytes $((5 * 1024 * 1024 * 1024)) --max-members 20000
else
  echo "Extraction destination already exists; archive verification completed only."
fi
