#!/usr/bin/env bash
# Start backend and frontend together; Ctrl+C stops both.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
"$DIR/start_backend.sh" &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT INT TERM
"$DIR/start_frontend.sh"
