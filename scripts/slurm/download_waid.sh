#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --job-name=herdproof-waid
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/download-waid-%j.out

set -euo pipefail

ROOT=/oscar/scratch/lzheng35/herdproof
DEST="$ROOT/data/waid"
REPO=https://github.com/xiaohuicui/WAID.git

mkdir -p "$ROOT/data" "$ROOT/logs"

if [[ -d "$DEST/.git" ]]; then
  git -C "$DEST" pull --ff-only
else
  rm -rf "$DEST"
  git clone --depth 1 "$REPO" "$DEST"
fi

printf '\nDownloaded dataset summary:\n'
du -sh "$DEST"
printf 'Images: '
find "$DEST/WAID/images" -type f | wc -l
printf 'Labels: '
find "$DEST/WAID/labels" -type f | wc -l
printf 'Classes:\n'
cat "$DEST/WAID/classes.txt"
