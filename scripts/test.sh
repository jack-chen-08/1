#!/usr/bin/env bash
# 一键跑测试：从 .env 注入库连接参数，然后 pytest。
# 用法：bash scripts/test.sh [pytest 参数...]
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON="${PYTHON:-python3}"
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
exec "$PYTHON" -m pytest "$@"
