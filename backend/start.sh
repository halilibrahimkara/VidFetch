#!/bin/bash
set -e

echo "Starting bgutil PO token provider..."
node /usr/lib/node_modules/@ybd-project/bgutil-ytdlp-pot-provider/dist/cli.js serve --port 4416 &
BGUTIL_PID=$!

echo "Waiting for bgutil to start..."
sleep 4

echo "Starting VidFetch API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
