#!/bin/bash
# Frontend validation — run before every build to catch mistakes early
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
FAILS=0

cd "$(dirname "$0")/frontend"

echo "=== Frontend Pre-Build Checks ==="

# 1. Brace/bracket balance — auto-discover all JSX/JS files in src/
check_braces() {
  local f=$1
  local o=$(grep -o '{' "$f" | wc -l)
  local c=$(grep -o '}' "$f" | wc -l)
  if [ "$o" != "$c" ]; then
    echo -e "${RED}❌ $f: braces unbalanced ($o open, $c close)${NC}"
    FAILS=$((FAILS + 1))
  fi
  local op=$(grep -o '(' "$f" | wc -l)
  local cp=$(grep -o ')' "$f" | wc -l)
  if [ "$op" != "$cp" ]; then
    echo -e "${RED}❌ $f: parens unbalanced ($op open, $cp close)${NC}"
    FAILS=$((FAILS + 1))
  fi
  local os=$(grep -o '\[' "$f" | wc -l)
  local cs=$(grep -o ']' "$f" | wc -l)
  if [ "$os" != "$cs" ]; then
    echo -e "${RED}❌ $f: brackets unbalanced ($os open, $cs close)${NC}"
    FAILS=$((FAILS + 1))
  fi
}

# Auto-discover all source files (not just hardcoded list)
SRC_FILES=$(find src -name '*.jsx' -o -name '*.js' | sort)
FILE_COUNT=0
for f in $SRC_FILES; do
  check_braces "$f"
  FILE_COUNT=$((FILE_COUNT + 1))
done
echo -e "${GREEN}✅ Braces balanced across $FILE_COUNT files${NC}"

# 2. Check for common mistakes
if grep -q 'cy\.add.*cy\.add' src/App.jsx; then
  echo -e "${YELLOW}⚠️  Duplicate cy.add() calls detected${NC}"
fi
if grep -q '\.position.*\.position' src/App.jsx; then
  echo -e "${YELLOW}⚠️  Duplicate position calls${NC}"
fi

# 3. Check required patterns exist
REQUIRED=("script_circle" "data_lineage" "LAYOUT_OPTIONS" "cyR.current" "graph-container")
for pattern in "${REQUIRED[@]}"; do
  if ! grep -q "$pattern" $SRC_FILES; then
    echo -e "${YELLOW}⚠️  Missing pattern: $pattern${NC}"
  fi
done

# 4. Build check
echo "Building..."
if npm run build 2>&1 | grep -q '✓ built'; then
  echo -e "${GREEN}✅ Build succeeded${NC}"
else
  echo -e "${RED}❌ Build failed${NC}"
  FAILS=$((FAILS + 1))
fi

# 5. Post-build: verify key selectors in output
JSFILE=$(ls dist/assets/*.js 2>/dev/null | head -1)
if [ -n "$JSFILE" ]; then
  for sel in "script_circle" "TABLE_FLOW" "data_lineage"; do
    if grep -q "$sel" "$JSFILE"; then
      echo -e "${GREEN}✅ Built JS has: $sel${NC}"
    else
      echo -e "${RED}❌ Built JS missing: $sel${NC}"
      FAILS=$((FAILS + 1))
    fi
  done
fi

if [ $FAILS -eq 0 ]; then
  echo -e "${GREEN}=== All checks passed ===${NC}"
  exit 0
else
  echo -e "${RED}=== $FAILS error(s) found ===${NC}"
  exit 1
fi
