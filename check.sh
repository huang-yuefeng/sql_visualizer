#!/bin/bash
# Frontend validation — run before every build to catch mistakes early
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ERR=0

cd "$(dirname "$0")/frontend"

echo "=== Frontend Pre-Build Checks ==="

# 1. Brace/bracket balance
check_braces() {
  local f=$1
  local o=$(grep -o '{' "$f" | wc -l)
  local c=$(grep -o '}' "$f" | wc -l)
  if [ "$o" != "$c" ]; then
    echo -e "${RED}❌ $f: braces unbalanced ($o open, $c close)${NC}"
    ERR=1
  fi
  local op=$(grep -o '(' "$f" | wc -l)
  local cp=$(grep -o ')' "$f" | wc -l)
  if [ "$op" != "$cp" ]; then
    echo -e "${RED}❌ $f: parens unbalanced ($op open, $cp close)${NC}"
    ERR=1
  fi
  local os=$(grep -o '\[' "$f" | wc -l)
  local cs=$(grep -o ']' "$f" | wc -l)
  if [ "$os" != "$cs" ]; then
    echo -e "${RED}❌ $f: brackets unbalanced ($os open, $cs close)${NC}"
    ERR=1
  fi
}

for f in src/App.jsx src/utils/graphStyles.js; do
  check_braces "$f"
done
echo -e "${GREEN}✅ Braces balanced${NC}"

# 2. Check for common mistakes
if grep -q 'cy\.add.*cy\.add' src/App.jsx; then
  echo -e "${YELLOW}⚠️  Duplicate cy.add() calls detected${NC}"
fi
if grep -q '\.position.*\.position' src/App.jsx; then
  echo -e "${YELLOW}⚠️  Duplicate position calls${NC}"
fi

# 3. Build-time syntax check (Vite/rollup catches errors at build time)
# Already covered by build check below

# 4. Check required patterns exist
REQUIRED=("script_circle" "data_lineage" "LAYOUT_OPTIONS" "cyR.current" "graph-container")
for pattern in "${REQUIRED[@]}"; do
  if ! grep -q "$pattern" src/App.jsx src/utils/graphStyles.js; then
    echo -e "${YELLOW}⚠️  Missing pattern: $pattern${NC}"
  fi
done

# 5. Build check
echo "Building..."
if npm run build 2>&1 | tail -3 | grep -q '✓ built'; then
  echo -e "${GREEN}✅ Build succeeded${NC}"
else
  echo -e "${RED}❌ Build failed${NC}"
  ERR=1
fi

# 6. Post-build: verify key selectors in output
JSFILE=$(ls dist/assets/*.js 2>/dev/null | head -1)
if [ -n "$JSFILE" ]; then
  for sel in "script_circle" "TABLE_FLOW" "data_lineage"; do
    if grep -q "$sel" "$JSFILE"; then
      echo -e "${GREEN}✅ Built JS has: $sel${NC}"
    else
      echo -e "${RED}❌ Built JS missing: $sel${NC}"
      ERR=1
    fi
  done
fi

if [ $ERR -eq 0 ]; then
  echo -e "${GREEN}=== All checks passed ===${NC}"
  exit 0
else
  echo -e "${RED}=== $ERR errors found ===${NC}"
  exit 1
fi
