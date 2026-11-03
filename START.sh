#!/usr/bin/env bash
cd "$(dirname "$0")/backend" || exit 1
[ -f .env ] || cp .env.example .env
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
python -m uvicorn agent_service:app --port 8001 &
AGENTS=$!
trap "kill $AGENTS" EXIT
sleep 3
python -m uvicorn main:app --port 8000
