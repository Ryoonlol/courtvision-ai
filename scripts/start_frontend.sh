#!/usr/bin/env bash
# Start the CourtVision AI React dev server on http://localhost:5173 (proxies /api to :8000)
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install
exec npm run dev -- --port "${FRONTEND_PORT:-5173}" "$@"
