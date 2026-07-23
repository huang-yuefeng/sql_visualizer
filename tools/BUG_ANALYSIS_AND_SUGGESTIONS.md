# Data Flow Debugger — Bug List

> **Date:** 2026-07-23 | **Version:** 3.3.64 | **Active:** 3

---

## Active Bugs

### Bug 1: FILTER Edge Highlights Wrong Lines (P2)

**Symptom:** step2 FILTER range=`[4-6]` (INSERT...SELECT...FROM). Should be `[7-8]` (WHERE clause). Last condition `AND c.region IN (...)` never highlighted.

**Fix:** `_estimate_sql_range` keyword matching should prioritize WHERE/HAVING over INSERT/SELECT for FILTER edges.

---

### Bug 2: Orange Highlight Never Clears (P1)

**Symptom:** 2 lines persist after Escape. Clicking different edges with different ranges doesn't change highlight.

**Fix:** `SqlPanel.jsx:316` — range-based React key. `dataflow_service.py` — per-edge-type range partitioning.

---

### Bug 3: Edge Ranges Overlap in step3 (P2)

**Symptom:** 5 lines covered by 2-3 edges simultaneously. FILTER/JOIN edges share identical range `[4-6]`.

**Fix:** Partition ranges by edge type. JOIN→L5 only, FILTER→L6 only, TABLE_FLOW→L4 only.

---

## Fixed

| Bug | Version |
|-----|:------:|
| DML edge now `⟐ output → stg_customers` | v3.3.64 |
| Duplicate output nodes removed | v3.3.64 |
| Taxi edge invisible | v3.3.57 |
| NONE sql_range | v3.3.56 |
| Pipeline==Spore | v3.3.51 |
| L2 collapse | v3.3.53 |
| Spore overlaps | v3.3.53 |
