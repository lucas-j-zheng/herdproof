#!/bin/sh
set -eu
terrain_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
terrain_repo_dir=$(CDPATH= cd -- "$terrain_script_dir/../.." && pwd)
terrain_python="$terrain_script_dir/.venv/bin/python"
terrain_action=${1:-build}
if [ "$#" -gt 0 ]; then shift; fi
case "$terrain_action" in
  setup)
    uv sync --project "$terrain_script_dir" --python 3.12.11 --frozen
    cd "$terrain_repo_dir/validation/terrain-demo"
    pnpm install --frozen-lockfile --ignore-scripts
    ;;
  serve)
    cd "$terrain_repo_dir/validation/terrain-demo"
    exec pnpm run serve
    ;;
  build|lock-inputs|package)
    if [ ! -x "$terrain_python" ]; then
      echo 'Run scripts/terrain/demo.sh setup first.' >&2
      exit 1
    fi
    exec "$terrain_python" "$terrain_script_dir/pipeline.py" "$terrain_action" "$@"
    ;;
  *) echo 'Usage: demo.sh setup|build [--check-repeatability] [--project FILE]|serve|package|lock-inputs' >&2; exit 1 ;;
esac
