PORT="${PORT:-8080}"
lsof -ti:$PORT | xargs kill -9
uvicorn open_webui.main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload