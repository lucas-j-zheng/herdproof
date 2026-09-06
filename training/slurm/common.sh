#!/usr/bin/env bash
set -euo pipefail
: "${SLURM_JOB_ID:?Heavy work must run within a SLURM job}"
: "${HERDPROOF_CODE:?Use training/slurm/submit.sh to set the checkout path}"
export HERDPROOF_ROOT="${HERDPROOF_ROOT:-/oscar/scratch/${USER}/herdproof}"
export HERDPROOF_SOURCE="${HERDPROOF_SOURCE:-${HERDPROOF_ROOT}/data/icaerus-cattle-v2}"
export HERDPROOF_PREPARED="${HERDPROOF_PREPARED:-${HERDPROOF_ROOT}/native1024-v1}"
export HERDPROOF_RUNS="${HERDPROOF_RUNS:-${HERDPROOF_ROOT}/runs/native1024-v2}"
export HERDPROOF_ENV="${HERDPROOF_ENV:-${HERDPROOF_ROOT}/envs/native1024-cu126}"
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-4}"
export MPLCONFIGDIR="${HERDPROOF_ROOT}/cache/matplotlib"
export YOLO_CONFIG_DIR="${HERDPROOF_ROOT}/cache/ultralytics"
export YOLO_AUTOINSTALL=false
export YOLO_OFFLINE=true
cd "$HERDPROOF_CODE"
PYTHON="${HERDPROOF_ENV}/bin/python"
