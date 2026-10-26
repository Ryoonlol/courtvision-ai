#!/usr/bin/env bash
# Start the CourtVision AI FastAPI backend on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -d .venv ]; then
  echo "Creating Python virtual environment..."
  PY=${PYTHON:-python3}
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
