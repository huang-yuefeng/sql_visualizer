#!/bin/bash
set -e
cd "$(dirname "$0")"

# ── Config ──────────────────────────────────────────────────────────
IMAGE_DIR="docker_image"
IMAGE_FILE="$IMAGE_DIR/gps-sql-visualizer.tar.gz"
PIECE_SIZE="45M"          # pieces < 50MB for GitHub
VERSION=$(cat VERSION)
COMMIT_MSG="${1:-[new] v$VERSION}"

# ── 1. Build Docker image ───────────────────────────────────────────
echo "=== Building Docker image v$VERSION ==="
docker build -t gps-sql-visualizer:latest .

# ── 2. Run quick smoke test (health check only) ─────────────────────
echo "=== Smoke test ==="
docker rm -f gps-test 2>/dev/null
docker run -d -p 8000:8000 -e ANTHROPIC_API_KEY=test-key --name gps-test gps-sql-visualizer:latest
for i in $(seq 1 15); do
    sleep 1
    if docker exec gps-test python3 -c "import socket;r=socket.socket().connect_ex(('127.0.0.1',8000));exit(r)" 2>/dev/null; then
        break
    fi
done
curl -s http://127.0.0.1:8000/api/health && echo ""
docker stop gps-test 2>/dev/null

# ── 3. Export image & split into pieces ─────────────────────────────
echo "=== Exporting & splitting image ==="
mkdir -p "$IMAGE_DIR"

# Export full image
docker save gps-sql-visualizer:latest | gzip > "$IMAGE_FILE"

# Remove old pieces
rm -f "$IMAGE_DIR"/part_* "$IMAGE_DIR"/checksums.md5

# Split into pieces < 50MB
split -b "$PIECE_SIZE" -d "$IMAGE_FILE" "$IMAGE_DIR/part_"
PIECE_COUNT=$(ls "$IMAGE_DIR"/part_* | wc -l)

# Generate checksums for integrity verification
md5sum "$IMAGE_DIR"/part_* > "$IMAGE_DIR/checksums.md5"
echo "  Split into $PIECE_COUNT pieces"

# ── 4. Clean up any stale Docker containers ─────────────────────────
docker rm -f gps-test 2>/dev/null

# ── 5. Git operations ──────────────────────────────────────────────
echo "=== Git ==="

# Remove old image pieces from git tracking, add new ones
git rm --cached "$IMAGE_DIR"/part_* "$IMAGE_DIR"/checksums.md5 2>/dev/null || true
git add "$IMAGE_DIR"/part_*
git add "$IMAGE_DIR"/checksums.md5

# Add all other source changes
git add -A

# Commit
echo "  Commit: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# Push
echo "=== Push ==="
git push

echo ""
echo "=== Done ==="
echo "  Version:  v$VERSION"
echo "  Image:    $IMAGE_FILE ($(du -sh "$IMAGE_FILE" | cut -f1))"
echo "  Pieces:   $PIECE_COUNT (in $IMAGE_DIR/)"
echo "  Commit:   $COMMIT_MSG"
