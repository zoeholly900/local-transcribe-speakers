#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
if [[ ! -x "$root/.venv/bin/python" ]]; then
  echo '尚未安装：请先在仓库目录运行 ./setup.sh。'
  exit 1
fi
exec "$root/.venv/bin/python" "$root/transcribe.py" "$@"
