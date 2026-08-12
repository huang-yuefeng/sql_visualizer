#!/bin/bash
# Jaccard benchmark — THE regression gate (supersedes
# test_ground_truth_benchmark.py / run_benchmark.sh). Compares the
# system's live L2 output vs the canonical ground truth
# (backend/tests/jaccard_canonical.py, compiled from the
# tools/GROUND_TRUTH_*.md docs — incl. the R29 directional cases: 4
# existing seeds pinned to direction=downstream plus the upstream /
# downstream closures for rrcdm / iiapty / lending_ref) and asserts the
# per-feature recall/precision floors plus the invariants (R19.3,
# J12-17, R11-2, R29 production-only upstream). Loop protocol: run →
# classify each diff line (solution bug vs ground-truth update) → fix →
# re-run → until MATCH.
#
# NOTE: the backend container is `gps-sql` (gps-sql-backend is an
# exited leftover and does NOT exist as a running container).
set -e
docker exec gps-sql sh -c 'cd /app/backend && python3 -m pytest tests/test_jaccard_benchmark.py -v 2>&1'
