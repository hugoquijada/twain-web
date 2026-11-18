#!/usr/bin/env sh
set -eu

agent_directory=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
project_directory=$(CDPATH= cd -- "$agent_directory/.." && pwd)
export PYTHONPYCACHEPREFIX="$project_directory/.runtime/pycache"
mkdir -p "$PYTHONPYCACHEPREFIX"

exec python3 -m devicebridge --config "${1:-config.yaml}"
