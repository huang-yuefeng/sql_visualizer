# Efficiency Suggestions — SQL Visualizer Testing

> **Date:** 2026-07-23

---

## 1. Biggest Time Wasters

| Waste | Time Cost | Fix |
|-------|:---------:|-----|
| Manual Playwright test per bug | ~2 min each | ✅ Done — `test_modes.js` |
| Deploy-check-test loop | ~1 min per cycle | Auto-deploy on source change |
| False positives from test bugs | Hours | Fix coordinate conversion in tests |
| Other agent regressions | Hours | Regression test suite |
| Document updates between tests | ~30 min/day | Template + auto-update |

---

## 2. Specific Suggestions

### S1: Add Hot-Reload Deployment (P1)

Currently: source change → `./fast_deploy.sh` → test. Adding a file watcher that auto-deploys on save eliminates the deploy step:

```bash
# In one terminal, keep running:
while inotifywait -r frontend/src/ -e modify; do ./fast_deploy.sh; done
```

### S2: Standardize Test Harness (P1)

All Playwright tests share the same setup (upload → search → wait). Extract to a function:

```js
// test_harness.js — reusable setup
async function setupTest(page, zipPath, table, field) {
  await page.goto("http://127.0.0.1:8000");
  // ... upload, search, wait ...
  return { cy: window.__cy1, scriptIds: [...] };
}
```

### S3: Fix Coordinate Conversion Once (P1)

Every edge visibility test had the model-vs-viewport coordinate bug. Create a single utility:

```js
function screenPosition(cy, modelX, modelY) {
  const zoom = cy.zoom(), pan = cy.pan();
  const vpW = cy.container().offsetWidth, vpH = cy.container().offsetHeight;
  return {
    x: (modelX - pan.x) * zoom + vpW / 2,
    y: (modelY - pan.y) * zoom + vpH / 2,
  };
}
```

### S4: Regression Suite as Single Command (P2)

Combine all checks into one script that runs API + browser tests:

```bash
./tools/regression_test.sh   # runs everything, outputs PASS/FAIL
```

This eliminates the "which test did I run last time?" problem.

### S5: Version-Locked Bug Status (P2)

Each bug document entry should include the last tested version. Auto-detect when version changes and flag for re-test:

```
Bug 3: v3.3.60=4 lines, v3.3.62=stuck
       Current: 3.3.63 → NEEDS RE-TEST
```

### S6: Reduce Document Churn (P3)

Instead of rewriting the bug document every test, maintain a simple status table + append findings:

```markdown
## Current Status (v3.3.63)
| Bug | Status | Since |
|-----|:------:|:-----:|
| 3. Orange persist | ❌ | v3.3.60 |
| All others | ✅ | v3.3.57 |
```

---

## 3. Time Savings Estimate

| Suggestion | Current Time | After | Saving |
|-----------|:-----------:|:-----:|:------:|
| S1: Auto-deploy | 1 min/cycle | 0 | 20% |
| S2: Test harness | 2 min/test | 30s | 75% |
| S3: Fix coordinates | Hours debugging | 0 | Large |
| S4: Single regression | 5 min | 30s | 90% |
| S5: Version tracking | Manual checking | Automatic | 50% |
| S6: Doc churn | 30 min/day | 5 min | 80% |

**Estimated total: 2-3x faster testing cycles.**
