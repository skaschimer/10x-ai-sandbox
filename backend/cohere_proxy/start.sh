#!/usr/bin/env bash
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR" || exit

ddtrace-run uvicorn proxy:app --host 0.0.0.0 --port 9101 --forwarded-allow-ips '*'
