#!/usr/bin/env bash
# Usage: bash training/slurm/submit.sh [prepare|smoke|train|evaluate|all] [--dry-run]
# Default: show the full submission plan. Explicit stage/all submits jobs.
# Optional: HERDPROOF_ROOT, HERDPROOF_SOURCE, HERDPROOF_GPU_GRES=gpu:a100:1,
# HERDPROOF_ACCOUNT, HERDPROOF_DEPENDENCY=<successful prerequisite job id>.
set -euo pipefail
export HERDPROOF_CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export HERDPROOF_ROOT="${HERDPROOF_ROOT:-/oscar/scratch/${USER}/herdproof}"
stage="${1:-all}"
dry=0
if [[ $# == 0 || "${2:-}" == --dry-run ]]; then dry=1; fi
case "$stage" in prepare|smoke|train|evaluate|all) ;; *) echo "Unknown stage: $stage" >&2; exit 2 ;; esac
if (( dry == 0 )); then mkdir -p "${HERDPROOF_ROOT}/logs"; fi
dependency="${HERDPROOF_DEPENDENCY:-}"
stages=("$stage")
if [[ "$stage" == all ]]; then stages=(prepare smoke train evaluate); fi
for item in "${stages[@]}"; do
    command=(sbatch --parsable --chdir="$HERDPROOF_CODE" --export=ALL
             --output="${HERDPROOF_ROOT}/logs/${item}-%A_%a.out"
             --error="${HERDPROOF_ROOT}/logs/${item}-%A_%a.err")
    if [[ -n "${HERDPROOF_ACCOUNT:-}" ]]; then command+=(--account="$HERDPROOF_ACCOUNT"); fi
    if [[ -n "$dependency" ]]; then command+=(--dependency="afterok:${dependency}" --kill-on-invalid-dep=yes); fi
    if [[ -n "${HERDPROOF_GPU_GRES:-}" ]]; then command+=(--gres="$HERDPROOF_GPU_GRES"); fi
    if [[ "$item" == train && -n "${HERDPROOF_TRAIN_ARRAY:-}" ]]; then command+=(--array="$HERDPROOF_TRAIN_ARRAY"); fi
    command+=("${HERDPROOF_CODE}/training/slurm/${item}.sh")
    if (( dry )); then
        printf '%q ' "${command[@]}"; printf '\n'
        dependency="PREVIOUS_JOB_ID"
    else
        result="$("${command[@]}")"
        dependency="${result%%;*}"
        [[ "$dependency" =~ ^[0-9]+$ ]] || { echo "Invalid sbatch response: $result" >&2; exit 1; }
        printf '%s %s\n' "$item" "$dependency" | tee -a "${HERDPROOF_ROOT}/logs/submissions.log"
    fi
done
