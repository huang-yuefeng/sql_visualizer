#!/bin/bash
# Ground-truth benchmark — the regression gate for every solution update.
# Compares the system's live L2 output vs the canonical ground truth
# (tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md Part II §7.2) and prints the
# structured diff. Loop protocol: run → classify each diff line (solution bug
# vs ground-truth update) → fix → re-run → until MATCH.
set -e
docker exec gps-sql-backend sh -c 'cd /app/backend && python3 -m pytest tests/test_ground_truth_benchmark.py -v 2>&1'
