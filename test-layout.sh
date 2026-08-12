#!/bin/bash
# Fast layout verification via curl (direct to backend)
# Requires: backend container restarted with latest code
# Usage: ./test-layout.sh [ws_id] [table] [field]
set -e
BASE="${API_BASE:-http://127.0.0.1:8000}"
WS_ID="${1:-}"
TABLE="${2:-crm_customers}"
FIELD="${3:-customer_id}"

if [ -z "$WS_ID" ]; then
  echo "Usage: ./test-layout.sh <ws_id> [table] [field]"
  echo "  ws_id: from a fresh upload (auto-creates if empty but needs curl access)"
  echo "  If curl to backend fails, use: API_BASE=http://localhost:5173 ./test-layout.sh ..."
  exit 1
fi

echo "=== Layout Test ==="
echo "API:  $BASE"
echo "WS:   $WS_ID"
echo "Query: $TABLE.$FIELD"
echo ""

RESULT=$(curl -s --connect-timeout 5 -X POST "$BASE/api/workspace/$WS_ID/debug/graph" \
  -H "Content-Type: application/json" \
  -d "{\"table\": \"$TABLE\", \"field\": \"$FIELD\"}")

if [ $? -ne 0 ] || [ -z "$RESULT" ]; then
  echo "❌ Backend not reachable at $BASE"
  echo "   The backend container may need restart: docker compose restart backend"
  echo "   Or use Vite proxy: API_BASE=http://localhost:5173 ./test-layout.sh $WS_ID"
  exit 1
fi

python3 - "$RESULT" << 'PYEOF'
import json, sys
data = json.loads(sys.argv[1])

if "detail" in data:
    print(f"❌ API error: {data['detail']}")
    sys.exit(1)

deps = data.get("duplicate_warnings", [])
if deps:
    print(f"❌ DUPLICATE WARNINGS: {len(deps)}")
    for d in deps: print(f"   {d}")
else:
    print("✅ No duplicate fields detected")

bad = sum(1 for b in data.get("field_bounds_check", []) if not b["inside"])
total = len(data.get("field_bounds_check", []))
if total == 0:
    print("⚠️  No field bounds data (endpoint may not be available yet — restart backend container)")
    sys.exit(0)

print(f"\n📊 L1: {len(data['l1']['tables'])} tables, {len(data['l1']['scripts'])} scripts, "
      f"{len(data['l1']['edges'])} edges, {total} fields")

for t in data["l1"]["tables"]:
    inside = sum(1 for b in data["field_bounds_check"] if b["table_id"]==t["id"] and b["inside"])
    print(f"   {t['label']}: h={t['height']}px, {inside}/{t['field_count']} fields inside")

if bad > 0:
    print(f"\n❌ FIELDS OUTSIDE: {bad}/{total}")
    for b in data["field_bounds_check"]:
        if not b["inside"]:
            print(f"   {b['label']} in {b['table_label']}: y={b['field_abs_y']}")
    sys.exit(1)
else:
    print(f"\n✅ All {total} fields inside table bounds")
print("\n🎉 PASSED")
PYEOF
