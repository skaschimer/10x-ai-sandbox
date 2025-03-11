#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR" || exit

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

# Check if WEBUI_SECRET_KEY is set in the environment
if [ -z "$WEBUI_SECRET_KEY" ]; then
  WEBUI_SECRET_KEY=$(sed -n 's/^WEBUI_SECRET_KEY=//p' ../.env)
fi

WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" exec uvicorn open_webui.main:app --host "$HOST" --port "$PORT"     --forwarded-allow-ips '*'
