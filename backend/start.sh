#!/usr/bin/env bash

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR" || exit

# Function to check if a port is in use
is_port_in_use() {
  lsof -i :"$1" >/dev/null
}

# # Check if port 9100 is in use
# if is_port_in_use 9100; then
#   echo "POD [$HOSTNAME] - Port 9100 is already in use. Skipping cohere proxy start." >&2
# else
#   ./azure_proxy/start.sh &
# fi

# Check if port 9101 is in use
if is_port_in_use 9101; then
  echo "POD [$HOSTNAME] - Port 9101 is already in use. Skipping cohere proxy start." >&2
else
  ./cohere_proxy/start.sh &
fi

# Check if port 9099 is in use
if is_port_in_use 9099; then
  echo "POD [$HOSTNAME] - Port 9099 is already in use. Skipping open webui pipelines server start." >&2
else
  ./open-webui-pipelines/start.sh &
fi

KEY_FILE=.webui_secret_key

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

if test "$WEBUI_SECRET_KEY $WEBUI_JWT_SECRET_KEY" = " "; then
  echo "Loading WEBUI_SECRET_KEY from file, not provided as an environment variable."

  if ! [ -e "$KEY_FILE" ]; then
    echo "Generating WEBUI_SECRET_KEY"
    # Generate a random value to use as a WEBUI_SECRET_KEY in case the user didn't provide one.
    echo $(openssl rand -base64 24) >"$KEY_FILE"
  fi

  echo "Loading WEBUI_SECRET_KEY from $KEY_FILE"
  WEBUI_SECRET_KEY=$(cat "$KEY_FILE")
fi

WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" exec uvicorn open_webui.main:app --host "$HOST" --port "$PORT" --forwarded-allow-ips '*'
