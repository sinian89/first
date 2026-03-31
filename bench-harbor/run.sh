#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$ROOT/backend"
cd "$ROOT/backend"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8765}"
