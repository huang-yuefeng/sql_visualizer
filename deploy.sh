#!/bin/bash
# Build + validate + deploy — one command, no mistakes
set -e
cd "$(dirname "$0")/frontend"

echo "🔨 Building..."
npm run build 2>&1 | tail -1

echo "🔍 Validating..."
JSFILE=$(ls dist/assets/*.js | head -1)
for sel in "script_circle" "TABLE_FLOW" "data_lineage" "node\\[type="; do
  if grep -q "$sel" "$JSFILE"; then
    echo "  ✅ $sel"
  else
    echo "  ❌ MISSING: $sel"
    exit 1
  fi
done
# Check no duplicate cy.add
if [ $(grep -c 'cy\.add(' src/App.jsx) -gt 1 ]; then
  echo "  ⚠️  Multiple cy.add() calls — may cause blank graph"
fi

echo "📦 Deploying..."
rm -rf ../backend/app/static/*
cp -r dist/* ../backend/app/static/
echo "✅ Deployed — restart backend + hard-refresh"
