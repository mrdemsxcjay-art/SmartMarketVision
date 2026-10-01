#!/usr/bin/env bash
# Start the API + dashboard (serves the built frontend at /app).
set -e
cd "$(dirname "$0")"
exec python3 -m uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
