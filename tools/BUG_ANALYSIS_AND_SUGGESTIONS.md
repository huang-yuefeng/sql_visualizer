# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-23 | **Version:** 3.3.72 (uncommitted) | **Base commit:** v3.3.65 | **Active:** 1 partial (Bug 3)
>
> Fixed bugs moved to [`BUG_HISTORY.md`](BUG_HISTORY.md).

---

## Quick Status

| Bug | Priority | Status | Notes |
|-----|----------|--------|-------|
| Bug 1: Duplicate Output Nodes | — | ✅ FIXED | v3.3.72: edge-level redirect for non-DML bypass edges |
| Bug 3: Edge Ranges Overlap | P2 | 🔧 PARTIALLY FIXED | step3: 2 lines; step4: 1 line (same-type co-location) |

## Regression Test Results (v3.3.72)

All 5 `samples/multi_workflow/*.sql` scripts tested:

| Script | Bug 1: Topology | Bug 3: Overlap | Notes |
|--------|----------------|----------------|-------|
| step1 | ✅ `raw_orders → ⟐ output → stg_orders` | 0 lines | Perfect |
| step2 | ✅ `crm_customers → ⟐ output → stg_customers` | 0 lines | + FILTER edge |
| step3 | ✅ `stg_orders → ⟐ output → analytics_orders` | 2 lines | TABLE_FLOW×2, JOIN×2 (same-type co-location) |
| step4 | ✅ `analytics_orders → ⟐ output → daily_summary` | 1 line | TRANSFORM+AGGREGATE co-location |
| step5 | ✅ `daily_summary → ⟐ output` | 0 lines | SELECT-only |

---

## Bug 1: Duplicate Output Nodes — FIXED ✅ v3.3.72

### Fix applied (three-step edge routing)

The `qo_` node has been eliminated. All edges now route through the existing `"⟐ output"` intermediate_table via three steps at `dataflow_service.py:1602-1634`:

```python
intermediate_id = None
for tn in table_nodes.values():
    if isinstance(tn, dict) and tn.get("type") == "intermediate_table":
        intermediate_id = tn.get("id"); break

dml_targets = set(); dml_sources = set()
for e in new_edges:
    if "DML" in e.get("edge_type", "").upper():
        dml_targets.add(e.get("target", ""))
        dml_sources.add(e.get("source", ""))

for e in new_edges:
    src, tgt, etype = e.get("source",""), e.get("target",""), e.get("edge_type","")
    # Step 1: Suppress TABLE_FLOW bypass edges (replaced by source→⟐→target chain)
    if (src in dml_sources and tgt in dml_targets
        and etype == "TABLE_FLOW"
        and src != intermediate_id and tgt != intermediate_id):
        continue
    # Step 2: Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
    if (src in dml_sources and tgt in dml_targets
        and "DML" not in etype.upper()
        and etype != "TABLE_FLOW"
        and src != intermediate_id and tgt != intermediate_id
        and intermediate_id):
        e["target"] = intermediate_id          # redirect to output
        new_dml_edges.append(e)
        continue
    # Step 3: Replace DML edges with ⟐ output → target (TABLE_FLOW)
    if "DML" in etype.upper() and intermediate_id:
        output_edge = dict(e)
        output_edge["source"] = intermediate_id
        output_edge["edge_type"] = "TABLE_FLOW"
        new_dml_edges.append(output_edge)
    else:
        new_dml_edges.append(e)
```

### Verified topology (all 5 scripts, v3.3.72)

```
step1: raw_orders        ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_orders
step2: crm_customers     ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_customers
       crm_customers     ──[FILTER]──────> ⟐ output
step3: stg_orders        ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> analytics_orders
       stg_customers     ──[TABLE_FLOW]──> ⟐ output
       stg_orders        ──[FILTER]──────> ⟐ output
       stg_orders        ──[JOIN]────────> ⟐ output
       stg_customers     ──[JOIN]────────> ⟐ output
step4: analytics_orders  ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary
       analytics_orders  ──[TRANSFORM]───> ⟐ output
       analytics_orders  ──[AGGREGATE]───> ⟐ output
step5: daily_summary     ──[TABLE_FLOW]──> ⟐ output
       daily_summary     ──[TRANSFORM]───> ⟐ output
```

All edges converge on `⟐ output` — the output node is the trunk of the data flow.

### How Step 2 catches the bypass (v3.3.72 fix)

**The output node is the trunk of the data flow.** Between source and target, all operations happen within the SELECT. The output node sits in the middle — all intermediate edges connect TO it:

Step 2 of the edge routing loop intercepts TRANSFORM/AGGREGATE edges that go directly to the DML target and redirects them to `⟐ output`:
```python
# Step 2: Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
if (src in dml_sources and tgt in dml_targets
    and "DML" not in etype.upper()
    and etype != "TABLE_FLOW"
    and src != intermediate_id and tgt != intermediate_id
    and intermediate_id):
    e["target"] = intermediate_id          # redirect to output!
```

Why `analytics_orders` is in `dml_sources`: after field promotion, the DML edge `ao.region --[DML]--> daily_summary` becomes `analytics_orders --[DML]--> daily_summary` (column promoted to parent table). So `analytics_orders` is a DML source, and the TRANSFORM edge `analytics_orders --[TRANSFORM]--> daily_summary` matches the bypass condition.

### Design note (for reference)

The root cause was that field promotion assigns computed fields (`dt`, `cnt`, `total`) to the wrong parent table when `source_tables=[]`. The Step 2 redirect fixes this at the edge level. A cleaner approach would fix it at the parent assignment level — see [Anatomy of the problem](#anatomy-of-the-problem) below.

### The output node as the trunk

```
analytics_orders                           daily_summary
       │                                         ▲
       │  ┌──────────────────────────┐           │
       ├─>│ DATE()  TRANSFORM → dt   │──┐        │
       ├─>│ SUM()   AGGREGATE → total│──┤        │
       │  └──────────────────────────┘  │        │
       │                                ▼        │
       └────────[TABLE_FLOW]────────> ⟐ output ──┘
                                      (trunk)
```

The `⟐ output` node is not a branch — it exists to **complete the chain** between source and target. Without it, intermediate operations (TRANSFORM, AGGREGATE) have nowhere to connect in the middle. They shouldn't bypass the trunk and connect directly to the target.

**Actual topology (v3.3.71):**
```
analytics_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary    ✅ trunk
analytics_orders ──[TRANSFORM ]──> daily_summary                                 ❌ bypasses trunk
analytics_orders ──[AGGREGATE ]──> daily_summary                                 ❌ bypasses trunk
```

**Expected topology:**
```
analytics_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary    ✅ trunk
analytics_orders ──[TRANSFORM ]──> ⟐ output                                     ✅ into trunk
analytics_orders ──[AGGREGATE ]──> ⟐ output                                     ✅ into trunk
```

### Root cause at the syntax tree level

The extractor produces these edges at field level:
```
ao.order_date --[TRANSFORM]--> dt       (dt = DATE(ao.order_date))
ao.amount     --[AGGREGATE]--> total    (total = SUM(ao.amount))
dt            --[DML]-------> daily_summary
total         --[DML]-------> daily_summary
```

And these SCHEMA ownership edges:
```
⟐ output --[SCHEMA]--> dt      ("dt is a column of the SELECT result")
⟐ output --[SCHEMA]--> total   ("total is a column of the SELECT result")
```

The SCHEMA edges already tell us: **`dt` and `total` belong to `⟐ output`**. When fields are promoted to their parent tables, the parent should be determined by **who owns the field**, not by iteration order.

**The bug at `_build_l2_graph:1358-1360`:**
```python
if not parent_table_id and table_nodes:
    parent_table_id = list(table_nodes.values())[0]["id"]  # arbitrary first table
```

`dt` and `total` have no `source_tables`. The code picks the first table in dict order. For INSERT scripts, `daily_summary` happens to be first → wrong parent → after field promotion, TRANSFORM/AGGREGATE edges bypass the trunk.

### Fix: use SCHEMA edges to determine parent

When a computed field has no `source_tables`, use the incoming SCHEMA edge to find who owns it. `⟐ output --[SCHEMA]--> dt` means `dt`'s parent is `⟐ output`. This is deterministic and semantic:

```python
# Line 1358-1360 — replace arbitrary first-table with SCHEMA-based lookup
if not parent_table_id and table_nodes:
    # Find which table OWNS this field via incoming SCHEMA edges
    for e in edges:
        ed = e.get("data", e)
        if ed.get("target") == nid and ed.get("relationship") == "SCHEMA":
            owner_id = ed.get("source")
            for tid, tn in table_nodes.items():
                if tn.get("original_id") == owner_id:
                    parent_table_id = tn["id"]
                    break
            if parent_table_id:
                break
    # Fallback: prefer intermediate_table
    if not parent_table_id:
        for tid, tn in table_nodes.items():
            if tn.get("type") == "intermediate_table":
                parent_table_id = tn["id"]; break
    # Last resort
    if not parent_table_id:
        parent_table_id = list(table_nodes.values())[0]["id"]
```

**Why this is correct:** After fixing parent assignment, field promotion naturally produces `analytics_orders --[TRANSFORM]--> ⟐ output` (not `daily_summary`). The `⟐ output` node becomes the trunk — ALL intermediate operations connect INTO it, and the output→target chain carries the result forward. No post-promotion edge redirection needed.

### Anatomy of the problem

The data flow graph is built in two layers, and the gap between them causes the bypass:

**Layer 1 — Extractor** (`variable_extractor_v2.py`) walks the SQL syntax tree at field level:

```
Step 4 SQL:
  INSERT INTO daily_summary
  SELECT DATE(ao.order_date) AS dt, COUNT(*) AS cnt, SUM(ao.amount) AS total
  FROM analytics_orders ao

Extractor produces:
  Variables:
    daily_summary     table        defined_in=INSERT
    analytics_orders   table        defined_in=FROM
    ao                 table        defined_in=FROM    source_tables=[analytics_orders]
    ⟐ output           virtual_table defined_in=TOP
    dt                 transform    is_output=True     source_tables=[]
    cnt                aggregate    is_output=True     source_tables=[]
    total              aggregate    is_output=True     source_tables=[]

  Dependencies:
    ao      --[TABLE_FLOW]--> ⟐ output       "data flows from alias into SELECT result"
    ⟐ output --[SCHEMA]-----> dt              "SELECT result OWNS the transform output"
    ⟐ output --[SCHEMA]-----> cnt             "SELECT result OWNS the aggregate output"
    ⟐ output --[SCHEMA]-----> total           "SELECT result OWNS the aggregate output"
    dt      --[DML]---------> daily_summary    "transform result is INSERTED into target"
    cnt     --[DML]---------> daily_summary    "aggregate result is INSERTED into target"
    total   --[DML]---------> daily_summary    "aggregate result is INSERTED into target"
    ao.order_date --[TRANSFORM]--> dt          "DATE() operates on order_date"
    ao.amount --[AGGREGATE]-----> total         "SUM() operates on amount"
```

The extractor does two things correctly:
1. Creates `⟐ output` and connects SCHEMA edges to output fields — *it knows who owns each field*
2. Creates DML edges from output fields to the INSERT target — *it knows where the data goes*

The extractor does one thing wrong:
- `dt` and `total` have `source_tables=[]` because `_extract_table_names` (line 182) only finds `exp.Table` nodes, not column prefixes like `ao` in `ao.order_date`

**Layer 2 — Graph builder** (`dataflow_service.py:_build_l2_graph`) promotes fields to table level:

```
Field promotion ("who does this field belong to?"):
  ao.order_date → parent=analytics_orders  (found via prefix "ao")
  dt            → parent=???                (no source_tables, no prefix)
  cnt           → parent=???                (no source_tables, no prefix)
  total         → parent=???                (no source_tables, no prefix)
```

For columns (`ao.order_date`), the parent is found via the dot prefix: `ao` → resolved to `analytics_orders`. For computed fields (`dt`, `cnt`, `total`), there's no dot prefix and no `source_tables`. The code falls through to line 1358-1360:

```python
if not parent_table_id and table_nodes:
    parent_table_id = list(table_nodes.values())[0]["id"]  # ← arbitrary
```

`table_nodes` dict order depends on variable extraction order. For INSERT scripts, `daily_summary` (INSERT target) happens to be first → `dt`/`cnt`/`total` get `parent=daily_summary`.

**After promotion with wrong parent:**
```
ao.order_date → parent=analytics_orders
dt            → parent=daily_summary     ← WRONG
cnt           → parent=daily_summary     ← WRONG
total         → parent=daily_summary     ← WRONG
```

Edges are promoted to their parents' level:
```
ao.order_date --[TRANSFORM]--> dt
  ↓ parent=analytics_orders     ↓ parent=daily_summary
  = analytics_orders --[TRANSFORM]--> daily_summary   ← bypass!
```

**Layer 3 — Simplification 1** converts DML edges but doesn't touch TRANSFORM/AGGREGATE:
```python
if (src in dml_sources and tgt in dml_targets
    and etype == "TABLE_FLOW"           # ← only catches TABLE_FLOW
    and src != intermediate_id ...):
    continue
```

TRANSFORM and AGGREGATE edges don't match `etype == "TABLE_FLOW"` → pass through unfiltered → end up in the final graph as direct `analytics_orders → daily_summary` bypass edges.

### Complete data flow trace (why each edge should route through output)

For `INSERT INTO daily_summary SELECT DATE(ao.order_date) AS dt, ... FROM analytics_orders ao`:

```
Level of operation          Data flow
────────────────────────────────────────────────────
Source table:               analytics_orders
                                │
Column reference:           ao.order_date
                                │ [TRANSFORM: DATE()]
Computed value:             dt
                                │
                                ├── dt is part of ⟐ output (SCHEMA edge)
                                │
SELECT result:              ⟐ output ──────────────┐
                                │                    │
                                │ [TABLE_FLOW]       │ [TABLE_FLOW]
                                ▼                    ▼
INSERT target:              daily_summary ◄─────────┘
```

The TRANSFORM happens *within* the SELECT — `DATE(ao.order_date)` produces `dt` which is a column OF the SELECT result. The edge `analytics_orders --[TRANSFORM]--> dt` should go INTO `⟐ output` (because `dt` belongs to `⟐ output`), not directly to `daily_summary`. The `⟐ output → daily_summary` TABLE_FLOW edge (created by Simplification 1) carries the complete result forward.

### Why the SCHEMA edge is the correct signal

SCHEMA means "this table owns this column." When the extractor says:

```
⟐ output --[SCHEMA]--> dt
```

It means: *dt is a column of the SELECT result set.* Therefore, `dt`'s parent in the L2 graph should be `⟐ output`. Every computed output field has a SCHEMA edge from `⟐ output` (created at `dependency_graph.py:257-271`, Pass 4c). Using SCHEMA edges for parent assignment is:
- **Deterministic** — doesn't depend on variable iteration order
- **Semantic** — SCHEMA literally encodes the ownership relationship
- **Already correct** — the extractor already produces these edges for every output field

### Evolution

| Version | State | Symptom |
|---------|-------|---------|
| v3.3.65 | ❌ BUG | Two nodes labeled `"⟐ output"` |
| v3.3.66 | ⚠️ REGRESSION | Duplicate real-table labels |
| v3.3.69 | ❌ BROKEN | Dangling edge references |
| v3.3.70 | ❌ BROKEN | Broken topology (bypass) |
| v3.3.71 | ⚠️ PARTIAL | qo_ eliminated, steps 1-3 correct, step4 bypass remains |
| v3.3.72 | ✅ FIXED | Step 2 redirects TRANSFORM/AGGREGATE through output |

### Files Involved
- `backend/app/extractor/variable_extractor_v2.py:182-192` — `_extract_table_names` (gap: misses column prefixes)
- `backend/app/extractor/variable_extractor_v2.py:738-739` — where `src_tables` is populated for computed nodes
- `backend/app/extractor/dependency_graph.py:257-271` — Pass 4c: SCHEMA edges from output container to fields
- `backend/app/services/dataflow_service.py:1349-1360` — fallback parent assignment
- `backend/app/services/dataflow_service.py:1565-1600` — Simplification 1 (TABLE_FLOW routing)

### Two complementary fixes (extractor + graph builder)

**Fix 1 — Extractor: enhance `_extract_table_names` to capture column prefixes**

`_extract_table_names` (line 182) only finds `exp.Table` nodes. It misses table aliases inside column references:

```
DATE(ao.order_date):  extract_tables=[]     col_prefix=['ao']  ← missed!
SUM(ao.amount):       extract_tables=[]     col_prefix=['ao']  ← missed!
COUNT(*):             extract_tables=[]     col_prefix=[]       ← correct
```

Enhance it to also extract table prefixes from `exp.Column.table`:
```python
def _extract_table_names(expr: exp.Expression) -> list[str]:
    tables = set()
    if expr is None or not hasattr(expr, 'walk'):
        return []
    for node in expr.walk():
        if isinstance(node, exp.Table):
            name = _clean(node.name or "")
            if name: tables.add(name)
        elif isinstance(node, exp.Column):           # ← new
            tbl_prefix = _clean(node.table or "")     # ← new
            if tbl_prefix: tables.add(tbl_prefix)    # ← new
    return list(tables)
```

Result: `dt` gets `source_tables=["ao"]`, `total` gets `source_tables=["ao"]`. The graph builder can resolve `ao` → `analytics_orders` via the existing alias map.

**Fix 2 — Graph builder: SCHEMA-based parent lookup for `source_tables=[]` fallback**

For nodes that still have `source_tables=[]` after the extractor fix (e.g., `COUNT(*)` → `cnt`), replace the arbitrary `list(table_nodes.values())[0]` at line 1358-1360 with SCHEMA-based lookup:
```python
if not parent_table_id and table_nodes:
    # Find which table OWNS this field via incoming SCHEMA edges
    for e in edges:
        ed = e.get("data", e)
        if ed.get("target") == nid and ed.get("relationship") == "SCHEMA":
            owner_id = ed.get("source")
            for tid, tn in table_nodes.items():
                if tn.get("original_id") == owner_id:
                    parent_table_id = tn["id"]; break
            if parent_table_id: break
    # Prefer intermediate_table as fallback
    if not parent_table_id:
        for tid, tn in table_nodes.items():
            if tn.get("type") == "intermediate_table":
                parent_table_id = tn["id"]; break
    # Last resort
    if not parent_table_id:
        parent_table_id = list(table_nodes.values())[0]["id"]
```

| Node | `source_tables` after Fix 1 | Parent found by |
|------|---------------------------|-----------------|
| `dt` | `["ao"]` | `source_tables` → `ao` → `analytics_orders` |
| `total` | `["ao"]` | `source_tables` → `ao` → `analytics_orders` |
| `cnt` | `[]` (COUNT(*)) | SCHEMA edge `⟐ output → cnt` |

### Defect: missing SCHEMA edges for computed nodes

**Potential gap:** The SCHEMA-based fallback (Fix 2) relies on the extractor producing `⟐ output --[SCHEMA]--> field` edges. These are created at `dependency_graph.py:257-271` (Pass 4c) for all variables where `is_output=True` and the variable is not table-like. Currently this works for all tested scripts. However, if a computed node is ever produced with `is_output=False` (e.g., inside a subquery context, or a new edge case), it would lack a SCHEMA edge and fall through to the `intermediate_table` preference.

**Tracking:** If in the future a computed field appears in the L2 graph with the wrong parent (attached to a random table), first check whether the extractor produced a SCHEMA edge to it. If not, the extractor's Pass 4c logic needs to be broadened to cover that context.

---

## Bug 3: Edge Ranges Overlap (P2) — PARTIALLY FIXED 🔧 v3.3.72

### v3.3.72 Status

- ✅ Compound edge types split — no commas in output edges
- ✅ TABLE_FLOW+DML collision eliminated (Simplification 1 removed the DML edges)
- ⚠️ Same-type co-location remains — step3: 2 lines, step4: 1 line

### Quantitative Test Results (v3.3.71)

| Script | Overlapping lines | Max edges/line | Pattern |
|--------|-------------------|----------------|---------|
| step1 | 0 | 1 | — |
| step2 | 0 | 1 | — |
| step3 | 2 | 2 | TABLE_FLOW×2 on FROM line 4; JOIN×2 on JOIN line 5 |
| step4 | 1 | 2 | TRANSFORM+AGGREGATE on SELECT line 3 |
| step5 | 0 | 1 | — |

### Overlap trend

| Script | v3.3.65 | v3.3.69 | v3.3.70 | v3.3.71 | Status |
|--------|---------|---------|---------|---------|--------|
| step1 | 2 | 2 | 0 | 0 | ✅ |
| step2 | 2 | 2 | 0 | 0 | ✅ |
| step3 | 10 (max 4) | 3 (max 4) | 3 (max 2) | 2 (max 2) | 🔧 |
| step4 | 3 | 3 | 1 | 1 | 🔧 |
| step5 | 0 | 0 | 0 | 0 | ✅ |

### Remaining overlap

1. **step3 line 4**: Two TABLE_FLOW edges (stg_orders→output, stg_customers→output) both point to the FROM clause. Semantically correct — both tables ARE in the FROM clause.

2. **step3 line 5**: Two JOIN edges both point to the JOIN keyword. Semantically correct.

3. **step4 line 3**: TRANSFORM and AGGREGATE edges on the same SELECT expression line.

All remaining overlaps are same-type co-location on shared keywords — the edges legitimately share the same SQL token. The compound type splitting and qo_ elimination have resolved the spurious overlaps.

### Suggested approach

Accept these as semantically correct. Further sub-line partitioning (character-level ranges within a line) would add complexity for marginal UX benefit.

### Files Involved
- `backend/app/services/dataflow_service.py:1472-1487` — compound edge splitting
- `backend/app/services/sql_range_finder.py:557-643` — `partition_edge_ranges`

---

## Design Simplification Recommendations

### ✅ Simplification 1: Eliminate `qo_` — APPLIED v3.3.71

The qo_ node has been eliminated. DML edges now route through the existing `"⟐ output"` intermediate_table. Result: correct topology, zero duplicate labels, no dangling references. Net: ~30 lines removed.

### Simplification 2: Split compound edges BEFORE range finding

Would resolve the remaining Bug 3 overlap for step4 (TRANSFORM+AGGREGATE). Already partially done — compound types are split in output but still computed with a single `find_sql_range` call before splitting. Moving the split before range computation would give each type its own accurate range.

### Simplification 3: Extract L2 graph builder

`dataflow_service.py` at ~1950 lines would benefit from splitting out the L2 builder (~700 lines) into `l2_graph_builder.py`.

---

## Historical Analysis (from original doc)

The original doc suggested checking `table_name == f"query_output_{src[:8]}"` to prevent duplicate qo_ nodes. This was wrong — the mechanism-1 node has `table_name = "⟐ output"`, not a query_output prefix. The actual fix (Simplification 1) eliminated the qo_ node entirely rather than trying to deduplicate it.

**Original analysis preserved for reference:**

**Symptom:** `⟐ output` appears twice in L2 graph for INSERT...SELECT scripts.

**Root cause:** Two mechanisms create output nodes — variable extractor's `is_output_node` flag and DML edge routing's `qo_` node — both labeled `"⟐ output"`.

**Original suggested fix** (incorrect):
```python
existing_output = any(
    tn.get("table_name") == f"query_output_{src[:8]}" 
    for tn in table_nodes.values()
)
if not existing_output:
    table_nodes[qo_id] = {...}
```
