#!/bin/bash
# CommerceOS'u başlatır: http://localhost:8002
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Sanal ortam kuruluyor..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || cp .env.example .env

PORT="${PORT:-8002}"
echo "CommerceOS → http://localhost:$PORT"
exec .venv/bin/python -W ignore -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
