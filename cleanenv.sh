#!/bin/bash

# Fully clean deps and rebuild to avoid conflicts with other branches

# clean node deps
nvm use 20.18.1
rm -rf node_modules
npm install --verbose

# clean python deps
rm -rf venv
python3.11 -m venv venv
source ./venv/bin/activate
pip install -r ./backend/requirements.txt

npm run build
