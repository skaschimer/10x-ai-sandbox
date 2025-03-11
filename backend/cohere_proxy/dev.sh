#!/usr/bin/env bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR" || exit
lsof -ti:9101 | xargs kill -9
uvicorn proxy:app --host 0.0.0.0 --port 9101 --reload --forwarded-allow-ips '*'
