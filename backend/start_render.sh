#!/usr/bin/env bash
# Runs the agent service (internal, 8001) and the Coordinator (public, $PORT) in ONE Render web service.
python -m uvicorn agent_service:app --host 127.0.0.1 --port 8001 &
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
