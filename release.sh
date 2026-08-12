#!/bin/bash
# Full release pipeline — build, test, split image, commit, push.
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'

# ── Config ──────────────────────────────────────────────────────────
IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
PIECE_SIZE="45M"          # pieces < 50MB for GitHub
VERSION=$(cat VERSION)
COMMIT_MSG="${1:-[release] v$VERSION}"

# ── 0. Pre-flight: run pytest suite ─────────────────────────────────
echo "=== Pre-flight: pytest ==="
cd backend
if [ -d venv ]; then
    venv/bin/python -m pytest tests/ -q --tb=short || {
        echo -e "${RED}❌ Tests failed — aborting release${NC}"
        exit 1
    }
else
    # No venv — skip but warn
    echo -e "${RED}⚠️  No venv found, skipping pytest. Run tests manually before release.${NC}"
fi
cd ..
echo -e "${GREEN}✅ Pre-flight OK${NC}"

# ── 1. Build Docker image ───────────────────────────────────────────
echo "=== Building Docker image v$VERSION ==="
docker build -t gps-sql-visualizer:latest .

# ── 2. Run smoke test ───────────────────────────────────────────────
echo "=== Smoke test ==="
docker rm -f gps-test 2>/dev/null || true
docker run -d --pull=never -p 8000:8000 --name gps-test gps-sql-visualizer:latest

echo -n "  Waiting for healthy..."
for i in $(seq 1 20); do
    sleep 1
    if docker exec gps-test python3 -c "import socket;r=socket.socket().connect_ex(('127.0.0.1',8000));exit(r)" 2>/dev/null; then
        echo " ready"
        break
    fi
    echo -n "."
done

curl -sf http://127.0.0.1:8000/api/health && echo ""

# Run pytest in container
echo "=== Pytest (container) ==="
docker exec gps-test python3 -m pytest tests/ -q --tb=short || {
    echo -e "${YELLOW}⚠️  Some tests failed — continuing anyway (check manually)${NC}"
}

docker stop gps-test 2>/dev/null || true

# ── 3. Export image & split into pieces ─────────────────────────────
echo "=== Exporting & splitting image ==="
mkdir -p "$IMAGE_DIR"

# Export full image
docker save gps-sql-visualizer:latest | gzip > "$IMAGE_FILE"
IMAGE_SIZE=$(du -sh "$IMAGE_FILE" | cut -f1)

# Remove old pieces
rm -f "$IMAGE_DIR"/part_* "$IMAGE_DIR"/checksums.md5

# Split into pieces < 50MB
split -b "$PIECE_SIZE" -d "$IMAGE_FILE" "$IMAGE_DIR/part_"
PIECE_COUNT=$(ls "$IMAGE_DIR"/part_* | wc -l)

# Generate checksums
(cd "$IMAGE_DIR" && md5sum part_* > checksums.md5)

# Release manifest (target_deploy.sh version guard)
{
    echo "VERSION=$VERSION"
    echo "COMMIT=$(git rev-parse HEAD)"
    echo "BUILT=$(date '+%Y-%m-%d %H:%M:%S %z')"
} > "$IMAGE_DIR/RELEASE.txt"
echo "  Split into $PIECE_COUNT pieces ($IMAGE_SIZE total)"

# ── 4. Git operations ──────────────────────────────────────────────
echo "=== Git ==="

# Remove old pieces from git tracking
git rm --cached "$IMAGE_DIR"/part_* "$IMAGE_DIR"/checksums.md5 2>/dev/null || true

# Stage new pieces
git add "$IMAGE_DIR"/part_*
git add "$IMAGE_DIR"/checksums.md5
git add "$IMAGE_DIR"/RELEASE.txt

# Stage source files (explicit paths, not git add -A)
git add VERSION backend/ frontend/ samples/ Dockerfile Dockerfile.dev \
       check.sh build.sh deploy.sh release.sh target_deploy.sh \
       README.md REQUIREMENTS.md CLAUDE.md tools/ .dockerignore .gitignore 2>/dev/null || true

# Commit
echo "  Commit: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# OFFLINE RULE (user ruling 2026-08-12): no internet-connecting command may
# live in any *.sh file — `git push` was REMOVED for this reason. The release
# is committed locally; publishing to origin is done manually by the
# developer (or by an agent on the dev machine), never inside a script.
echo "=== Push (manual) ==="
echo -e "  ${YELLOW}Release committed locally — push manually with 'git push' (offline rule: no git in .sh)${NC}"
echo "  Full image preserved at $IMAGE_FILE until the commit is pushed; then: rm -f $IMAGE_FILE"

echo ""
echo -e "${GREEN}=== Done ===${NC}"
echo "  Version:  v$VERSION"
echo "  Image:    $IMAGE_SIZE"
echo "  Pieces:   $PIECE_COUNT (in $IMAGE_DIR/)"
echo "  Manifest: $IMAGE_DIR/RELEASE.txt"
echo "  Commit:   $COMMIT_MSG"
