#!/usr/bin/env python3
"""API smoke test for GPS SQL Visualizer."""
import sys, requests

BASE = 'http://127.0.0.1:8000'
FAIL = 0

def check(name, ok):
    global FAIL
    if ok:
        print(f'  ✅ {name}')
    else:
        print(f'  ❌ {name}')
        FAIL += 1

print('=== API Smoke Test ===')

# 1. Health
try:
    r = requests.get(f'{BASE}/api/health', timeout=5)
    check('GET /api/health', r.status_code == 200)
except Exception as e:
    check('GET /api/health', False)
    print(f'      {e}')

# 2. Analyze
SAMPLE_SQL = (
    "SELECT t.id, t.amount, "
    "COUNT(*) OVER (PARTITION BY t.status) AS cnt "
    "FROM transactions t "
    "WHERE t.date >= '2024-01-01'"
)
try:
    r = requests.post(
        f'{BASE}/api/analyze',
        data={'sql_text': SAMPLE_SQL, 'script_name': 'smoke.sql'},
        timeout=30,
    )
    ok = r.status_code == 200 and r.json().get('total_variables', 0) > 0
    check('POST /api/analyze', ok)
except Exception as e:
    check('POST /api/analyze', False)
    print(f'      {e}')

# 3. Scripts
try:
    r = requests.get(f'{BASE}/api/scripts', timeout=10)
    check('GET /api/scripts', r.status_code == 200 and isinstance(r.json(), list))
except Exception as e:
    check('GET /api/scripts', False)
    print(f'      {e}')

print(f'\n{"✅ All passed" if FAIL == 0 else f"❌ {FAIL} failures"}')
sys.exit(0 if FAIL == 0 else 1)
