#!/usr/bin/env bash
#SBATCH --job-name=herdproof-train
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --array=0-1%1
set -euo pipefail
source "${HERDPROOF_CODE:?}/training/slurm/common.sh"
variants=(yolov8n yolov8s)
variant="${variants[${SLURM_ARRAY_TASK_ID:?}]}"
# Both models must pass the real CUDA smoke run before the full comparison starts.
for model in "${variants[@]}"; do
    test -f "${HERDPROOF_RUNS}/smoke-${model}/complete.json"
done
resume=()
if [[ "${HERDPROOF_RESUME:-0}" == 1 ]]; then resume=(--resume); fi
"$PYTHON" -m training.run --mode train --variant "$variant" --prepared "$HERDPROOF_PREPARED" \
    --weights "${HERDPROOF_ROOT}/weights" --runs "$HERDPROOF_RUNS" "${resume[@]}"
