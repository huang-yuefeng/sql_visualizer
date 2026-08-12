#!/bin/bash
# Build, test, and export the Docker image.
# Prerequisites: Docker, python3 with requests module.
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'

echo "=== Build ==="
docker build -t gps-sql-visualizer:latest .

echo "=== Start container ==="
docker rm -f gps-test 2>/dev/null || true
docker run -d -p 8000:8000 --name gps-test gps-sql-visualizer:latest

# Wait for health
echo -n "  Waiting for healthy..."
for i in $(seq 1 20); do
    sleep 1
    if docker exec gps-test python3 -c "import socket;r=socket.socket().connect_ex(('127.0.0.1',8000));exit(r)" 2>/dev/null; then
        echo " ready"
        break
    fi
    echo -n "."
done

# Health check
echo "=== Health ==="
curl -sf http://127.0.0.1:8000/api/health && echo ""

# Run full pytest suite inside the container
echo "=== Pytest Suite ==="
docker exec gps-test python3 -m pytest backend/tests/ -q --tb=short 2>&1 || {
    echo -e "${RED}❌ Tests failed${NC}"
    docker stop gps-test 2>/dev/null || true
    exit 1
}
echo -e "${GREEN}✅ All tests passed${NC}"

# API smoke test
echo "=== API Smoke Test ==="
python3 tools/gps_test_api.py || {
    echo -e "${RED}❌ API tests failed${NC}"
    docker stop gps-test 2>/dev/null || true
    exit 1
}

# Cleanup
docker stop gps-test 2>/dev/null || true

# Export
EXPORT_PATH="${EXPORT_PATH:-/mnt/data/work/gps-sql-visualizer.tar.gz}"
EXPORT_DIR=$(dirname "$EXPORT_PATH")
mkdir -p "$EXPORT_DIR"
echo "=== Export ==="
docker save gps-sql-visualizer:latest | gzip > "$EXPORT_PATH"
ls -lh "$EXPORT_PATH"
echo -e "${GREEN}Done.${NC} ($EXPORT_PATH)"
