#!/bin/bash
# Build + validate + deploy frontend + restart backend — one command.
set -e
cd "$(dirname "$0")/frontend"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo -e "${YELLOW}🔨 Building frontend...${NC}"
npm run build 2>&1 | grep '✓ built' || { echo -e "${RED}❌ Build failed${NC}"; exit 1; }

echo -e "${YELLOW}🔍 Validating selectors...${NC}"
JSFILES=(dist/assets/*.js)
if [ ${#JSFILES[@]} -eq 0 ]; then echo -e "${RED}❌ No built JS found${NC}"; exit 1; fi

FAILS=0
REQUIRED_SELECTORS=("script_circle" "TABLE_FLOW" "data_lineage" "node\\[type=" "SCHEMA" "edge\\[edge_type=" "reads_from" "writes_to")
for sel in "${REQUIRED_SELECTORS[@]}"; do
  FOUND=0
  for f in "${JSFILES[@]}"; do
    if grep -q "$sel" "$f" 2>/dev/null; then FOUND=1; break; fi
  done
  if [ $FOUND -eq 1 ]; then echo -e "  ${GREEN}✅${NC} $sel"
  else echo -e "  ${RED}❌ MISSING: $sel${NC}"; FAILS=$((FAILS+1)); fi
done
[ $FAILS -gt 0 ] && { echo -e "${RED}❌ Validation failed — $FAILS missing selector(s)${NC}"; exit 1; }

STATIC_DIR="../backend/app/static"
if [ -d "$STATIC_DIR" ] && [ "$(ls -A "$STATIC_DIR" 2>/dev/null)" ]; then
  BACKUP="${STATIC_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
  echo -e "${YELLOW}📦 Backing up static/ → $(basename "$BACKUP")${NC}"
  cp -r "$STATIC_DIR" "$BACKUP"
fi

echo -e "${YELLOW}📦 Deploying static files...${NC}"
rm -rf "$STATIC_DIR"/*
cp -r dist/* "$STATIC_DIR"/

echo -e "${YELLOW}🔄 Restarting Docker containers...${NC}"
cd "$(dirname "$0")/.."
docker compose -f docker-compose.yml restart 2>&1 || echo "Trying with sudo..." && echo huangyf | sudo -S docker compose -f docker-compose.yml restart 2>&1

echo -e "${YELLOW}⏳ Waiting for backend...${NC}"
for i in $(seq 1 15); do
  if curl -s --max-time 2 http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Backend healthy${NC}"
    VER=$(curl -s --max-time 2 http://127.0.0.1:8000/api/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    echo -e "${GREEN}✅ Version: $VER${NC}"
    echo -e "${GREEN}✅ Deploy complete — hard-refresh browser (Ctrl+Shift+R)${NC}"
    exit 0
  fi
  sleep 2
done
echo -e "${YELLOW}⚠️  Health check timeout — containers may still be starting${NC}"
