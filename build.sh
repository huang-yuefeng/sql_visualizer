#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "=== Build ===" && docker build -t gps-sql-visualizer:latest .
echo "=== Test ===" && docker rm -f gps-test 2>/dev/null
docker run -d -p 8000:8000 -e ANTHROPIC_API_KEY=test-key --name gps-test gps-sql-visualizer:latest
for i in $(seq 1 15); do sleep 1; docker exec gps-test python3 -c "import socket;r=socket.socket().connect_ex(('127.0.0.1',8000));exit(r)" 2>/dev/null && break; done
curl -s http://127.0.0.1:8000/api/health && echo ""
python3 /tmp/gps_test_api.py
docker stop gps-test 2>/dev/null
echo "=== Export ===" && docker save gps-sql-visualizer:latest | gzip > /mnt/data/work/gps-sql-visualizer.tar.gz
ls -lh /mnt/data/work/gps-sql-visualizer.tar.gz && echo "Done."
