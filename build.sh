#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== Building Docker image ==="
docker build -t gps-sql-visualizer:latest .

echo "=== Starting test container ==="
docker rm -f gps-test 2>/dev/null
docker run -d -p 8000:8000 -e ANTHROPIC_API_KEY=test-key --name gps-test gps-sql-visualizer:latest

echo "=== Waiting for server ==="
for i in $(seq 1 15); do
    sleep 1
    if docker exec gps-test python3 -c "import socket;r=socket.socket().connect_ex(('127.0.0.1',8000));exit(r)" 2>/dev/null; then
        echo "Ready in ${i}s"
        break
    fi
done

echo "=== Health check ==="
curl -s http://127.0.0.1:8000/api/health
echo ""

echo "=== Running API tests ==="
python3 /tmp/gps_test_api.py

echo "=== Stopping container ==="
docker stop gps-test 2>/dev/null

echo "=== Exporting image ==="
docker save gps-sql-visualizer:latest | gzip > /mnt/data/work/gps-sql-visualizer.tar.gz
ls -lh /mnt/data/work/gps-sql-visualizer.tar.gz

echo "=== Done ==="
