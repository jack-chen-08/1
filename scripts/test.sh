#!/usr/bin/env bash
# 运行测试。默认用当前环境的 python3，可用 PYTHON 覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

if [ ! -f .env ]; then
  echo "缺少 .env（请参考 .env.example），测试需要真实 PostgreSQL。" >&2
  exit 1
fi

"$PYTHON" -m pytest -q "$@"
