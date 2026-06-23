#!/bin/bash
# Target-machine deployment — cloud Linux server (offline, no git pull).
# The repository is manually copied (scp/rsync) to this machine before running.
# Prerequisite: Docker installed and running.
# Usage:  export ANTHROPIC_API_KEY=sk-... && ./target_deploy.sh
set -e
cd "$(dirname "$0")"

IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
IMAGE_NAME="gps-sql-visualizer"
CONTAINER_NAME="gps-sql"

echo "=== Reassemble image ==="
cd "$IMAGE_DIR"
if [ ! -f checksums.md5 ]; then echo "ERROR: checksums.md5 not found"; exit 1; fi
echo "  Verifying checksums..." && md5sum -c checksums.md5 && echo "  Checksums OK"
echo "  Joining pieces..." && cat part_* > "$(basename "$IMAGE_FILE")"
echo "  Done: $(ls -lh "$(basename "$IMAGE_FILE")" | awk '{print $5}')"
cd ..

echo "=== Stop old container ==="
if docker ps -q --filter "name=$CONTAINER_NAME" | grep -q .; then
    docker stop "$CONTAINER_NAME" && echo "  Stopped"
fi
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "=== Remove old image ==="
docker rmi "$IMAGE_NAME:latest" 2>/dev/null || true

echo "=== Load new image ===" && docker load < "$IMAGE_FILE"

echo "=== Start container ==="
docker run -d \
    -p 0.0.0.0:8000:8000 \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    "$IMAGE_NAME:latest"

echo "=== Wait for health ==="
for i in $(seq 1 15); do
    sleep 1
    if curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "  Ready ($(curl -s http://localhost:8000/api/health))"
        break
    fi
done

echo "" && echo "=== Done ==="
echo "  Local:   http://localhost:8000"
echo "  Remote:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<server-ip>'):8000"
echo "  Health:  curl http://<ip>:8000/api/health"
echo "  Logs:    docker logs $CONTAINER_NAME"
echo ""
echo "  If unreachable from other machines, check cloud firewall/security group allows TCP port 8000."
