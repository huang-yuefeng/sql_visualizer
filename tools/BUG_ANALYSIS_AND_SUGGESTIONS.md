# Data Flow Debugger — Bug List

> **Date:** 2026-07-23 | **Version:** 3.3.63 | **Active:** 3

---

## Bug 1: L2 — DML Edge Bypasses Output Node (P2)

**Symptom:** In step2 L2, the DML edge goes `crm_customers → stg_customers`, skipping `⟐ output`. Should go `⟐ output → stg_customers` because the INSERT reads from the SELECT result.

**Evidence:**
```
Current:  crm_customers ──DML──→ stg_customers   (bypasses SELECT)
Correct:  crm_customers → ⟐ output ──DML──→ stg_customers
```

**Fix:** DML edge source should be `⟐ output` (the SELECT result container), not the FROM table.

---

## Bug 2: FILTER Edge Highlights Wrong Lines (P2)

**Symptom:** In step2, clicking FILTER edge highlights lines 3-6 (INSERT...SELECT...FROM) instead of lines 7-8 (WHERE clause). Last line `AND c.region IN ('NA','EMEA','APAC');` is never highlighted.

**Evidence:** FILTER range=`[3,6]` (INSERT...FROM). WHERE is on lines 7-8.

**Fix:** `_estimate_sql_range` keyword matching for FILTER should match WHERE/HAVING before INSERT/SELECT.

---

## Bug 3: Orange Highlight Stuck After Escape (P1)

**Symptom:** Orange edge-highlight never clears. v3.3.62: 0/5 scripts show highlight change. Ranges now more specific (3-6 vs 2-5) but all still overlap on first few lines.

**Fix:** `SqlPanel.jsx:316` — range-based React key. `dataflow_service.py` — per-edge-type partitioning.

---

## Fixed

| Bug | Version |
|-----|:------:|
| Taxi edge invisible (dx=0) | v3.3.57 |
| NONE sql_range | v3.3.56 |
| Pipeline==Spore | v3.3.51 |
| L2 collapse | v3.3.53 |
| Spore overlaps | v3.3.53 |
