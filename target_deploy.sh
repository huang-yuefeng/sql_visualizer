#!/bin/bash
# Target-machine deployment with rollback on failure.
# Prerequisites: Docker installed, image pieces in docker_image/.
# Usage:  export ANTHROPIC_API_KEY=sk-... && ./target_deploy.sh
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
IMAGE_NAME="gps-sql-visualizer"
CONTAINER_NAME="gps-sql"
ROLLBACK_TAG="previous"

ROLLBACK_NEEDED=false

rollback() {
    echo -e "\n${RED}=== ROLLBACK ===${NC}"
    echo "  Something failed — reverting to previous image..."

    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true

    if docker image inspect "${IMAGE_NAME}:${ROLLBACK_TAG}" &>/dev/null; then
        echo "  Re-tagging previous → latest"
        docker tag "${IMAGE_NAME}:${ROLLBACK_TAG}" "${IMAGE_NAME}:latest"
        docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

        docker run -d \
            -p 0.0.0.0:8000:8000 \
            -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
            --name "$CONTAINER_NAME" \
            --restart unless-stopped \
            "${IMAGE_NAME}:latest"
        echo -e "${GREEN}  Rolled back to previous image${NC}"
    else
        echo -e "${RED}  No previous image found — manual intervention required${NC}"
    fi
    exit 1
}

# ── 1. Reassemble image ─────────────────────────────────────────────
echo "=== Reassemble image ==="
cd "$IMAGE_DIR"
if [ ! -f checksums.md5 ]; then
    echo -e "${RED}ERROR: checksums.md5 not found${NC}"
    exit 1
fi
echo "  Verifying checksums..."
if md5sum -c checksums.md5; then
    echo -e "${GREEN}  Checksums OK${NC}"
else
    echo -e "${RED}  Checksum verification FAILED${NC}"
    exit 1
fi
echo "  Joining pieces..."
cat part_* > "$(basename "$IMAGE_FILE")"
echo "  Done: $(ls -lh "$(basename "$IMAGE_FILE")" | awk '{print $5}')"
cd ..

# ── 2. Tag current as previous (for rollback) ────────────────────────
echo "=== Tag current → previous ==="
if docker image inspect "${IMAGE_NAME}:latest" &>/dev/null; then
    docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true
    docker tag "${IMAGE_NAME}:latest" "${IMAGE_NAME}:${ROLLBACK_TAG}"
    echo "  Tagged ${IMAGE_NAME}:latest → ${IMAGE_NAME}:${ROLLBACK_TAG}"
else
    echo "  No existing image (first deploy)"
fi

# ── 3. Stop old container ───────────────────────────────────────────
echo "=== Stop old container ==="
if docker ps -q --filter "name=$CONTAINER_NAME" | grep -q .; then
    docker stop "$CONTAINER_NAME" && echo "  Stopped"
fi
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# ── 4. Remove old image, load new ───────────────────────────────────
echo "=== Load new image ==="
docker rmi "${IMAGE_NAME}:latest" 2>/dev/null || true
docker load < "$IMAGE_FILE" || rollback

# ── 5. Start container ──────────────────────────────────────────────
echo "=== Start container ==="
docker run -d \
    -p 0.0.0.0:8000:8000 \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    "${IMAGE_NAME}:latest" || rollback

# ── 6. Detect server IP ────────────────────────────────────────────
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP=$(ip route get 1 2>/dev/null | awk '{print $7;exit}') 
fi
[ -z "$SERVER_IP" ] && SERVER_IP="<server-ip>"

# ── 7. Health check with extended timeout ────────────────────────────
echo "=== Health check ==="
HEALTHY=false
for i in $(seq 1 30); do
    sleep 2
    if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        echo -e "  ${GREEN}Ready${NC} ($(curl -s http://127.0.0.1:8000/api/health))"
        HEALTHY=true
        break
    fi
    echo -n "."
done

if [ "$HEALTHY" = false ]; then
    echo -e "\n${RED}  Health check FAILED after 60s${NC}"
    rollback
fi

# ── 8. Cleanup old rollback tag (deploy succeeded) ───────────────────
docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

# ── 9. Show summary ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Deployed Successfully ===${NC}"
echo "  Access:  http://${SERVER_IP}:8000"
echo "  Health:  curl http://${SERVER_IP}:8000/api/health"
echo "  Logs:    docker logs $CONTAINER_NAME"
echo ""
echo "  If unreachable from other machines, check firewall allows TCP port 8000."
