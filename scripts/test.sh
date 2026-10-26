#!/usr/bin/env bash
# Run backend unit tests and the frontend type-check/build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && .venv/bin/python -m pytest -q)
(cd "$ROOT/frontend" && npm run build)
