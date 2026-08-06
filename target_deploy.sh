#!/bin/bash
# Target-machine deployment with rollback on failure.
# Prerequisites: Docker installed, image pieces in docker_image/.
# Usage:  export ANTHROPIC_API_KEY=sk-... && ./target_deploy.sh
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

LOG_FILE="target_deploy.log"
log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
IMAGE_NAME="gps-sql-visualizer"
CONTAINER_NAME="gps-sql"
ROLLBACK_TAG="previous"

ROLLBACK_NEEDED=false

rollback() {
    echo -e "\n${RED}=== ROLLBACK ===${NC}" | tee -a "$LOG_FILE" >&2
    echo "  Something failed — reverting to previous image..." | tee -a "$LOG_FILE" >&2

    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true

    if docker image inspect "${IMAGE_NAME}:${ROLLBACK_TAG}" &>/dev/null; then
        echo "  Re-tagging previous → latest" | tee -a "$LOG_FILE" >&2
        docker tag "${IMAGE_NAME}:${ROLLBACK_TAG}" "${IMAGE_NAME}:latest"
        docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

        docker run -d \
            -p 0.0.0.0:8000:8000 \
            -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
            --name "$CONTAINER_NAME" \
            --restart unless-stopped \
            "${IMAGE_NAME}:latest"
        echo -e "${GREEN}  Rolled back to previous image${NC}" | tee -a "$LOG_FILE" >&2
    else
        echo -e "${RED}  No previous image found — manual intervention required${NC}" | tee -a "$LOG_FILE" >&2
    fi
    exit 1
}

# ── 0. Version guard (fail fast on stale pieces/checkout) ─────────────
log "=== Version guard ==="
REPO_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
log "  Repo VERSION: ${REPO_VERSION}"

if [ -f "$IMAGE_DIR/RELEASE.txt" ]; then
    PIECE_VERSION=$(sed -n 's/^VERSION=//p' "$IMAGE_DIR/RELEASE.txt" 2>/dev/null | head -1)
    PIECE_COMMIT=$(sed -n 's/^COMMIT=//p' "$IMAGE_DIR/RELEASE.txt" 2>/dev/null | head -1)
    PIECE_BUILT=$(sed -n 's/^BUILT=//p' "$IMAGE_DIR/RELEASE.txt" 2>/dev/null | head -1)
    log "  Piece manifest: VERSION=${PIECE_VERSION} COMMIT=${PIECE_COMMIT} BUILT=${PIECE_BUILT}"
    if [ "$PIECE_VERSION" != "$REPO_VERSION" ]; then
        echo -e "\n${RED}MISMATCH: pieces are v${PIECE_VERSION} but repo VERSION is v${REPO_VERSION} — image pieces are stale, run 'git pull' and retry${NC}" | tee -a "$LOG_FILE" >&2
        exit 1
    fi
else
    echo -e "\n${RED}ERROR: ${IMAGE_DIR}/RELEASE.txt manifest missing — cannot verify image piece version. Run release.sh first to generate the release pieces and manifest, then retry.${NC}" | tee -a "$LOG_FILE" >&2
    exit 1
fi

# Optional online check: is the local checkout strictly behind origin/main?
if command -v timeout &>/dev/null; then
    REMOTE_HEAD=$(timeout 10 git ls-remote origin refs/heads/main 2>/dev/null | head -1)
else
    REMOTE_HEAD=$(git ls-remote origin refs/heads/main 2>/dev/null | head -1)
fi

if [ -n "$REMOTE_HEAD" ]; then
    # Track fetch success explicitly — a failed fetch must NOT fall back to
    # the stale origin/main ref (previously swallowed by `|| true`).
    FETCH_OK=false
    if command -v timeout &>/dev/null; then
        if timeout 15 git fetch origin --quiet 2>/dev/null; then
            FETCH_OK=true
        fi
    else
        if git fetch origin --quiet 2>/dev/null; then
            FETCH_OK=true
        fi
    fi

    if [ "$FETCH_OK" = true ]; then
        BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
        AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
        if [ "$BEHIND" != "?" ] && [ "$AHEAD" != "?" ] && [ "$BEHIND" -gt 0 ] && [ "$AHEAD" -eq 0 ]; then
            # Strictly behind origin/main (fetch ok + behind + NOT diverged) → reset advice.
            REMOTE_VERSION=$(git show origin/main:VERSION 2>/dev/null || echo "?")
            if [ "$REMOTE_VERSION" = "?" ]; then
                REMOTE_VERSION="unknown version"
            else
                REMOTE_VERSION="v${REMOTE_VERSION}"
            fi
            echo -e "\n${RED}STALE CHECKOUT: local v${REPO_VERSION} is ${BEHIND} commit(s) behind origin/main (origin/main: ${REMOTE_VERSION})${NC}" | tee -a "$LOG_FILE" >&2
            echo -e "${RED}  Fix: git clean -fd docker_image/ && git reset --hard origin/main${NC}" | tee -a "$LOG_FILE" >&2
            exit 1
        elif [ "$BEHIND" = "?" ] || [ "$AHEAD" = "?" ]; then
            log "  ${YELLOW}Could not compare local HEAD with origin/main — skipping remote version check${NC}"
        elif [ "$BEHIND" -eq 0 ] && [ "$AHEAD" -gt 0 ]; then
            log "  ${YELLOW}Local checkout is ${AHEAD} commit(s) AHEAD of origin/main — unpushed commits present; skipping remote version check (do NOT reset)${NC}"
        elif [ "$BEHIND" -gt 0 ] && [ "$AHEAD" -gt 0 ]; then
            log "  ${YELLOW}Local checkout DIVERGED from origin/main (${AHEAD} ahead, ${BEHIND} behind) — resolve manually; skipping remote version check${NC}"
        else
            log "  Checkout up to date with origin/main"
        fi
    else
        log "  ${YELLOW}git fetch from origin failed — skipping remote version check (origin may be unreachable)${NC}"
    fi
else
    log "  ${YELLOW}origin unreachable (offline?) — skipping remote version check${NC}"
fi

# ── 1. Reassemble image ─────────────────────────────────────────────
log "=== Reassemble image ==="
cd "$IMAGE_DIR"
if [ ! -f checksums.md5 ]; then
    echo -e "${RED}ERROR: checksums.md5 not found${NC}" | tee -a "$LOG_FILE" >&2
    exit 1
fi
log "  Joining pieces..."
cat part_* > "$(basename "$IMAGE_FILE")"
log "  Done: $(ls -lh "$(basename "$IMAGE_FILE")" | awk '{print $5}')"
log "  Verifying checksums..."
# Verify AFTER joining — the tarball is gitignored and only exists
# on a fresh clone after the cat above (Bug fix 2026-08-04).
if md5sum -c checksums.md5; then
    log "  ${GREEN}Checksums OK${NC}"
else
    echo -e "${RED}  Checksum verification FAILED${NC}" | tee -a "$LOG_FILE" >&2
    exit 1
fi
cd ..

# ── 2. Tag current as previous (for rollback) ────────────────────────
log "=== Tag current → previous ==="
if docker image inspect "${IMAGE_NAME}:latest" &>/dev/null; then
    docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true
    docker tag "${IMAGE_NAME}:latest" "${IMAGE_NAME}:${ROLLBACK_TAG}"
    log "  Tagged ${IMAGE_NAME}:latest → ${IMAGE_NAME}:${ROLLBACK_TAG}"
else
    log "  No existing image (first deploy)"
fi

# ── 3. Stop old container ───────────────────────────────────────────
log "=== Stop old container ==="
if docker ps -q --filter "name=$CONTAINER_NAME" | grep -q .; then
    docker stop "$CONTAINER_NAME" && log "  Stopped"
fi
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# ── 4. Remove old image, load new ───────────────────────────────────
log "=== Load new image ==="
docker rmi "${IMAGE_NAME}:latest" 2>/dev/null || true
docker load < "$IMAGE_FILE" || rollback

# ── 4.5. Verify loaded image version (before starting) ───────────────
IMAGE_VERSION=$(docker run --rm "${IMAGE_NAME}:latest" cat /app/VERSION 2>/dev/null || echo "unknown")
log "  Loaded image VERSION: v${IMAGE_VERSION} (repo expects v${REPO_VERSION})"
if [ "$IMAGE_VERSION" != "$REPO_VERSION" ]; then
    echo -e "\n${RED}  VERSION MISMATCH: loaded image is v${IMAGE_VERSION} but repo expects v${REPO_VERSION}${NC}" | tee -a "$LOG_FILE" >&2
    rollback
fi

# ── 5. Start container ──────────────────────────────────────────────
log "=== Start container ==="
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
log "=== Health check ==="
HEALTHY=false
for i in $(seq 1 30); do
    sleep 2
    HEALTH_JSON=$(curl -sf http://127.0.0.1:8000/api/health 2>/dev/null || true)
    if [ -n "$HEALTH_JSON" ]; then
        HEALTH_VER=$(echo "$HEALTH_JSON" | grep -o '"version":"[^"]*"' | head -1 | cut -d'"' -f4)
        log "  ${GREEN}Ready${NC} ($HEALTH_JSON)"
        if [ -n "$HEALTH_VER" ] && [ "$HEALTH_VER" != "$REPO_VERSION" ]; then
            echo -e "\n${RED}  VERSION MISMATCH: server serves v${HEALTH_VER} but repo expects v${REPO_VERSION}${NC}" | tee -a "$LOG_FILE" >&2
            rollback
        fi
        HEALTHY=true
        break
    fi
    echo -n "."
done

if [ "$HEALTHY" = false ]; then
    echo -e "\n${RED}  Health check FAILED after 60s${NC}" | tee -a "$LOG_FILE" >&2
    rollback
fi

# ── 8. Cleanup old rollback tag (deploy succeeded) ───────────────────
docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

# ── 9. Show summary ─────────────────────────────────────────────────
echo ""
log "  ${GREEN}=== Deployed Successfully ===${NC}"
log "  Access:  http://${SERVER_IP}:8000"
log "  Health:  curl http://${SERVER_IP}:8000/api/health"
log "  Logs:    docker logs $CONTAINER_NAME"
log "  Version: v${REPO_VERSION}"
echo ""
log "  If unreachable from other machines, check firewall allows TCP port 8000."
