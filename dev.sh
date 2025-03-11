#!/bin/sh

./backend/open_webui_pipelines/dev.sh &
./backend/cohere_proxy/dev.sh &
./backend/dev.sh &

wait
