#!/bin/sh

./backend/open-webui-pipelines/start.sh &
./backend/cohere_proxy/start.sh &
./backend/start.sh &

wait
