PORT="${PORT:-9099}"
lsof -ti:$PORT | xargs kill -9
uvicorn main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload