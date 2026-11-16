#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo '缺少 ffmpeg：Mac 用 brew install ffmpeg；Ubuntu/Debian 用 sudo apt install ffmpeg。'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  candidate="${PYTHON:-}"
  if [[ -z "$candidate" ]]; then
    for name in python3.11 python3.12 python3.10 python3; do
      if command -v "$name" >/dev/null 2>&1 && "$name" -c 'import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,12))'; then
        candidate="$name"
        break
      fi
    done
  fi
  if [[ -z "$candidate" ]]; then
    echo '需要 Python 3.10–3.12。可用 uv venv --python 3.11 .venv 后重跑本脚本；详见 AGENTS.md。'
    exit 1
  fi
  "$candidate" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else "请使用 Python 3.10–3.12")'
  "$candidate" -m venv .venv
fi
.venv/bin/python setup_install.py "$@"
