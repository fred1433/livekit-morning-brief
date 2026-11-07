#!/usr/bin/env bash
# One command: ./start.sh  (needs .env.local with LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY,
# and the `claude` CLI logged in on a subscription for the webhook). Open http://127.0.0.1:8303 and start the brief.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt; }
mkdir -p logs
PY=.venv/bin/python
$PY mock_api/server.py        > logs/mock_api.log 2>&1 & P1=$!
$PY claude_webhook/server.py  > logs/webhook.log  2>&1 & P2=$!
$PY web/server.py             > logs/web.log      2>&1 & P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null' EXIT
echo "Call page: http://127.0.0.1:8303   (internal API :8301, Claude webhook :8302)"
$PY agent/agent.py start
