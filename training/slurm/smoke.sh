#!/usr/bin/env bash
#SBATCH --job-name=herdproof-smoke
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
set -euo pipefail
source "${HERDPROOF_CODE:?}/training/slurm/common.sh"
for variant in yolov8n yolov8s; do
    "$PYTHON" -m training.run --mode smoke --variant "$variant" --prepared "$HERDPROOF_PREPARED" \
        --weights "${HERDPROOF_ROOT}/weights" --runs "$HERDPROOF_RUNS" --resume-if-needed
done
