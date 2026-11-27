#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m pytest -q
$PY scripts/demo_offline.py > /dev/null
echo "ALL GREEN"
