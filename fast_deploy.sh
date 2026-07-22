#!/bin/bash
set -e
cd "$(dirname "$0")"
# Build frontend
cd frontend && npx vite build --logLevel warn
cd ..
# Copy built files
rm -rf backend/app/static/*
cp -r frontend/dist/* backend/app/static/
# Copy elk.bundled.js for pipeline layout
cp frontend/node_modules/elkjs/lib/elk.bundled.js backend/app/static/elk.bundled.js
# Restart docker
docker compose restart
echo "✅ Deployed $(cat VERSION)"
