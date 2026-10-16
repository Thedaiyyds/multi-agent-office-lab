#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# A separate database and material directory keep rehearsals away from normal work.
exec bash scripts/start_workbench.sh --port 8530 --data-dir "$PWD/outputs/demo" "$@"
