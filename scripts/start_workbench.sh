#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked --python 3.12
npm --prefix frontend ci
npm --prefix frontend run build
exec uv run --locked office-workbench "$@"
