#!/bin/bash
# Target-machine deployment with rollback on failure.
# Prerequisites: Docker installed, image pieces in docker_image/.
# Usage:  ./target_deploy.sh
set -e

# ── Definitions only below ──────────────────────────────────────────
# Everything up to the "entry guard" is DEFINITIONS (colors, log helpers,
# build_users_env). Sourcing this file (tests/deploy/test_allowlist_logic.sh)
# therefore defines the functions and runs nothing: no docker, no cd, no
# version guard. Two testability seams:
#   * DEPLOY_LOG_FILE  — redirect the deploy log (default target_deploy.log)
#   * BASH_SOURCE guard — a sourced run returns before the main flow
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${DEPLOY_LOG_FILE:-$APP_DIR/target_deploy.log}"

_diag() {
    # Diagnostics to stderr AND the deploy log — never stdout: the caller
    # captures build_users_env's stdout as the payload JSON.
    printf '%s\n' "$*" | tee -a "$LOG_FILE" >&2
}

log() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
IMAGE_NAME="gps-sql-visualizer"
CONTAINER_NAME="gps-sql"

# ── User allowlist (R31 #269, M1-D5-safe) ───────────────────────────
# users.allowlist.json (repo root) is a single JSON object mapping
# email → password. The LIVE file is GITIGNORED — real passwords are never
# committed or pushed; users.allowlist.json.example documents the format.
#
# `//` FULL-LINE comments (optional leading whitespace) are stripped before
# parsing. A trailing `// note` AFTER the JSON on the same line is NOT
# supported: it fails validation and the file is skipped — keep comments on
# their own lines.
#
# admin@hsbc.com is auto-merged with the default password when the file
# omits it (M1-D5: omitting it silently disables the admin account).
ALLOWLIST_FILE="$APP_DIR/users.allowlist.json"
ADMIN_EMAIL="admin@hsbc.com"
ADMIN_DEFAULT_PASSWORD="123456"

# Every non-provisioning outcome is a WARNING + SKIP: the container then
# starts with the image default (admin@hsbc.com only) and the deploy
# continues. A broken allowlist must never abort a deploy.
USERS_ENV=()
USERS_ENV_STATUS="no-file"
USERS_ENV_JSON=""

# In-container location of the account store (backend WORKSPACE_ROOT).
CONTAINER_USERS_FILE="/tmp/workspaces/users.json"

# strip_allowlist_comments <path>
#   `//` LINE-comment strip. Full-line comments only (leading whitespace,
#   then // to end of line — a `//` inside a value such as "https://…" is
#   untouched). CR/LF/TAB are then removed so a pretty-printed, commented
#   file becomes one JSON line. SPACES ARE KEPT: they are legal JSON
#   whitespace and may be part of a password.
strip_allowlist_comments() {
    sed -e 's#^[[:space:]]*//.*$##' "$1" | tr -d '\r\n\t'
}

# build_users_env <path-to-users.allowlist.json>
#   Outputs the merged, comment-stripped JSON TWO ways:
#     * prints it to STDOUT (pure JSON, no log noise)
#     * leaves it in $USERS_ENV_JSON
#   The duplicate is deliberate: the caller also needs USERS_ENV_STATUS in the
#   CURRENT shell, and capturing stdout (`x="$(build_users_env …)")` would run
#   the function in a subshell whose variable assignments are lost — the
#   status would silently stay at its initial value and nothing would ever be
#   provisioned. So the deploy calls the function bare and reads both globals.
#   It also sets USERS_ENV_STATUS to one of:
#     ok            file parsed, admin@hsbc.com already present
#     merged-admin  file parsed, admin@hsbc.com auto-merged (M1-D5)
#     no-file       path missing/unreadable (image default: admin only)
#     empty-file    file exists but is empty / whitespace / comments only
#     empty-object  file is `{}` — valid JSON but provisions nothing
#     invalid-json  not shaped like a JSON object, or fails the deep parse
#   Only ok / merged-admin produce a payload; everything else is logged as a
#   warning and skipped.
#   set -e safe: the function NEVER returns non-zero — a bad file is a
#   status, not an abort.
build_users_env() {
    USERS_ENV_STATUS="no-file"
    USERS_ENV_JSON=""
    USERS_ENV_STATUS="no-file"
    local file="${1:-}"
    local label="${file:-$ALLOWLIST_FILE}"
    local raw shape

    if [ -z "$file" ] || [ ! -f "$file" ] || [ ! -r "$file" ]; then
        _diag "  Users: no readable allowlist at $label — provisioning the image default ($ADMIN_EMAIL only)"
        return 0
    fi

    raw="$(strip_allowlist_comments "$file")" || true

    if [ -z "$raw" ]; then
        USERS_ENV_STATUS="empty-file"
        _diag "  ⚠ $label is empty (or comments only) — skipping user provisioning (image default: $ADMIN_EMAIL only)"
        return 0
    fi

    # Shape checks run on the whitespace-collapsed form so a pretty-printed
    # file ("admin@hsbc.com": "pw") validates the same as a single-line one.
    shape="$(printf '%s' "$raw" | tr -d '[:space:]')"

    if [ "$shape" = "{}" ]; then
        USERS_ENV_STATUS="empty-object"
        _diag "  ⚠ $label is {} — no accounts to provision (image default: $ADMIN_EMAIL only)"
        return 0
    fi

    if [[ "$shape" != '{'* ]] || [[ "$shape" != *'}' ]] || [[ "$shape" != *'":"'* ]]; then
        USERS_ENV_STATUS="invalid-json"
        _diag "  ⚠ $label is not a JSON object ({\"email\":\"password\", ...}) — skipping user provisioning (image default: $ADMIN_EMAIL only)"
        return 0
    fi

    # Deep parse when python3 is available (the image's own json.loads is the
    # authority, and a shape-valid but syntactically broken file would
    # otherwise be dropped SILENTLY inside the container). Best effort: a
    # target without python3 keeps the shape check only.
    if command -v python3 >/dev/null 2>&1; then
        if ! printf '%s' "$raw" | python3 -c 'import json,sys; json.load(sys.stdin)' >/dev/null 2>&1; then
            USERS_ENV_STATUS="invalid-json"
            _diag "  ⚠ $label is not valid JSON — skipping user provisioning (image default: $ADMIN_EMAIL only)"
            return 0
        fi
    fi

    if [[ "$shape" == *"\"${ADMIN_EMAIL}\":"* ]]; then
        USERS_ENV_STATUS="ok"
        _diag "  Users: provisioning allowlist from $label"
    else
        raw="{\"${ADMIN_EMAIL}\":\"${ADMIN_DEFAULT_PASSWORD}\",${raw#\{}"
        USERS_ENV_STATUS="merged-admin"
        _diag "  Users: provisioning allowlist from $label (admin auto-merged)"
    fi

    USERS_ENV_JSON="$raw"
    printf '%s' "$raw"
    return 0
}

# ── Entry guard: sourced runs get definitions only ──────────────────
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return 0
fi

cd "$APP_DIR"

# Port mapping — the container always listens on CONTAINER_PORT (uvicorn),
# published on HOST_PORT. Default 8000 (dev machine 192.168.0.66); override
# per machine without editing the script, e.g. the remote server is limited
# to host port 8010 → `HOST_PORT=8010 ./target_deploy.sh`.

# Informational usage hint — when run directly with no input at all (no
# positional args AND no HOST_PORT env override), print the correct
# invocations. Purely informational: the deploy continues with the default.
# (Checked BEFORE the HOST_PORT default assignment below so we can tell
# whether the user explicitly set HOST_PORT vs. it being unset.)
if [ "$#" -eq 0 ] && [ -z "${HOST_PORT+x}" ]; then
    log "Usage: ./target_deploy.sh                        # default host port 8000"
    log "       HOST_PORT=8010 ./target_deploy.sh         # publish on host port 8010"
    log "       (informational: deploying with default HOST_PORT=8000)"
fi

CONTAINER_PORT="8000"
HOST_PORT="${HOST_PORT:-8000}"
case "$HOST_PORT" in
    ''|*[!0-9]*)
        echo -e "${RED}ERROR: HOST_PORT must be a positive integer (got '${HOST_PORT}')${NC}" >&2
        exit 1
        ;;
esac
if [ "$HOST_PORT" -lt 1 ] || [ "$HOST_PORT" -gt 65535 ]; then
    echo -e "${RED}ERROR: HOST_PORT out of range 1-65535 (got '${HOST_PORT}')${NC}" >&2
    exit 1
fi
ROLLBACK_TAG="previous"

# R31: user data (workspaces + users.json) is DURABLE — the container mounts a
# named volume for /tmp/workspaces so a recreate (every deploy) never wipes it.
# Named volumes survive container recreation; data lives on across deploys.
WS_VOLUME="gps_workspace_data"

ROLLBACK_NEEDED=false

rollback() {
    echo -e "\n${RED}=== ROLLBACK ===${NC}" | tee -a "$LOG_FILE" >&2
    echo "  Something failed — reverting to previous image..." | tee -a "$LOG_FILE" >&2

    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

    if docker image inspect "${IMAGE_NAME}:${ROLLBACK_TAG}" &>/dev/null; then
        echo "  Re-tagging previous → latest" | tee -a "$LOG_FILE" >&2
        docker tag "${IMAGE_NAME}:${ROLLBACK_TAG}" "${IMAGE_NAME}:latest"
        docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

        # Same account set as the failed deploy: users.json is durable in the
        # volume, but provisioning is what re-syncs passwords at startup, so a
        # rollback keeps the allowlist env rather than dropping it.
        docker run -d --pull=never \
            -p "0.0.0.0:${HOST_PORT}:${CONTAINER_PORT}" \
            -v "$WS_VOLUME:/tmp/workspaces" \
            "${USERS_ENV[@]}" \
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
        echo -e "\n${RED}MISMATCH: pieces are v${PIECE_VERSION} but repo VERSION is v${REPO_VERSION} — image pieces are stale${NC}" | tee -a "$LOG_FILE" >&2
        echo -e "${RED}  Fix: obtain fresh docker_image/ pieces from the developer (offline transfer) and retry${NC}" | tee -a "$LOG_FILE" >&2
        exit 1
    fi
    if [ -n "$PIECE_COMMIT" ]; then
        LOCAL_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
        log "  Local HEAD: ${LOCAL_COMMIT}"
        if [ "$LOCAL_COMMIT" != "unknown" ]; then
            # release.sh stamps RELEASE.txt BEFORE making its own commit, so
            # PIECE_COMMIT names a pre-release commit that the release commit
            # descends from. Strict equality would therefore always fail on any
            # machine that has pulled the release commit (dev and target alike).
            # Accept any ancestor of HEAD: the pieces are at-or-behind the
            # checkout, never ahead of it. A diverged/unrelated pieces commit
            # (real staleness) still refuses. (Local git op — offline-safe.)
            if ! git merge-base --is-ancestor "$PIECE_COMMIT" HEAD 2>/dev/null; then
                echo -e "\n${RED}COMMIT MISMATCH: pieces were built from ${PIECE_COMMIT} which is NOT an ancestor of local HEAD ${LOCAL_COMMIT} — image pieces are stale${NC}" | tee -a "$LOG_FILE" >&2
                echo -e "${RED}  Fix: obtain fresh docker_image/ pieces from the developer (offline transfer) and retry${NC}" | tee -a "$LOG_FILE" >&2
                exit 1
            fi
        fi
    fi
else
    echo -e "\n${RED}ERROR: ${IMAGE_DIR}/RELEASE.txt manifest missing — cannot verify image piece version. Run release.sh first to generate the release pieces and manifest, then retry.${NC}" | tee -a "$LOG_FILE" >&2
    exit 1
fi

# OFFLINE-ONLY TARGET (user rule 2026-08-12): no internet connections are
# ever allowed on this machine — git operations in particular. The former
# origin check (`git ls-remote` / `git fetch`) was REMOVED for this reason.
# The version guard above (repo VERSION vs RELEASE.txt manifest) is the gate.

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
# macOS has no GNU md5sum — fall back to `md5 -q` per-part comparison.
if command -v md5sum >/dev/null 2>&1; then
    if md5sum -c checksums.md5; then
        log "  ${GREEN}Checksums OK${NC}"
    else
        echo -e "${RED}  Checksum verification FAILED${NC}" | tee -a "$LOG_FILE" >&2
        exit 1
    fi
else
    ALL_OK=1
    while read -r EXPECTED FILE; do
        ACTUAL=$(md5 -q "$FILE" 2>/dev/null)
        if [ -z "$ACTUAL" ] || [ "$ACTUAL" != "$EXPECTED" ]; then
            echo -e "  ${RED}FAILED: $FILE${NC}" | tee -a "$LOG_FILE" >&2
            ALL_OK=0
        else
            echo "  OK: $FILE"
        fi
    done < checksums.md5
    if [ "$ALL_OK" -eq 1 ]; then
        log "  ${GREEN}Checksums OK${NC}"
    else
        echo -e "${RED}  Checksum verification FAILED${NC}" | tee -a "$LOG_FILE" >&2
        exit 1
    fi
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
# -f (2026-09-01 deploy failure): a plain `docker stop` + `docker rm` silently
# failed when the existing container (created outside this script by the
# add-user procedure) didn't quiesce — the rm error was swallowed by
# `|| true` and the later `docker run` died with "name already in use",
# triggering a rollback. Force-remove instead, then VERIFY the name is free.
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
if docker ps -aq --filter "name=^/${CONTAINER_NAME}$" | grep -q .; then
    log "  ERROR: container ${CONTAINER_NAME} still exists after force-remove"
    exit 1
fi

# ── 4. Remove old image, load new ───────────────────────────────────
log "=== Load new image ==="
docker rmi "${IMAGE_NAME}:latest" 2>/dev/null || true
docker load < "$IMAGE_FILE" || rollback

# ── 4.5. Verify loaded image version (before starting) ───────────────
IMAGE_VERSION=$(docker run --rm --pull=never "${IMAGE_NAME}:latest" cat /app/VERSION 2>/dev/null || echo "unknown")
log "  Loaded image VERSION: v${IMAGE_VERSION} (repo expects v${REPO_VERSION})"
if [ "$IMAGE_VERSION" != "$REPO_VERSION" ]; then
    echo -e "\n${RED}  VERSION MISMATCH: loaded image is v${IMAGE_VERSION} but repo expects v${REPO_VERSION}${NC}" | tee -a "$LOG_FILE" >&2
    rollback
fi

# ── 5. Start container ──────────────────────────────────────────────
log "=== Start container ==="

# M1-D5-safe user allowlist: build_users_env prints the merged JSON and sets
# USERS_ENV_STATUS / USERS_ENV_JSON. Only ok / merged-admin produce a payload;
# every other status was already logged by the function as a WARNING + SKIP,
# so the deploy continues with the image default (admin@hsbc.com only).
# Called BARE (no command substitution): a subshell would drop the status and
# the deploy would silently provision nothing — see the function's header.
# Stdout is discarded: that copy of the payload carries the PASSWORDS and must
# never reach the console or a piped/tee'd deploy log. The payload travels in
# $USERS_ENV_JSON instead.
build_users_env "$ALLOWLIST_FILE" >/dev/null || true
case "$USERS_ENV_STATUS" in
    ok|merged-admin)
        USERS_ENV=(-e "PROVISIONED_USERS_JSON=$USERS_ENV_JSON")
        ;;
esac

docker run -d --pull=never \
    -p "0.0.0.0:${HOST_PORT}:${CONTAINER_PORT}" \
    -v "$WS_VOLUME:/tmp/workspaces" \
    "${USERS_ENV[@]}" \
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
i=0
while [ "$i" -lt 30 ]; do
    i=$((i+1))
    sleep 2
    HEALTH_JSON=$(curl -sf --noproxy '*' "http://127.0.0.1:${HOST_PORT}/api/health" 2>/dev/null || true)
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

# ── 8. Post-deploy: name the provisioned accounts (emails ONLY) ──────
# Provisioning runs in the container's startup lifespan; by the time the
# health endpoint answers it has finished. Log the account NAMES so the
# operator can see who the deploy created — never the passwords.
if [ "${#USERS_ENV[@]}" -gt 0 ]; then
    PROVISIONED_EMAILS=$(docker exec "$CONTAINER_NAME" python3 -c "import json;d=json.load(open('${CONTAINER_USERS_FILE}'));print(' '.join(sorted(d)))" 2>/dev/null || true)
    if [ -n "$PROVISIONED_EMAILS" ]; then
        log "  ${GREEN}Provisioned accounts:${NC} $PROVISIONED_EMAILS"
    else
        log "  ⚠ Could not read the provisioned accounts from ${CONTAINER_NAME}:${CONTAINER_USERS_FILE} — check 'docker logs $CONTAINER_NAME' for provision_user warnings (e.g. a password shorter than the minimum is dropped with a named warning)"
    fi
fi

# ── 9. Cleanup old rollback tag (deploy succeeded) ───────────────────
docker rmi "${IMAGE_NAME}:${ROLLBACK_TAG}" 2>/dev/null || true

# ── 10. Show summary ─────────────────────────────────────────────────
echo ""
log "  ${GREEN}=== Deployed Successfully ===${NC}"
log "  Access:  http://${SERVER_IP}:${HOST_PORT}"
log "  Health:  curl --noproxy '*' http://${SERVER_IP}:${HOST_PORT}/api/health"
log "  Logs:    docker logs $CONTAINER_NAME"
log "  Version: v${REPO_VERSION}"
echo ""
log "  If unreachable from other machines, check firewall allows TCP port ${HOST_PORT}."
