#!/bin/bash
set -e
cd "$(dirname "$0")"
# Build frontend
cd frontend && ./node_modules/.bin/vite build --logLevel warn
cd ..
# Stamp real VERSION into the built index.html (cache-busting ?v=)
VERSION=$(cat VERSION 2>/dev/null | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
    echo "❌ VERSION file missing or empty — aborting deploy" >&2
    exit 1
fi
VERSION_SED=$(printf '%s' "$VERSION" | sed 's/[&\\|]/\\&/g')
sed -i -E 's|(<meta name="version" content=")[^"]*(")|\1'"$VERSION_SED"'\2|' frontend/dist/index.html
if ! grep -qF -- "name=\"version\" content=\"${VERSION}\"" frontend/dist/index.html; then
    echo "❌ Failed to stamp v$VERSION into frontend/dist/index.html" >&2
    exit 1
fi
echo "✅ Stamped v$VERSION into frontend/dist/index.html"
# Copy built files
rm -rf backend/app/static/*
cp -r frontend/dist/* backend/app/static/
# Copy elk.bundled.js for pipeline layout
cp frontend/node_modules/elkjs/lib/elk.bundled.js backend/app/static/elk.bundled.js
# Restart docker
docker compose restart
echo "✅ Deployed $(cat VERSION)"
