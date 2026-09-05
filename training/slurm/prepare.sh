#!/usr/bin/env bash
#SBATCH --job-name=herdproof-prepare
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=06:00:00
set -euo pipefail
source "${HERDPROOF_CODE:?}/training/slurm/common.sh"

# Per project policy, even preparation runs within the gpu partition, never on a login node.
if [[ -z "${HERDPROOF_BASE_PYTHON:-}" ]]; then
    module load "${HERDPROOF_PYTHON_MODULE:-miniforge3/25.3.0-3-a6hh}"
    HERDPROOF_BASE_PYTHON="$(command -v python)"
fi
"$HERDPROOF_BASE_PYTHON" -c 'import sys, platform; assert sys.version_info[:2] == (3, 12), "Choose a Python 3.12 module via HERDPROOF_BASE_PYTHON"; assert platform.system() == "Linux" and platform.machine() == "x86_64"'
mkdir -p "${HERDPROOF_ROOT}/cache/pip" "$(dirname "$HERDPROOF_ENV")"
export PIP_CACHE_DIR="${HERDPROOF_ROOT}/cache/pip"
export PIP_DISABLE_PIP_VERSION_CHECK=1
LOCK="${HERDPROOF_CODE}/training/environment/requirements-cu126.lock"
if [[ -e "${HERDPROOF_ENV}/herdproof-requirements.lock" ]]; then
    cmp "$LOCK" "${HERDPROOF_ENV}/herdproof-requirements.lock"
else
    if [[ ! -x "$PYTHON" ]]; then "$HERDPROOF_BASE_PYTHON" -m venv "$HERDPROOF_ENV"; fi
    "$PYTHON" -m pip install --require-hashes --only-binary=:all: -r "$LOCK"
    cp "$LOCK" "${HERDPROOF_ENV}/herdproof-requirements.lock"
fi
"$PYTHON" -m pip check
"$PYTHON" -m training.fetch --root "$HERDPROOF_ROOT" --source "$HERDPROOF_SOURCE"
if [[ -e "$HERDPROOF_PREPARED" ]]; then
    "$PYTHON" -c 'import os; from pathlib import Path; from training.common import PACKAGE, verify_prepared; verify_prepared(Path(os.environ["HERDPROOF_PREPARED"]), PACKAGE / "config.json"); print("Existing prepared dataset verified")'
else
    "$PYTHON" -m training.data --source "$HERDPROOF_SOURCE" --output "$HERDPROOF_PREPARED"
fi
