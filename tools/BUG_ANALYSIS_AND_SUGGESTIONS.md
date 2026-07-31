# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-31 | **Version:** 3.3.123 | **Active:** 10 bugs (6 root patterns)
>
> Fixed bugs are in [`BUG_HISTORY.md`](BUG_HISTORY.md). Historical analyses are in [`wiki/`](../wiki/).
>
> **Root cause patterns** (2026-07-31 analysis):
> 1. **Dual extraction with diverging fallbacks** (Bug 47, Bug 39) — P1
> 2. **Field promotion before edge survival check** (Bug 45, Bug 46) — P2
> 3. **Name resolution rebuilt in consumers** (Bug 48) — P3
> 4. **Column position never extracted from AST** (Bug 43) — P3
> 5. **Indexer records only one side of DML name mapping** (Bug 41) — P3
> 6. **Frontend-backend contract gap** (Bug 42, Bug 33) — P2/P3

---

## Prerequisites for Simplified Architecture (SOLUTION_DESIGN.md)

> All name resolution moves to the extractor. L1/L2 just read pre-resolved data.

| # | Task | Priority | File |
|---|------|----------|------|
| P1 | ✅ Done — `pair_index[(table,field)] → {scripts}` during indexing | — | `folder_index_service.py:154` |
| P2 | ✅ Done — `build_graph_data` resolves alias→canonical via `source_tables` | — | `graph_service.py:120-163` |
| P3 | ✅ Done — `_classify_tables` uses canonical names; sets `⟐ result` for SELECT-only | — | `multi_script_service.py:26-42` |
| P4 | ✅ Done — Record fields per table: SCHEMA + DML | — | `graph_service.py:217-265` |
| P5 | ✅ Done — Sync alias↔canonical fields + pre-build `alias_map` | — | `graph_service.py:218` |
| ⚠️ | P2/P5 consumers still rebuild alias_map (harmless duplication) | P3 | `l1_builder.py:784`, `l2_builder.py:187` — should read pre-built map |
| P6 | ✅ Done — fallback label matching removed from `compute_field_lineage` | — | `lineage.py:157` |
| Doc | ✅ Done — TABLE_FLOW docstring: "bidirectional — always follow" | — | `lineage.py:33` |
| ⚠️ | **P1–P6 consumers still use per-node field_name extraction instead of P4 table_fields** | P1 | `l1_builder.py:700-960` — see Pattern 1 |

---

## Quick Status

| Bug | Priority | Status | Notes |
|-----|----------|--------|-------|
| Bug 24: Empty Table Cleanup (R18.1) | P2 | ✅ Fixed | 24a/24b/24c all resolved; API + E2E verified |
| Bug 25: L2 UnboundLocalError on cache hit | P1 | ✅ Fixed | table_schemas=None at line 277 |
| Bug 26: Terminal marker disconnected from downstream scripts | P2 | 🔧 Requirement changed | Outgoing edges now KEPT per R18.1 update; Bug 26 closed |
| Bug 27: L1 lineage_field_pairs extraction bug | P1 | ✅ Fixed (v3.3.110) | table_name/field_name added in build_graph_data; L1 reads directly |
| Bug 28: Alias/output field sync invariant violation | P2 | ✅ Fixed (v3.3.110) | Alias sync + DML phantom fields working; stg_customers(1f) ✅ |
| Bug 29: DML phantom field sync broken by field promotion | P2 | ✅ Fixed (v3.3.110) | Sync 2 now handles table IDs post-promotion |
| Bug 30: L1 over-inclusion — raw_orders/stg_orders.customer_id | P2 | ✅ Fixed (v3.3.114) | `if` guard removed; constrained union works on fresh + cached workspaces |
| Bug 31: ⟐ output table has 0 fields in step2 L2 | P3 | ✅ Fixed (v3.3.111) | SCHEMA edges now populate output table fields; ⟐ output(1f) ✅ |
| Bug 32: Alias table label rendered below compound node | P3 | ✅ Fixed (v3.3.111) | alias_table label now positioned above, consistent with other types |
| Bug 33: ALIAS edges cross in step3 L2 | P3 | Open | Pattern 6 — needs control-point-distances + rebuild |
| Bug 39: P6 removed fallback — seed matching fails for alias columns | P1 | 🔧 Combined with Bug 47 | See Bug 47 (Pattern 1) — same dual-extraction root |
| Bug 40: Multi-hop lineage missing — only 1-hop traced | P2 | ✅ Fixed (v3.3.121) | Iterative chaining; analytics_orders.amount → 3 hops |
| Bug 41: INSERT column vs SELECT alias mismatch | P3 | Open | Pattern 5 — indexer records only SELECT alias, not INSERT column |
| Bug 42: L2 edge click shows no highlighted SQL lines | P2 | Open | Pattern 6 — frontend wiring missing: edge tap → sql_range → SqlPanel |
| Bug 43: sql_range column always 1 | P3 | Open | Pattern 4 — AST node positions never captured; RangeBuilder hardcodes `start_col=1` |
| Bug 44: Step3 L2 so/stg_orders missing customer_id field | P2 | Open | Need verification — may be correct behavior (JOIN is conditional) |
| Bug 45: Step3 L2 missing so→⟐ output JOIN edge | P2 | Open | Pattern 2 — filter_relevant removes JOIN edges before promotion |
| Bug 46: Step3 L2 TABLE_FLOW bypasses ⟐ output | P3 | Open | Pattern 2 — suppression check too narrow (only dml_source→dml_target) |
| Bug 47: Naive+constrained unions diverge on table field pairs | P1 | Open | Pattern 1 — DML propagation outside per-script loop (uses wrong gdata) + no non-column skip in constrained union |
| Bug 48: L1/L2 rebuild alias_map from scratch | P3 | Open | Pattern 3 — alias_map not stored in graph cache; consumers reconstruct |
| Bug 34: SUBQUERY edge silently ignored in BFS | P2 | ✅ Fixed (v3.3.115) | Added to _ALWAYS_BIDIR |
| Bug 35: Seed matching doesn't follow ALIAS chains | P2 | ✅ Fixed (v3.3.115) | ALIAS-transitive closure before SCHEMA validation |
| Bug 36: `if _production_pairs:` guard still present | P2 | ✅ Fixed (v3.3.115) | Guard removed; always intersects |
| Bug 37: Constrained union and lineage BFS use different edge sets | P3 | 🔧 Partial | Unified BFS deployed but reverted for SCHEMA directionality |
| Bug 38: TABLE_FLOW: formal def says follow, code says skip | P2 | ✅ Fixed (v3.3.115) | Added to _ALWAYS_BIDIR; docstring needs update |

---

## Bug 24: Empty Table Cleanup After Lineage (R18.1)

> **Found:** v3.3.105 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.106)

**Symptom:** Querying `stg_customers.customer_id` in lineage mode shows `analytics_orders` (0 fields), `daily_summary` (0 fields), and `Query Result` as empty table nodes. `customer_id` is used only in a JOIN condition but not INSERTed — the data flow terminates at `stg_orders.customer_id`/`stg_customers.customer_id`.

**Requirement:** R18.1 — keep field-bearing tables + one terminal marker (immediate downstream table with 0 fields), remove all further empty tables and edges.

### Current state

An uncommitted implementation exists in the working tree with the R18.1 cleanup logic in `_filter_l1_by_lineage`. Chromium E2E testing revealed two bugs:

---

### Bug 24a (P1): `UnboundLocalError` — `filtered_edges` referenced before assignment

**Location:** `_filter_l1_by_lineage`, R18.1 cleanup block (~lines 348, 357, 371)

The R18.1 cleanup code iterates `filtered_edges`:
```python
for e in filtered_edges:  # line 348 — UnboundLocalError!
    ed = e.get("data", e)
    ...
filtered_edges = [e for e in filtered_edges ...]  # line 371 — same error
```

But `filtered_edges` is only assigned at line 371 *after* being used. The variable doesn't exist when first referenced. This is a NameError at runtime — the search API returns HTTP 500.

**Fix:** Change all three `filtered_edges` references to `edges` (the input edges from the function parameter `edges = l1_graph.get("edges", [])` at line 307). The R18.1 cleanup operates on the full edge set to find terminal tables — it doesn't need pre-filtered edges.

```python
# Lines 348, 357: change "filtered_edges" to "edges"
for e in edges:  # was: for e in filtered_edges

# Line 371: change "filtered_edges" to "edges"
filtered_edges = [e for e in edges ...]  # was: filtered_edges
```

---

### Bug 24b (P1): Propagated "indirect" fields prevent table removal

**Location:** `_filter_l1_by_lineage`, name-based filter at line 330-335

The name-based filter keeps ALL fields named `customer_id` regardless of `field_group`:
```python
if ntype == "field":
    fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
    if fname == keep_field_suffix:       # matches ALL "customer_id" fields
        filtered_nodes.append(n)         # includes propagated indirect ones
```

`_build_l1_graph` propagates fields to downstream tables (line 787-945). For example, `customer_id` is propagated from `stg_orders` into `analytics_orders` and `daily_summary` as `field_group: "indirect"`. These propagated fields survive the name-based filter because they're still named `customer_id`.

Result: `analytics_orders` and `daily_summary` each have 1 "indirect" `customer_id` field → they appear in `field_parent_ids` → R18.1 cleanup keeps them because they "have fields." The cleanup can never remove them.

**Fix:** Add a `field_group == "direct"` check to the name-based filter:
```python
if ntype == "field":
    fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
    fg = nd.get("field_group", "")
    if fname == keep_field_suffix and fg == "direct":  # ← add "and fg == 'direct'"
        filtered_nodes.append(n)
```

This drops propagated indirect fields, leaving `analytics_orders` with 0 fields.

---

### Bug 24c (P1): ✅ Fixed — `scripts_with_fields` populated with table IDs, not script IDs

**Location:** `_filter_l1_by_lineage` in `dataflow_service.py`, lines 195-205

**Original issue:** The R18.1 code tried to identify "scripts that have fields" by checking field nodes' `parent` attribute:

```python
scripts_with_fields = set()
for n in filtered_nodes:
    nd = n.get("data", n)
    if nd.get("type") == "field" and nd.get("parent"):
        scripts_with_fields.add(nd.get("parent"))  # ← adds TABLE IDs, not script IDs!
```

In the L1 graph, a field's `parent` is the **table** compound node (e.g., `tbl_stg_customers`), not the script node. So `scripts_with_fields` ends up containing table IDs like `{tbl_crm_customers, tbl_raw_orders, tbl_stg_orders, tbl_stg_customers}`.

Then at line 199:
```python
if ed.get("edge_type") == "writes_to" and ed.get("source") in scripts_with_fields:
```

`writes_to` edges go from **script** → table. The `source` is a script ID like `841cfba0d103`, but `scripts_with_fields` has table IDs like `tbl_stg_orders`. The check **never matches** → `terminal_table_ids` is always empty → no terminal marker is ever kept → `analytics_orders` is silently removed.

**Effect:** The R18.1 cleanup removes ALL empty tables including the terminal marker. `analytics_orders` disappears from L1. The data flow looks like it "jumps" from step3 directly to nothing — no visual indication of where the field's value terminates.

**Fix:** Derive `scripts_with_fields` from the graph **edges** instead of field `parent`:

```python
# After computing field_parent_ids (line 207):
scripts_with_fields = set()
for e in edges:
    ed = e.get("data", e)
    if ed.get("edge_type") in ("reads_from", "writes_to"):
        src, tgt = ed.get("source"), ed.get("target")
        if src in field_parent_ids:
            scripts_with_fields.add(tgt)
        if tgt in field_parent_ids:
            scripts_with_fields.add(src)
```

This finds scripts connected to field-bearing tables via any edge direction. Then the terminal marker logic at line 199 works correctly: `ed.get("source") in scripts_with_fields` matches script IDs.

**Fix applied** (lines 195-205): `scripts_with_fields` is now derived from graph edges — scripts connected to field-bearing tables via `reads_from`/`writes_to` edges. Confirmed working via API and E2E screenshot.

---

### Verified result (all 3 fixes)

### Expected result after both fixes

Query `stg_customers.customer_id` in lineage mode:

| Table | Fields | Kept? | Reason |
|-------|--------|-------|--------|
| `crm_customers` | 1 (`customer_id`) | ✅ | Field-bearing |
| `raw_orders` | 1 (`customer_id`) | ✅ | Field-bearing |
| `stg_customers` | 1 (`customer_id`) | ✅ | Field-bearing (target) |
| `stg_orders` | 1 (`customer_id`) | ✅ | Field-bearing |
| `analytics_orders` | 0 | ✅ | Terminal marker (step3 writes to it) |
| `daily_summary` | 0 | ❌ removed | Producer (step4) has 0 direct fields |
| `Query Result` | 0 | ❌ removed | No direct fields |

**Files:** `backend/app/services/dataflow_service.py:304-345` (`_filter_l1_by_lineage`)

---

## Recently Fixed (v3.3.103–104)

| Bug | Version | Description |
|-----|---------|-------------|
| Bug 19 | v3.3.103 | L1 ID mapping gap — `original_id` now populated on field nodes |
| Bug 20 | v3.3.103 | L2 `table_schemas` NameError on cache hit — initialized on both paths |
| Bug 21 | v3.3.103 | `lineage.py` Fallback 2 dead code — removed |
| Bug 22 | v3.3.103 | `get_level2_graph` double cache load — `preloaded_graph` param added |
| Bug 23 | v3.3.104 | `_build_l2_graph` cache-miss `else:` missing — added + re-indented |

See [`BUG_HISTORY.md`](BUG_HISTORY.md) for all fixed bugs.

---

## Bug 30: `raw_orders.customer_id` and `stg_orders.customer_id` Over-Included in L1

> **Found:** v3.3.110 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.114)

**Symptom:** Querying `stg_customers.customer_id` shows `raw_orders.customer_id` and `stg_orders.customer_id` in L1. These fields share the name `customer_id` but are on a different branch — their values flow through `stg_orders`, which JOINs `stg_customers` on equality but doesn't produce into it.

**Root cause:** `compute_field_lineage` in `lineage.py` has a fallback label-matching path (line 122-137). When the SCHEMA-validated seed lookup fails (because no column is directly SCHEMA-connected to `stg_customers`), the fallback finds ALL nodes whose label ends with `customer_id`:

```python
if (label == full_name or label == target_field or
    '.' in label and label.rsplit('.', 1)[-1] == target_field):
    seed_ids.add(nid)
```

This adds `o.customer_id`, `c.customer_id`, `sc.customer_id`, `so.customer_id` — all `customer_id` columns across all scripts — as seeds. The BFS expands from all of them, producing per-script R sets that include unrelated fields. These then pass through `lineage_field_pairs` → alias resolution → appear in L1.

**The cross-script constrained union (Flaw 3 in formal definition) is not implemented.** The formal definition says: "fields excluded by conditional edges (JOIN/FILTER) in ANY script are excluded from R₁." But the current implementation does a simple union of per-script R sets without the constraint.

### Fix — Per-edge-type strategy for cross-script constrained union

The core question: given a `(table, field)` pair from the naive per-script union, does this field actually flow into/out of the target `(stg_customers, customer_id)`?

The answer depends on the **edge types** connecting the field to the target, not on the field's name. Two fields both named `customer_id` may have entirely different relationships to the target.

#### Edge type strategy for cross-script lineage

```
16 edge types → 3 categories for cross-script propagation:
```

**Category 1 — Value-carrying (propagates):** The field's value actually flows through this edge. If this edge connects the field to the target, the field IS in the lineage.

| Edge | Notation | Production? | Cross-script rule |
|------|----------|:-----------:|------|
| DML | `column → table` | ✅ | If target_table is the queried table, column IS in lineage. This is THE key edge. `c.customer_id --DML--> stg_customers` → `c.customer_id` produces the target's value. |
| REF | `col → expr` | ✅ | If col ∈ R, expr ∈ R. `order_id --REF--> total` → total is in lineage. |
| TRANSFORM | `col → result` | ✅ | Value transformed but preserved. `COALESCE(cid, 0) AS cid_clean` — cid_clean ∈ R. |
| AGGREGATE | `col → agg` | ✅ | `SUM(amount) AS total` — total ∈ R if amount ∈ R, and vice versa. |
| WINDOW | `col → win` | ✅ | `RANK() OVER (PARTITION BY dept)` — rank ∈ R if dept ∈ R. |
| COMPUTED | `col → case` | ✅ | `CASE WHEN x>100 THEN 'high'` — result ∈ R if x ∈ R. |
| ALIAS | `orig → alias` | ✅ | Purely naming. `stg_customers --ALIAS--> sc` → `sc.customer_id` IS `stg_customers.customer_id`. Both sides connected. |

**Category 2 — Structural (propagates for connectivity):** Doesn't carry field values directly but provides graph connectivity. Useful for reaching tables that own columns.

| Edge | Notation | Cross-script rule |
|------|----------|------|
| SCHEMA | `table → col` | ↑ (col→table): always adds table. ↓ (table→col): production-filtered — only columns with a production edge from R are added. |
| TABLE_FLOW | `table → output` | Connects table to output container. Follow for connectivity. |
| SUBSET | `comp → main` | Connectivity bridge. Always follow. |
| SET_OP | `branch → parent` | UNION branches connected. Always follow. |
| CORRELATED | `outer → inner` | Subquery reference. Always follow. |
| INDIRECT | `defined → ref` | HAVING→SELECT match. Always follow. |

**Category 3 — Conditional (does NOT propagate values):** These edges test conditions or filter rows. They do not produce, transform, or move field values. A field connected to the target ONLY via these edges is NOT in the lineage.

| Edge | Notation | Cross-script rule |
|------|----------|------|
| **JOIN** | `table/col → output` | `ON so.customer_id = sc.customer_id` — the JOIN tests equality but does NOT produce either field's value. `sc.customer_id`'s value comes from DML in step2, not from the JOIN. **Excluded from lineage unless also connected via Production edges.** |
| **FILTER** | `col → output` | `WHERE region = 'NA'` — filters rows, doesn't produce `region`'s value. **Excluded from lineage unless also connected via Production edges.** |

#### Algorithm

```python
# After computing per-script naive lineage_field_pairs (line 775),
# apply constrained union using per-edge-type strategy:

production_connected = set()  # (table, field) pairs validated by production path

PRODUCTION_EDGES = {"REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED", "DML", "ALIAS"}
STRUCTURAL_EDGES = {"SCHEMA", "TABLE_FLOW", "SUBSET", "SET_OP", "CORRELATED", "INDIRECT"}
# JOIN and FILTER are NOT in either set — they do NOT propagate

for s in all_scripts:
    gdata = s.get("graph", {})
    if not gdata: continue
    
    # Step A: Find the target table in this script's graph
    target_table_id = None
    for n in gdata.get("nodes", []):
        nd = n.get("data", n)
        if nd.get("label") == target_table and \
           nd.get("variable_type") in ("table", "view", "virtual_table"):
            target_table_id = nd.get("id")
            break
    if not target_table_id:
        continue  # script doesn't contain the target table → skip entirely
    
    # Step B: Build adjacency
    adj = {}
    for e in gdata.get("edges", []):
        ed = e.get("data", e)
        etype = ed.get("edge_type") or ed.get("relationship", "")
        adj.setdefault(ed["source"], []).append((ed["target"], etype, "forward"))
        adj.setdefault(ed["target"], []).append((ed["source"], etype, "reverse"))
    
    # Step C: BFS from target_table through Production + Structural edges only
    # JOIN and FILTER edges are NOT traversed
    visited = {target_table_id}
    queue = [target_table_id]
    while queue:
        nid = queue.pop(0)
        for (neighbor, etype, direction) in adj.get(nid, []):
            if neighbor in visited:
                continue
            should_follow = False
            
            if etype in PRODUCTION_EDGES:
                should_follow = True
            elif etype in STRUCTURAL_EDGES:
                if etype == "SCHEMA":
                    # ↑ (col→table): always. ↓ (table→col): production-filtered
                    if direction == "reverse":
                        should_follow = True
                    else:
                        # table→col: only if col has production from R
                        for (n2, e2, d2) in adj.get(neighbor, []):
                            if n2 in visited and e2 in PRODUCTION_EDGES and d2 == "reverse":
                                should_follow = True
                                break
                else:
                    should_follow = True
            # JOIN, FILTER: should_follow stays False — NOT traversed
            
            if should_follow:
                visited.add(neighbor)
                queue.append(neighbor)
    
    # Step D: Extract (table_name, field_name) from visited nodes
    for n in gdata.get("nodes", []):
        nd = n.get("data", n)
        if nd.get("id") in visited:
            tn = nd.get("table_name", "")
            fn = nd.get("field_name", "")
            if tn and fn:
                production_connected.add((tn, fn))

# Step E: Constrain the naive union
lineage_field_pairs = {p for p in lineage_field_pairs if p in production_connected}
lineage_field_pairs.add((table, field))  # always keep target
```

#### Trace for `stg_customers.customer_id` in multi_workflow

```
step1: target_table="stg_customers" → NOT in graph → SKIP
       → contributes: nothing

step2: target_table="stg_customers" → FOUND (INSERT target)
       BFS from stg_customers:
         DML↑: c.customer_id → stg_customers (PRODUCTION → follow)
         DML↑: c.full_name → stg_customers (PRODUCTION → follow)
         TABLE_FLOW↑: c → stg_customers (STRUCTURAL → follow)
         From c: ALIAS↑: crm_customers → c (PRODUCTION → follow)
       → visited includes: stg_customers, c.customer_id, c, crm_customers
       → production_connected += {(c, customer_id), (crm_customers, customer_id)}

step3: target_table="stg_customers" → FOUND (JOIN source)
       BFS from stg_customers:
         ALIAS↓: stg_customers → sc (PRODUCTION → follow)
         From sc: SCHEMA↓ (production-filtered): sc.customer_id
           → check production from visited: sc.customer_id --JOIN--> ⟐ output
           → JOIN is NOT production → NOT added
         TABLE_FLOW↓: sc → ⟐ output (STRUCTURAL → follow)
       → visited includes: stg_customers, sc, ⟐ output
       → sc.customer_id NOT in visited (blocked by JOIN)
       → so.customer_id NOT reachable (would need to traverse JOIN from so side)
       → production_connected += {} (no new column pairs)

step4: target_table="stg_customers" → NOT in graph → SKIP
step5: target_table="stg_customers" → NOT in graph → SKIP

Constrained union:
  naive pairs: {(crm_customers,customer_id), (raw_orders,customer_id),
                (stg_customers,customer_id), (stg_orders,customer_id)}
  production_connected: {(c, customer_id), (crm_customers, customer_id)}
  after constraint: {(crm_customers, customer_id), (stg_customers, customer_id)}
```

**Result:** L1 shows exactly 2 fields: `crm_customers.customer_id` (upstream source) + `stg_customers.customer_id` (target). `raw_orders.customer_id` and `stg_orders.customer_id` excluded.

### Simplified implementation

The graph data is already loaded in the loop at lines 702-748. Add the constrained union as a **second loop** after line 775 (after `lineage_field_pairs.add((table, field))`). Both loops iterate `all_scripts` and use the same `gdata`:

```python
# After line 775, add constrained union:
# ── Bug 30: Constrained union — exclude pairs without production path ──
PRODUCTION_EDGES = {"REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED", "DML", "ALIAS"}
production_connected = set()  # (table, field) validated by production path

for s in all_scripts:
    gdata = s.get("graph", {})
    if not gdata: continue
    
    # (same graph-loading logic as lines 704-748)
    nodes = gdata.get("nodes", [])
    edges_list = gdata.get("edges", [])
    
    # Find target table in this script
    target_id = None
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("label") == table and nd.get("variable_type") in ("table","view","virtual_table"):
            target_id = nd.get("id")
            break
    if not target_id:
        continue
    
    # BFS from target through production edges only (skip JOIN/FILTER)
    adj = {}
    for e in edges_list:
        ed = e.get("data", e)
        etype = ed.get("edge_type") or ed.get("relationship", "")
        adj.setdefault(ed["source"], []).append((ed["target"], etype, "forward"))
        adj.setdefault(ed["target"], []).append((ed["source"], etype, "reverse"))
    
    visited = {target_id}
    queue = [target_id]
    while queue:
        nid = queue.pop(0)
        for (nb, etype, direction) in adj.get(nid, []):
            if nb in visited: continue
            if etype in PRODUCTION_EDGES or \
               etype in ("SCHEMA","TABLE_FLOW","SUBSET","SET_OP","CORRELATED","INDIRECT"):
                visited.add(nb)
                queue.append(nb)
            # JOIN, FILTER: NOT traversed
    
    # Collect (table, field) from visited nodes
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("id") in visited:
            tn = nd.get("table_name", "")
            fn = nd.get("field_name", "")
            if tn and fn:
                production_connected.add((tn, fn))

# Remove pairs not validated by any script
lineage_field_pairs = {p for p in lineage_field_pairs if p in production_connected}
lineage_field_pairs.add((table, field))  # always keep target
```

This is ~40 lines. The graph-loading logic (lines 704-748) already has two patterns for getting `gdata` — the constrained union loop copies the same pattern.

**Files:** `backend/app/services/l1_builder.py` — add after line 775

---

## Bug 31: `⟐ output` Table Has 0 Fields in L2

> **Found:** v3.3.110 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.111)

**Fix applied:** SCHEMA-based output table field population in `l2_builder.py:608-648`. Output table fields are now populated from SCHEMA edges read from the full graph (before lineage filtering).

**Files:** `backend/app/services/l2_builder.py:608-648`

---

## Bug 32: Alias Table Label Positioned Below Compound Node

> **Found:** v3.3.110 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.111)

**Fix applied:** Alias table label now uses same `text-valign: top` positioning as other compound node types.

**Files:** `frontend/src/utils/graphStyles.js`

### Remaining issue — `if _production_pairs:` guard skips constraint

The constrained union was deployed (v3.3.113) with a small bug. When `_production_pairs` is empty (BFS from target table finds nothing — happens on fresh workspaces), the `if` guard at line 868 skips the constraint entirely:

```python
# l1_builder.py:868-869 (buggy):
if _production_pairs:                                    # {} is falsy → SKIPPED
    lineage_field_pairs = lineage_field_pairs & _production_pairs
```

Empty `_production_pairs` means the BFS couldn't validate any pairs — not that validation should be skipped. The correct behavior: intersect with empty set → result is empty → only the target survives via `lineage_field_pairs.add((table, field))` at line 871.

**Fix:** Remove 2 lines, keep 1:

```python
# l1_builder.py:868-869 (fixed):
lineage_field_pairs = lineage_field_pairs & _production_pairs  # always intersect
```

Works for both cached workspaces (`_production_pairs` non-empty → correctly filters) and fresh workspaces (`_production_pairs` empty → only target shown).

**Files:** `backend/app/services/l1_builder.py:868-869`

---

## Bug 33: ALIAS Edges Cross in Step3 L2

> **Found:** v3.3.110 | **Priority:** P3 | **Status:** Open
> **Pattern 6:** Frontend-backend contract gap

**Symptom:** In step3 L2 graph, ALIAS edges `stg_orders → so` and `stg_customers → sc` visually cross through each other. The four compound nodes are positioned in a grid by the layout algorithm, and ALIAS edges between them travel in straight lines.

**Root cause:** `graphStyles.js:598-601` sets `curve-style: unbundled-bezier` but does NOT set `control-point-distances` or `control-point-weights`. Without explicit control points, Cytoscape uses default placement, which for closely-positioned compound nodes is too subtle to avoid visible crossing.

**Solution:** Add explicit control points to force visible separation:
```js
// graphStyles.js:598-601
{
  selector: 'edge[edge_type="ALIAS"]',
  style: {
    'curve-style': 'unbundled-bezier',
    'control-point-distances': [-30, 30],
    'control-point-weights': [0.3, 0.7],
  },
},
```
Then rebuild frontend: `cd frontend && npm run build && cp -r dist/* ../backend/app/static/`

**Files:** `frontend/src/utils/graphStyles.js:598-601`

---

## Bug 37: Two Duplicate BFS Implementations With Different Edge Sets

> **Found:** v3.3.114 | **Priority:** P2 | **Status:** ✅ Effectively fixed (v3.3.115) — update doc

**Original symptom:** Two independent BFS implementations existed — one in `lineage.py` and one in `l1_builder.py` — with different edge-type handling.

**Current state:** The constrained union in `l1_builder.py:842` and multi-hop in `l1_builder.py:936` both call `compute_field_lineage` with `edge_filter`. The unified engine is used. No separate BFS remains.

| Call site | Line | Engine |
|-----------|------|--------|
| Naive union | 731 | `compute_field_lineage(gdata, table, field)` — no filter |
| Constrained union | 842 | `compute_field_lineage(gdata, table, field, edge_filter=PRODUCTION_TYPES \| {"SCHEMA"})` |
| Multi-hop | 936 | `compute_field_lineage(gdata, tn, fn, edge_filter=PRODUCTION_TYPES \| {"SCHEMA"})` |

All three use the same unified engine. **This bug is fixed** — only the doc status needs updating.

**Files:** `backend/app/extractor/lineage.py`, `backend/app/services/l1_builder.py:842,936`

---

## Bug 26: Terminal Marker Should Not Have Outgoing Edges

> **Found:** v3.3.106 | **Priority:** P2 | **Status:** Closed — R18.1 updated (2026-07-30)

**Original issue:** Terminal marker had outgoing edge to step4 — implied data flows onward.

**Requirement change:** Scripts connected to the terminal marker are now **kept with edges**. The terminal marker shows where automatic lineage stops; connected scripts enable **manual L2 verification** — users open step4/step5 to visually confirm `customer_id` is absent from INSERT/SELECT. Better than hiding scripts.

**New expected edges:**
```
step3 --writes_to--> analytics_orders        ← kept (incoming)
analytics_orders --reads_from--> step4        ← KEPT (manual verification)
analytics_orders --reads_from--> step5        ← KEPT (manual verification)
step4 --writes_to--> daily_summary            ← removed (downstream table)
step5 --writes_to--> report                   ← removed (downstream table)
```

**Updated:** REQUIREMENTS.md R18.1, DATAFLOW_FORMAL_DEFINITION.md, SOLUTION_DESIGN.md

---

## Bug 27: L1 Uses Name Matching Instead of Lineage BFS

> **Found:** v3.3.106 | **Priority:** P1 | **Status:** ✅ Fixed (v3.3.110)

**Symptom:** Querying `stg_customers.customer_id` shows `raw_orders.customer_id` and `stg_orders.customer_id` in L1. These fields share the same **name** as the target but are NOT in the target's **lineage** — they feed into `stg_orders.customer_id`, which joins `stg_customers.customer_id` via equality in step3, but doesn't produce or transform into it.

**Example pipeline:**
```
crm_customers.customer_id → step2(INSERT) → stg_customers.customer_id → step3(JOIN ON sc.customer_id=so.customer_id)
raw_orders.customer_id    → step1(INSERT) → stg_orders.customer_id    → same JOIN
```

`stg_customers.customer_id`'s value comes from `crm_customers.customer_id` via step2's INSERT. `stg_orders.customer_id` has the same name and value (via JOIN equality) but is produced independently. The JOIN does NOT create a production relationship between them — it only tests equality. `compute_field_lineage` correctly excludes `stg_orders.customer_id` from `stg_customers.customer_id`'s lineage (JOIN is conditional, requires both ends already in R via production).

But `_filter_l1_by_lineage` at line 174 doesn't use `compute_field_lineage` — it uses name matching:
```python
if fname == keep_field_suffix and fg == "direct":
```
Any field named `customer_id` with `field_group == "direct"` passes, regardless of actual lineage connectivity. The `"direct"` classification in `_build_l1_graph` (l1_builder.py) is a simplified BFS over ALL edges (undirected), which over-includes fields connected via JOIN.

**What L1 should show for `stg_customers.customer_id`:**
| Field | Shown? | Reason |
|-------|--------|--------|
| `stg_customers.customer_id` (★target) | ✅ | Seed |
| `crm_customers.customer_id` | ✅ | DML ↑ via step2: `c.customer_id → stg_customers` |
| `stg_orders.customer_id` | ❌ | JOIN only, not in production chain |
| `raw_orders.customer_id` | ❌ | Produces `stg_orders.customer_id`, not `stg_customers.customer_id` |

### Partial fix applied (v3.3.107)

`_build_l1_graph` in `l1_builder.py:696-745` now runs `compute_field_lineage` per script and builds a `lineage_field_pairs` set. L1 fields are kept only if their `(table_name, field_name)` is in this set. Name matching is gone. ✅

### What's still broken — alias resolution

Lineage field pairs are extracted from analysis graph node labels. The labels use alias prefixes:

```
analysis graph: c.customer_id, sc.customer_id, so.customer_id, o.customer_id
lineage_pairs:  ("c", "customer_id"), ("sc", "customer_id"), ...
L1 tables:      crm_customers,         stg_customers,          ...
```

`("c", "customer_id")` doesn't match L1 field `table_name = "crm_customers"` → `crm_customers.customer_id` is dropped from L1. Only the target field (`is_target=True`) survives.

### Root cause (confirmed)

`build_graph_data` in `graph_service.py:121-136` creates graph nodes with these keys:
`id, label, variable_type, shape, color, size, sql_expression, defined_in, is_output, source_tables`

**Missing:** `table_name` and `field_name`. The information exists in `v["name"] = "c.customer_id"` but is never split.

Then `l1_builder.py:718-719` tries to read these missing keys:
```python
tn = nd.get("table_name", "")                              # → always ""
fn = nd.get("field_name", nd.get("label", "").lstrip("★"))  # → falls back to "c.customer_id"
```

The fallback populates `fn` with the full label → `not fn` is False → the dot-split at line 722 never runs → `tn` stays empty → pair silently dropped.

### Fix — Step 1: `graph_service.py` ~line 134

**File:** `backend/app/services/graph_service.py`
**Function:** `build_graph_data()`
**Change:** After line 134 (`"source_tables": v.get("source_tables", []),`), add:

```python
# Extract table_name and field_name from dotted column names like "c.customer_id"
label = v.get("name", "")
if "." in label and v.get("variable_type") in ("column", "cte_column"):
    parts = label.rsplit(".", 1)
    node_data["table_name"] = parts[0]    # "c"
    node_data["field_name"] = parts[1]    # "customer_id"
```

This must be added INSIDE the `nodes.append({"data": {...}})` call, before the closing `})`, so the keys go into `node_data`. Specifically after line 134, before line 135 `}`.

### Fix — Step 2: `l1_builder.py` lines 718-719 and 738-739

**File:** `backend/app/services/l1_builder.py`
**Function:** `_build_l1_graph()` — the `lineage_field_pairs` extraction block (~line 696-775)

**Change:** Simplify both extraction sites. The `table_name` and `field_name` keys now exist — read them directly:

```python
# Line 718-719 (Path 1 — graph cache), replace:
tn = nd.get("table_name", "")
fn = nd.get("field_name", nd.get("label", "").lstrip("★"))
# Also try to get field_name from label like "table.field"
label = nd.get("label", "")
if not fn and "." in label:
    parts = label.rsplit(".", 1)
    tn = tn or parts[0]
    fn = parts[1]

# WITH:
tn = nd.get("table_name", "")
fn = nd.get("field_name", "")
```

Same replacement at lines 738-744 (Path 2 — `analyze_multiple_scripts` graph).

**Why only 6 lines per site:** After Step 1, every column/cte_column node already has `table_name` and `field_name`. No label parsing needed. No fallbacks needed. No conditional logic.

### Verification

After both steps, run the debug command to confirm fix:
```bash
# Should print non-empty pairs for step2 and step3:
# step2: pairs={('c', 'customer_id')}
# step3: pairs={('sc', 'customer_id'), ('so', 'customer_id')}
```

Alias resolution at lines 765-772 then maps `c→crm_customers`, `sc→stg_customers`, `so→stg_orders` → `lineage_field_pairs` = `{("crm_customers","customer_id"), ("stg_customers","customer_id")}` → L1 shows both fields.

This produces `{("crm_customers", "customer_id"), ("stg_customers", "customer_id")}` — matching the L1 canonical table names.

**Note:** Aliases should NOT appear as separate L1 nodes. Aliases are script-local (`c` means nothing outside step2). L1 is cross-script — only canonical table names belong. This is different from Bug 28 (L2), where showing aliases IS appropriate because L2 is per-script.

**Files:** `backend/app/services/l1_builder.py:715-727`

---

## Bug 28: Alias and Output Table Field Synchronization (Table Type Invariants)

> **Found:** v3.3.106 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.110)

**Symptom:** In step2 L2 graph, querying `stg_customers.customer_id`:
```
c(1f: customer_id)  crm_customers(0f)  stg_customers(0f)  ⟐ output(0f)
```
Only the alias `c` has the field. The canonical table, DML target, and output table are all empty.

### Operation-Based Invariants

The edges recorded by the extractor exactly determine which fields each table carries. No blind inheritance needed.

**Alias Field Sync:** When `crm_customers --ALIAS--> c` exists, fields on `c` MUST also appear on `crm_customers`. The ALIAS edge triggers bidirectional field copy.

**Output Table Fields:** An output table's fields = {columns with SCHEMA edge FROM that output table}. In step2:
```
c.customer_id  ←──SCHEMA── ⟐ output
c.full_name    ←──SCHEMA── ⟐ output
c.segment      ←──SCHEMA── ⟐ output
c.region       ←──SCHEMA── ⟐ output
```
The SCHEMA edges from `⟐ output` list exactly what was SELECTed. The extractor already recorded this — we just need to read it during compound node building.

### Fix — Step 1: Alias field sync (l2_builder.py, after line 210)

**File:** `backend/app/services/l2_builder.py`
**Location:** After Phase 0 alias_map is built (~line 210), before node classification (~line 212)

After building `alias_map`, iterate it and sync field nodes. Graph nodes now have `table_name` and `field_name` from the Bug 27 fix — use them to identify fields belonging to each table.

```python
# After alias_map is built (after line 210), add:
# ── Alias field synchronization ──
# For each (canonical_name, alias_name) pair, copy field nodes both ways
# so both tables show identical field sets.
alias_field_map = {}  # table_label -> set of (table_name, field_name) pairs
for n in nodes:
    nd = n.get("data", n)
    if nd.get("variable_type") in ("column", "cte_column"):
        tn = nd.get("table_name", "")
        fn = nd.get("field_name", "")
        if tn and fn:
            alias_field_map.setdefault(tn, set()).add((tn, fn))

for alias_name, canonical_name in alias_map.items():
    if canonical_name in alias_field_map and alias_name in alias_field_map:
        # Sync both ways
        alias_field_map[canonical_name] |= alias_field_map[alias_name]
        alias_field_map[alias_name] |= alias_field_map[canonical_name]
```

Then during field node creation (~line 295-304), use `alias_field_map` to determine which fields a table carries, rather than relying solely on `source_tables` or name prefix. A table's fields = the union of its own fields + any synced fields from alias partners.

### Fix — Step 2: Output table fields from SCHEMA edges (l2_builder.py, ~line 350)

**File:** `backend/app/services/l2_builder.py`
**Location:** After field_nodes are populated (~line 350), before final assembly

For each `virtual_table` (like `⟐ output`), find all columns that have a **SCHEMA edge from this table**. Create field nodes under the output table.

```python
# After field_nodes population, add:
# ── Output table fields from SCHEMA edges ──
# An output table's fields = {columns with SCHEMA edge FROM this output table}
existing_vt_ids = {tn["original_id"] for tn in table_nodes.values()
                   if tn.get("variable_type") == "virtual_table"}
for e in edges:
    ed = e.get("data", e)
    if ed.get("edge_type") == "SCHEMA" and ed.get("source") in existing_vt_ids:
        # Find the column node
        for n in nodes:
            nd = n.get("data", n)
            if nd.get("id") == ed.get("target"):
                tn = nd.get("table_name", "")
                fn = nd.get("field_name", "")
                if tn and fn:
                    # Check if this field already exists under the output table
                    vt_id = table_nodes[ed["source"]]["id"] if ed["source"] in table_nodes else None
                    if vt_id:
                        already_exists = any(
                            f.get("parent") == vt_id and f.get("field_name") == fn
                            for f in field_nodes
                        )
                        if not already_exists:
                            field_nodes.append({
                                "id": f"fld_{hashlib.md5((vt_id + fn).encode()).hexdigest()[:10]}",
                                "label": fn,
                                "type": "field",
                                "variable_type": "field",
                                "field_group": "indirect",
                                "table_name": tn,
                                "field_name": fn,
                                "parent": vt_id,
                                "original_id": nd.get("id"),
                            })
```

This reads the SCHEMA edges the extractor already recorded — every SELECTed column has `⟐ output --SCHEMA--> column`. No blind inheritance, no guessing.

**Files:** `backend/app/services/l2_builder.py`

---

## Bug 29: DML Phantom Field Sync Broken by Field Promotion

> **Found:** v3.3.109 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.110)

**Symptom:** `stg_customers(0f)` in step2 L2. The DML phantom field sync (Bug 28 Sync 2) is supposed to show `customer_id` under the INSERT target table, but it silently does nothing.

### Root cause

The execution order in `l2_builder.py`:

**Phase 1 (line 482-518): Field promotion** — converts field-level edges to table level. A DML edge like:
```
field(c.customer_id) --DML--> table(stg_customers)
```
becomes:
```
table(c) --DML--> table(stg_customers)   ← source is now a TABLE ID
```

**Phase 2 (line 539-544): dml_pairs collection** — records `(c_table_id, stg_customers_table_id)` — table-level pairs.

**Phase 3 (line 635-648): DML phantom field sync** — tries to match `src_fid` against field node IDs:
```python
for (src_fid, tgt_tid) in dml_pairs:      # src_fid = c_table_id
    for fn in field_nodes:
        if fn["id"] == src_fid:            # c_table_id ≠ any field ID → NEVER MATCHES
```

The promotion changed `src_fid` from a field ID to a table ID. The sync code assumes field IDs. Match fails silently → no phantom fields created → `stg_customers` stays empty.

### Fix

**File:** `backend/app/services/l2_builder.py`, lines 635-648

After promotion, `dml_pairs` may contain table IDs (not field IDs). Handle both cases:

```python
# Sync 2: DML phantom fields (field -> DML target table)
# After field promotion, dml_pairs may have table IDs instead of field IDs.
# When src_fid is a table ID: sync ALL fields under that table.
for (src_fid, tgt_tid) in dml_pairs:
    # Find all field nodes whose parent is src_fid (table-level DML)
    src_fields = [fn for fn in field_nodes if fn.get("parent") == src_fid]
    if not src_fields:
        # src_fid might be a field ID (pre-promotion) — try direct match
        src_fields = [fn for fn in field_nodes if fn["id"] == src_fid]
    for fn in src_fields:
        exists = any(
            f.get("parent") == tgt_tid and f.get("label") == fn.get("label")
            for f in field_nodes
        )
        if not exists:
            proxy = dict(fn)
            proxy["id"] = f"dml_{fn['id']}_{tgt_tid[:8]}"
            proxy["parent"] = tgt_tid
            proxy["field_group"] = "direct"
            field_nodes.append(proxy)
```

**Files:** `backend/app/services/l2_builder.py:635-648`

---

## Bug 34: SUBQUERY Edge Type Silently Ignored in Lineage BFS

> **Found:** v3.3.114 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.115)

**Symptom:** `lineage.py` defines `_PRODUCTION` and `_ALWAYS_BIDIR` edge sets covering 15 edge types. SUBQUERY (the 16th type) is missing from both sets and has no conditional check. SUBQUERY edges are never traversed — they're silently dead.

**Root cause:** `lineage.py:76-79`:
```python
_PRODUCTION = {"REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED", "DML", "ALIAS"}
_ALWAYS_BIDIR = {"CORRELATED", "INDIRECT", "SET_OP", "SUBSET"}
```

SUBQUERY is not in either set, and the conditional block (lines 166-213) only handles JOIN and FILTER. SUBQUERY edges are silently ignored.

**Fix:** Add SUBQUERY to `_ALWAYS_BIDIR` (bidirectional, always follow — same as SET_OP and SUBSET):
```python
_ALWAYS_BIDIR = {"CORRELATED", "INDIRECT", "SET_OP", "SUBSET", "SUBQUERY"}
```

Update docstring at line 23 from "15 edge types" to "16 edge types".

**Files:** `backend/app/extractor/lineage.py:78`

---

## Bug 35: Seed Matching Doesn't Follow ALIAS Chains

> **Found:** v3.3.114 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.115)

**Symptom:** When the target table has an ALIAS (`stg_customers → sc`), its columns (`sc.customer_id`) are SCHEMA-connected to the alias (`sc`), not directly to the target. The SCHEMA validation at `lineage.py:111-119` only checks direct SCHEMA edges from the target table:

```python
if (etype == "SCHEMA" and ed.get("source") == table_node_id and ed.get("target") == nid):
    seed_ids.add(nid)
```

`table_node_id` = `stg_customers`. SCHEMA edge source = `sc` (alias), not `stg_customers`. → Validation fails → falls through to fallback label matching → adds ALL columns named `customer_id` as seeds.

**Fix:** Before the SCHEMA validation, build an ALIAS-transitive closure of the target table. Follow ALIAS edges from the target table to find all aliases, then accept SCHEMA edges from ANY of them:

```python
# Build transitive alias closure from target table
alias_sources = {table_node_id}
queue = [table_node_id]
while queue:
    nid = queue.pop(0)
    for e in edges:
        ed = e.get("data", e)
        if (ed.get("edge_type") == "ALIAS" and ed.get("source") == nid
            and ed.get("target") not in alias_sources):
            alias_sources.add(ed.get("target"))
            queue.append(ed.get("target"))

# Then validate: SCHEMA edge from any alias source
for e in edges:
    if (etype == "SCHEMA" and ed.get("source") in alias_sources and ed.get("target") == nid):
        seed_ids.add(nid)
        break
```

**Files:** `backend/app/extractor/lineage.py:111-119`

---

## Bug 36: `if _production_pairs:` Guard Can Skip Constraint

> **Found:** v3.3.114 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.115)

**Symptom:** The constrained union at `l1_builder.py:873` has a guard that skips the constraint when `_production_pairs` is empty. On workspaces where the BFS finds nothing, all 4 naive pairs survive unfiltered.

```python
# l1_builder.py:873-874
if _production_pairs:                                    # {} is falsy → SKIPPED
    lineage_field_pairs = lineage_field_pairs & _production_pairs
```

**Fix:** Remove the 2-line `if` guard — always intersect:
```python
lineage_field_pairs = lineage_field_pairs & _production_pairs
```

When `_production_pairs` is empty, the intersection correctly gives empty set, then `lineage_field_pairs.add((table, field))` at line 876 restores the target. Works for all workspace states.

**Files:** `backend/app/services/l1_builder.py:873-874`

## Bug 38: TABLE_FLOW — Formal Definition Says Follow, Code Says Skip

> **Found:** v3.3.114 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.115)

**Symptom:** The formal definition's Rules Summary explicitly lists TABLE_FLOW as bidirectional and NOT conditional:

```
| TABLE_FLOW | alias ← output | alias → output | No |
```

But `lineage.py:33` says:
```
TABLE_FLOW: not followed (redundant — DML/REF/SCHEMA↑ already reach source tables)
```

The code has TABLE_FLOW in **no** edge set (`_PRODUCTION`, `_ALWAYS_BIDIR`, or conditional check). It's silently skipped.

**Impact:** In most cases this is benign — DML and SCHEMA edges already connect the same tables. But for SELECT-only scripts without DML edges (pure SELECT → `⟐ output`), TABLE_FLOW is the ONLY way to reach the output. Skipping TABLE_FLOW can cause `compute_field_lineage` to miss the output table entirely when there's no DML path.

**Fix:** Add TABLE_FLOW to `_ALWAYS_BIDIR` (or create a separate `_STRUCTURAL` set):
```python
_ALWAYS_BIDIR = {"CORRELATED", "INDIRECT", "SET_OP", "SUBSET", "SUBQUERY", "TABLE_FLOW"}
```

Or, if TABLE_FLOW truly is always redundant: update the formal definition to say "not followed" instead of "bidirectional." Either the code or the spec must change — they can't disagree.

**Files:** `backend/app/extractor/lineage.py:78` or `wiki/DATAFLOW_FORMAL_DEFINITION.md` (Rules Summary)

---

## Bug 39 + Bug 47 (Pattern 1, P1): Dual Extraction Pipeline With Independent Fallback Strategies

> **Found:** v3.3.116 (Bug 39), v3.3.121 (Bug 47) | **Priority:** P1 | **Status:** Open

**Symptom:** Querying `stg_customers.customer_id` in lineage mode returns incomplete results. `crm_customers.customer_id` may be missing from L1 (upstream source). Downstream queries also fail. The results vary depending on which script is last in `all_scripts` iteration order — non-deterministic.

### Root Cause Architecture

`_build_l1_graph()` computes `lineage_field_pairs` through **three independent extraction passes** that all parse `(table_name, field_name)` from graph nodes, each with different fallback strategies:

| Pass | Lines | Edge set | Skip non-column? | Fallback when field_name="" | DML propagation |
|------|-------|----------|:---:|------|:---:|
| Naive union (cache) | 720-755 | All edges | ✅ (line 737) | `fn = label.lstrip("★")` | ❌ |
| Naive union (in-memory) | 757-781 | All edges | ✅ (line 765) | `fn = label.lstrip("★")` | ❌ |
| Constrained union | 822-858 | PRODUCTION+SCHEMA | ❌ (no skip) | `fn = label.lstrip("★")` | ✅ (scoped wrong) |

Then at line 911: `lineage_field_pairs = lineage_field_pairs & _production_pairs` — **intersection** of two independently-computed sets. If either produces garbage or misses a correct pair, the result is silently wrong.

The SOLUTION_DESIGN.md specifies that both should read **P4's `table_fields`** (pre-recorded per-table field sets) as single source of truth. **Neither currently does.** Instead, each pass walks graph nodes and applies its own heuristic fallback chain.

### Root Cause A (Bug 47): Constrained Union Has No Non-Column Skip

At line 855-856, the constrained union falls back to:
```python
if not fn:
    fn = label.lstrip("★")   # table node "stg_customers" → fn = "stg_customers" (WRONG!)
```

The naive union skips non-column nodes (line 737: `if nd.get("variable_type", "") not in ("column",): continue`), but the constrained union does NOT. This produces garbage pairs like `("stg_customers", "stg_customers")` in `_production_pairs`.

These garbage pairs are later filtered by `_is_valid_col_pair` (line 901: `if fn in _alias_names or fn in _table_names: return False`), but this filter is itself a heuristic — a real column genuinely named after a table would be incorrectly dropped.

### Root Cause B (Bug 47): DML Propagation Uses Wrong `gdata`

At lines 863-879, the DML propagation iterates `_col_pairs` and searches `gdata.get("nodes", [])`. But `gdata` here retains the value from the **last** iteration of the `for s in all_scripts` loop (line 822). If the last script has no DML edges to `stg_customers`, the propagation loop finds nothing:

```python
# Line 822: for s in all_scripts:   ← loop ENDS
#   gdata = ...                     ← last script's gdata persists

# Line 864-865: OUTSIDE the loop:
for (tn, fn) in _col_pairs:
    for n in gdata.get("nodes", []):   # ← searches only the LAST script!
```

**This means `("stg_customers", "customer_id")` may or may not be added to `_production_pairs` depending on script iteration order** — non-deterministic.

### Root Cause C (Bug 39): Both Passes Miss DML Targets

The naive union (with no DML propagation) never produces `("stg_customers", "customer_id")` — column nodes are on alias `c`, not on target `stg_customers`. The constrained union should add it via DML propagation (Root Cause B), but the scoping bug makes it unreliable.

### Solution: Replace Dual Extraction With Single P4-Based Pass

Instead of three independent per-node extraction loops, build `all_table_fields[canonical_table] → {field_names}` once from all scripts' graph data, then use it as single source of truth:

1. **Build `all_table_fields` once** — from SCHEMA edges (P4) and DML edges across all scripts:
   ```python
   all_table_fields = {}  # canonical_table → {field_names}
   for s in all_scripts:
       gdata = s.get("graph", {})
       for e in gdata.get("edges", []):
           ed = e.get("data", e)
           if ed.get("edge_type") == "SCHEMA":
               # source=table, target=column → add field to table
               ...
           elif ed.get("edge_type") == "DML":
               # source=column, target=table → add column's field to target table
               ...
   ```

2. **Single extraction pass** — for each script, run `compute_field_lineage` with the appropriate edge_filter, then collect pairs as `{(tn, fn) for tn, fns in all_table_fields.items() for fn in fns if node_id_of(tn, fn) in lineage_set}`.

3. **Drop `_is_valid_col_pair`** — it exists only because garbage pairs need cleaning. With P4 as source of truth, no garbage is created.

4. **Move DML propagation inside** the per-script loop so it uses the correct `gdata`.

This reduces lines ~700-960 (~260 lines) to about 80 lines with zero heuristic fallbacks.

**Files:** `backend/app/services/l1_builder.py:696-960`

---

## Bug 40: Multi-Hop Lineage Missing — Only 1-Hop Traced

> **Found:** v3.3.120 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.121)

**Symptom:** Each script correctly traces 1-hop. `analytics_orders.amount` finds `stg_orders.amount` (step3 DML). `stg_orders.amount` finds `raw_orders.amount` (step1 DML). But querying `analytics_orders.amount` only returns 1-hop — `raw_orders.amount` is missing.

Expected: `raw_orders.amount → stg_orders.amount → analytics_orders.amount` (3 fields). Actual: `stg_orders.amount → analytics_orders.amount` (2 fields).

**Root cause:** The constrained union runs `compute_field_lineage` per script, getting per-script 1-hop pairs. These are unioned but not chained. The output `(stg_orders, amount)` is never used as input to search step1.

**Fix — Iterate until stable:**

```python
# After constrained union produces lineage_field_pairs, iterate:
changed = True
while changed:
    changed = False
    for (tn, fn) in list(lineage_field_pairs):
        # Run constrained union for THIS pair as if it were the query
        sub_pairs = constrained_union_for(tn, fn)
        new_pairs = sub_pairs - lineage_field_pairs
        if new_pairs:
            lineage_field_pairs |= new_pairs
            changed = True
```

Round 1: `analytics_orders.amount` → `{stg_orders.amount, analytics_orders.amount}`
Round 2: `stg_orders.amount` → adds `raw_orders.amount`
Round 3: no new pairs → stop

**Files:** `backend/app/services/l1_builder.py`

---

## Bug 41: INSERT Column vs SELECT Alias Mismatch (Pattern 5, P3)

> **Found:** v3.3.120 | **Priority:** P3 | **Status:** Open
> **Pattern 5:** Indexer records only one side of DML name mapping

**Symptom:** Step4 SQL: `INSERT INTO daily_summary (total_amount) SELECT SUM(amount) AS total`. The field index records `total → {step4}`, not `total_amount → {step4}`. User searches `daily_summary.total_amount` → `match_mode: "fallback"` → broader, less accurate script set.

**Root cause:** The DML dependency records both names (`total --DML--> total_amount`) — source is the SELECT alias, target is the INSERT column. But the field indexer in `folder_index_service.py` indexes only variable names (SELECT side). The INSERT column name (`total_amount`) is never added to the field index.

**Solution:** In the indexer, iterate DML dependencies and index both sides:
```python
for dep in dependencies:
    if dep["relationship"] == "DML":
        # dep["source_id"] → SELECT alias node → look up its name → "total"
        # dep["target_id"] → INSERT column node → look up its name → "total_amount"
        # Index BOTH names → the same script
        tgt_name = lookup_variable_name(dep["target_id"])
        if tgt_name:
            field_index.setdefault(tgt_name, {"scripts": set()})["scripts"].add(script_name)
```

**Files:** `backend/app/services/folder_index_service.py` (field indexing loop)

---

## Bug 42: L2 Edge Click Shows No Highlighted SQL Lines (Pattern 6, P2)

> **Found:** v3.3.120 | **Priority:** P2 | **Status:** Open
> **Pattern 6:** Frontend-backend contract gap

**Symptom:** Clicking an edge in L2 graph does not scroll to or highlight the relevant SQL lines in the SQL panel.

**Root cause:** The data pipeline works — `find_sql_range()` populates `sql_range` on each L2 edge. `SqlPanel.jsx:56-59` correctly handles `sqlHighlightRange`:
```jsx
const [edgeStart, , edgeEnd] = sqlHighlightRange;
for (let i = edgeStart; i <= edgeEnd; i++) edgeHighlightSet.add(i);
```

The gap is in the **frontend edge-click handler**. When the user taps an edge in the Cytoscape graph, the handler must:
1. Read `edge.data().sql_range` from the clicked edge
2. Pass it as `sqlHighlightRange` prop to `SqlPanel`

This wiring was never implemented. The Cytoscape `tap` event handler (in `useCytoscapeGraph.js` or `DataFlowGraph.jsx`) does not dispatch the edge's `sql_range` to the SQL panel state.

Additionally, the CSS class `.sql-line.edge-highlighted` may lack visible styling (background color not defined in the stylesheet).

**Solution:**
1. In the edge `tap` event handler, read `edge.data().sql_range` and call a state setter
2. Ensure `.sql-line.edge-highlighted` has a visible CSS background (e.g., `background: rgba(255, 165, 0, 0.3)`)

**Files:** `frontend/src/components/DataFlowGraph.jsx` (or `useCytoscapeGraph.js`), `frontend/src/components/SqlPanel.jsx`

---

## Bug 43: `sql_range` Column Always 1 (Pattern 4, P3)

> **Found:** v3.3.120 | **Priority:** P3 | **Status:** Open
> **Pattern 4:** Column position never extracted from AST

**Symptom:** Every edge's `sql_range` has `start_col=1` and `end_col=<full line length>`. Line numbers may also be off by 1 for certain edge types.

**Root cause:** The entire `SqlRangeFinder` pipeline (StatementParser → StatementMatcher → KeywordLocator → RangeBuilder) operates at **line granularity only**. The `KeywordLocator` finds which *line* contains a keyword but never extracts the *column* within that line.

`RangeBuilder.build()` at `sql_range_finder.py:492-496` hardcodes:
```python
return SqlRange(
    start_line=start_line + 1,
    start_col=1,                                # ← always 1
    end_line=end_line + 1,
    end_col=len(self.all_lines[end_line])       # ← always full line
)
```

The sqlglot AST already carries character positions — `sqlglot.parse()` produces nodes where `node.start` and `node.end` are character offsets into the original SQL string. But `StatementParser._parse()` never records them.

**Solution:**
1. In `StatementParser._parse()`, walk the parsed AST to find the node matching the edge's source/target variable. Record its `node.start` offset.
2. Convert character offset to `(line, column)` by counting newlines in `sql_text[:offset]`.
3. Pass `(start_line, start_col, end_line, end_col)` through the pipeline to `RangeBuilder.build()` instead of defaulting to column 1.

**Files:** `backend/app/services/sql_range_finder.py:71-135` (parse), `:492-496` (RangeBuilder.build)

---

## Bug 44: Step3 L2 `so`/`stg_orders` Missing `customer_id` Field

> **Found:** v3.3.121 | **Priority:** P2 | **Status:** Open — needs verification

**Symptom:** In step3 L2, querying `stg_customers.customer_id` does not show `customer_id` under `so` or `stg_orders`.

**Root cause analysis:** In step3, `so` is an alias for `stg_orders`. `sc` is an alias for `stg_customers`. The JOIN condition `ON so.customer_id = sc.customer_id` connects them. When querying `stg_customers.customer_id`:

- `sc.customer_id` has SCHEMA from `sc` (alias of `stg_customers`)
- Bug 35's ALIAS-transitive closure finds: `stg_customers → sc` (ALIAS from stg_customers to sc)
- SCHEMA validation: `sc --SCHEMA--> sc.customer_id` → seed found ✅
- BFS from `sc.customer_id`:
  - JOIN to `so.customer_id` → **conditional** — requires both ends in R via production
  - `sc.customer_id` has NO production path to `so.customer_id` (they share a JOIN, not DML/REF/TRANSFORM)
  - → `so.customer_id` NOT added to R

**This is correct behavior** — `so.customer_id`'s value in step3 comes from `stg_orders` (the INSERT target of step1), not from any production operation within step3. The JOIN tests equality but does not produce either field's value in step3.

**If the bug is confirmed** (field missing even when it should be present), the fix would involve adding a pass in `l2_builder.py` that re-adds fields reachable via JOIN when the JOIN connects to the target table.

**Verification needed:** Query `stg_orders.customer_id` in step3 L2 instead of `stg_customers.customer_id`. If `so.customer_id` appears, the behavior is correct — Bug 44 may be a usage expectation issue, not a code bug.

**Files:** `backend/app/services/l2_builder.py`, `backend/app/extractor/lineage.py`

---

## Bug 45: Step3 L2 Missing `so→⟐ output` JOIN Edge (Pattern 2, P2)

> **Found:** v3.3.121 | **Priority:** P2 | **Status:** Open
> **Pattern 2:** Field promotion before edge survival check

**Symptom:** In step3 L2, clicking `stg_customers.customer_id` should show `so --JOIN--> ⟐ output` (the JOIN between `so.customer_id` and `sc.customer_id` flows into the query output). The JOIN edge exists in the full graph but is not rendered.

**Root cause:** The L2 builder runs steps in this order:

1. `filter_relevant()` at `l2_builder.py:114` — computes lineage, removes nodes/edges not in R
2. Compound node building (lines 118-354) — maps original IDs to compound IDs
3. Edge list building (lines 367-456) — builds edges with new IDs
4. **Field promotion** (lines 497-518) — promotes field-level edges to table level
5. DML simplification (lines 520-579)

The JOIN edge `so.customer_id --JOIN--> ⟐ output` has field-level endpoints. `filter_relevant()` at step 1 runs `compute_field_lineage`, which treats JOIN as **conditional** — both ends need a production path into R. Since neither `so.customer_id` nor `⟐ output` is in the production lineage of `stg_customers.customer_id`, the JOIN edge is removed from `graph_data`. Step 3 (edge building) never sees it. Step 4 (promotion) can't promote what was already filtered out.

But the JOIN edge is **semantically valuable** — it shows the relationship between tables even though it doesn't carry production values.

**Solution:** After field promotion (step 4), run a **second pass** over the full graph's JOIN edges. For any JOIN edge where both endpoints resolve to table nodes in the current L2 graph, add a table-level JOIN edge regardless of whether `filter_relevant` included it. This is semantically correct — JOIN edges represent relationships between tables, not value flow.

```python
# After line 518 (after field promotion), add:
full_graph_edges = full_graph.get("edges", [])
for fe in full_graph_edges:
    fed = fe.get("data", fe)
    if fed.get("edge_type") == "JOIN" or fed.get("relationship") == "JOIN":
        src_new = id_map.get(fed.get("source"))
        tgt_new = id_map.get(fed.get("target"))
        if src_new and tgt_new and src_new != tgt_new:
            # Both endpoints resolved → add table-level JOIN edge
            promoted.append({...})
```

**Files:** `backend/app/services/l2_builder.py:497-518`

---

## Bug 46: Step3 L2 TABLE_FLOW Bypasses `⟐ output` (Pattern 2, P3)

> **Found:** v3.3.121 | **Priority:** P3 | **Status:** Open
> **Pattern 2:** Incomplete suppression check in DML simplification

**Symptom:** In step3 L2, a TABLE_FLOW edge goes `so → analytics_orders` directly instead of `so → ⟐ output → analytics_orders`.

**Root cause:** The DML simplification at `l2_builder.py:546-579` handles three cases:

1. **Line 552-555:** Suppress TABLE_FLOW if `src in dml_sources AND tgt in dml_targets AND neither is intermediate_id`
2. **Line 557-563:** Redirect non-DML, non-TABLE_FLOW edges to `intermediate_id`
3. **Line 566-576:** Replace DML edges with `intermediate_id → target (TABLE_FLOW)`

The suppression check at line 552 requires BOTH `src in dml_sources` AND `tgt in dml_targets`. If a TABLE_FLOW edge goes from a non-DML source to a DML target (e.g., `some_table --TABLE_FLOW--> analytics_orders` where `some_table` is not in `dml_sources`), it survives unsuppressed and bypasses `⟐ output`.

**Solution:** After the DML simplification, add a pass that ensures **all** edges into DML targets go through `intermediate_id`. Any surviving edge `X → dml_target` where edge_type is TABLE_FLOW and `X != intermediate_id` should be either:
- Suppressed (the `X → ⟐ → target` chain replaces it), or
- Redirected to `intermediate_id`

```python
# After line 579, add:
for e in new_dml_edges:
    src = e.get("source", "")
    tgt = e.get("target", "")
    etype = e.get("edge_type", "")
    if tgt in dml_targets and src != intermediate_id and etype == "TABLE_FLOW":
        e["source"] = intermediate_id  # redirect through ⟐ output
```

**Files:** `backend/app/services/l2_builder.py:546-579`

---

## Bug 48: L1/L2 Rebuild `alias_map` From Scratch (Pattern 3, P3)

> **Found:** v3.3.121 | **Priority:** P3 | **Status:** Open
> **Pattern 3:** Name resolution rebuilt in consumers

**Symptom:** P5 pre-builds `alias_map` in `graph_service.py:121-125`, but downstream consumers independently reconstruct it:
- `l1_builder.py:784-796` — rebuilds `global_alias_map` by scanning analysis cache files
- `l2_builder.py:187-210` — rebuilds `alias_map` by scanning nodes + edges, including a length heuristic (`len(label) <= 3`)

**Root cause:** The extractor writes `alias_map` into the per-script analysis output, but the graph cache format (`graph_3_2_15_{hash}.json`) does not include it as a top-level key. Each consumer independently reconstructs it because the data isn't in the format they read.

**Solution:** Store `alias_map` as a top-level key `"alias_map"` in the graph cache JSON (written at `graph_service.py` / `dataflow_service.py`). Both L1 and L2 read it from there:
```python
# Read:
alias_map = graph_cache.get("alias_map", {})

# Remove reconstruction code at:
#   l1_builder.py:784-796
#   l2_builder.py:187-210
```

The graph nodes already have `table_name`/`field_name` pre-resolved (P2) and `source_tables` populated. L2 can use `source_tables` directly for alias detection instead of the length heuristic.

**Files:** `backend/app/services/graph_service.py:121-125` (write), `l1_builder.py:784-796` (remove), `l2_builder.py:187-210` (remove)
