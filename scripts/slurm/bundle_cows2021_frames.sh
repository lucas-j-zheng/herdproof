#!/usr/bin/env bash
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --job-name=herdproof-cows21-frames
#SBATCH --output=/oscar/scratch/lzheng35/herdproof/logs/bundle-cows21-frames-%j.out

set -euo pipefail
module load ffmpeg/7.1-7dmq
ROOT=/oscar/scratch/lzheng35/herdproof
DATA="$ROOT/data/cows2021-video-sample"
OUTPUT="$ROOT/audits/cows2021-video-sample-frames"
rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"
for video in "$DATA"/*.avi; do
  name=$(basename "$video" .avi)
  ffmpeg -v error -ss 2.7 -i "$video" -frames:v 1 -q:v 2 "$OUTPUT/$name.jpg"
done
tar -C "$ROOT/audits" -cf "$ROOT/audits/cows2021-video-sample-frames.tar" \
  cows2021-video-sample.json cows2021-video-sample-frames
