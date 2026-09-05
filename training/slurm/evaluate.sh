#!/usr/bin/env bash
#SBATCH --job-name=herdproof-eval
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=06:00:00
set -euo pipefail
source "${HERDPROOF_CODE:?}/training/slurm/common.sh"
for stage in select test; do
    "$PYTHON" -m training.evaluate "$stage" --source "$HERDPROOF_SOURCE" --prepared "$HERDPROOF_PREPARED" \
        --runs "$HERDPROOF_RUNS" --output "${HERDPROOF_RUNS}/evaluation"
done
