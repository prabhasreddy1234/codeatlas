#!/usr/bin/env bash
# Starts backend (8000) and frontend (5173). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x backend/.venv/bin/python ]; then
  echo "Creating backend virtualenv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi
[ -f .env ] || echo "Warning: .env not found. Copy .env.example to .env and add GitHub OAuth credentials."

(cd backend && .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000) &
BACK=$!
(cd frontend && npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' INT TERM EXIT
echo "UI: http://localhost:5173   API: http://localhost:8000/docs"
wait
