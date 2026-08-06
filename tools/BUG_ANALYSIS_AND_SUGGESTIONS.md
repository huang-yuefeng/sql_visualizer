# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-31 | **Version:** 3.3.129 | **Active:** 12 bugs (1 legacy + 1 new functional + 10 code review findings)
>
> **Tested against:** `stg_customers.customer_id` + `analytics_orders.amount` on workspace `0d4ae2cefe6a`
>
> **Root cause patterns**:
> 1. ~~Dual extraction with diverging fallbacks~~ — ✅ FIXED (Bug 39, 47)
> 2. ~~`filter_relevant()` removes semantically-important edges — downstream consumers read from filtered data instead of full graph~~ — ✅ FIXED (Bug 45, 46, verified v3.3.127)
> 3. ~~Column position never extracted from AST~~ — ✅ FIXED (Bug 43, v3.3.129)
> 4. ~~Name resolution rebuilt in consumers because `alias_map` not in graph cache~~ — ✅ FIXED (Bug 48, verified v3.3.127)
> 5. ~~Indexer records only one side of DML name mapping~~ — ✅ FIXED (Bug 41)
> 6. ~~Frontend-backend contract gap~~ — ✅ FIXED (Bug 33, 42)

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
| Bug 33: ALIAS edges cross in step3 L2 | P3 | ✅ Fixed (v3.3.126) | control-point-distances added; frontend rebuilt |
| Bug 39: P6 removed fallback — seed matching fails for alias columns | P1 | ✅ Fixed (v3.3.126) | DML seed search + alias sync working; step2 L2 full chain verified |
| Bug 40: Multi-hop lineage missing — only 1-hop traced | P2 | ✅ Fixed (v3.3.121) | Verified: 3 hops raw_orders→stg_orders→analytics_orders |
| Bug 41: INSERT column vs SELECT alias mismatch | P3 | ✅ Fixed (v3.3.126) | folder_index_service.py:114-147 cross-references DML deps; indexes both names |
| Bug 42: L2 edge click shows no highlighted SQL lines | P2 | ✅ Fixed (v3.3.126) | Full wiring: DataFlowGraph→DataFlowApp→SqlPanel verified |
| Bug 43: sql_range column always 1 | P3 | ✅ Fixed (v3.3.129) | KeywordLocator now returns (line, col) tuple; RangeBuilder uses matched_col |
| Bug 44: Step3 L2 so/stg_orders missing customer_id field | P2 | ✅ Not a bug — closed | JOIN is conditional; so.customer_id correctly excluded from stg_customers lineage |
| Bug 45: Step3 L2 missing so→⟐ output JOIN edge | P2 | ✅ Fixed (v3.3.127) | 2/2 JOIN edges present; so→⟐ output via survival pass |
| Bug 46: Step3 L2 TABLE_FLOW bypasses ⟐ output | P3 | ✅ Fixed (v3.3.127) | 0 bypasses; all flow through ⟐ output |
| Bug 47: Naive+constrained unions diverge on table field pairs | P1 | ✅ Fixed (v3.3.126) | Verified: 2 exact pairs, no over-inclusion, no missing pairs |
| Bug 48: L1/L2 rebuild alias_map from scratch | P3 | ✅ Fixed (v3.3.127) | alias_map in graph cache; both consumers read it |
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

> **Found:** v3.3.110 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.126)
> **Fix:** Added `control-point-distances: [-30, 30]` + `control-point-weights: [0.3, 0.7]` to ALIAS edge style; frontend rebuilt and deployed.

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

## Bug 39 + Bug 47 (Pattern 1, P1): Dual Extraction Pipeline — ✅ Fixed & Verified

> **Found:** v3.3.116 (Bug 39), v3.3.121 (Bug 47) | **Priority:** P1 | **Status:** ✅ Fixed (v3.3.126)

**Verified 2026-07-31:**

| Test | Expected | Actual | Result |
|------|----------|--------|:--:|
| L1 lineage_field_pairs | `crm_customers.customer_id`, `stg_customers.customer_id` | 2 pairs, both correct | ✅ |
| Excluded raw_orders.customer_id | Not in lineage | Not in lineage | ✅ |
| Excluded stg_orders.customer_id | Not in lineage | Not in lineage | ✅ |
| Non-lineage mode | 35 fields (all tables) | 35 fields | ✅ |
| Multi-hop (analytics_orders.amount) | 3 hops | 3 hops | ✅ |
| Step2 L2 DML chain | `crm_customers→c→⟐ output→stg_customers` all with `customer_id` | All 4 tables have 1 field | ✅ |

The DML-based seed search (Bug 39) + alias sync + constrained union intersection all work correctly. No over-inclusion, no missing pairs, no garbage pairs.

**Root cause (historical):** The issue was three-fold: (A) constrained union had no non-column skip, (B) DML propagation used wrong `gdata` (last script only), (C) both passes independently extracted pairs with different fallback strategies. All three have been addressed in the current code.

**Files:** `backend/app/services/l1_builder.py:696-960`, `backend/app/extractor/lineage.py:138-155`

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

> **Found:** v3.3.120 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.126)

**Verified:** `folder_index_service.py:114-147` already cross-references DML dependencies and indexes BOTH the SELECT alias name (`total`) AND the INSERT column name (`total_amount`). The code comment at line 114 explicitly says "Bug 41: Cross-reference DML dependencies". Both names are indexed under the target table.

**Files:** `backend/app/services/folder_index_service.py:114-147`

---

## Bug 42: L2 Edge Click Shows No Highlighted SQL Lines (Pattern 6, P2)

> **Found:** v3.3.120 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.126)

**Verified — full wiring chain intact:**

1. `DataFlowGraph.jsx:23-33` — edge `tap` reads `data.sql_range` + `data.sql_ranges` → calls `onEdgeClick`
2. `DataFlowApp.jsx:336-342` — `handleEdgeClick` → `pickBestSqlRange(edgeData)` → `setSqlHighlightRange(best)`
3. `DataFlowApp.jsx:574-575` — passes `sqlHighlightRange` to `<SqlPanel>`
4. `SqlPanel.jsx:56-66` — applies `edgeHighlightSet` + auto-scrolls to highlighted line

`pickBestSqlRange()` (line 313-334) prefers per-type `sql_ranges` dict (most specific), falls back to `sql_range` array, then `line_num`.

**Files:** `DataFlowGraph.jsx:23-33`, `DataFlowApp.jsx:313-342`, `SqlPanel.jsx:56-66`

---

## Bug 43: `sql_range` Column Always 1 (Pattern 4, P3)

> **Found:** v3.3.120 | **Priority:** P3 | **Status:** Open — suggestion below (do not fix directly; hand to implementer)

**Historical confirmed test data from step3 L2:**
```
  ALIAS      stg_orders → so           range=[5, 1, 5, 30]    ← col always 1
  ALIAS      stg_customers → sc        range=[5, 1, 5, 30]    ← col always 1
  JOIN       sc → ⟐ output             range=[5, 1, 6, 30]    ← col always 1
```
Every edge has `start_col=1` and `end_col=<full line length>` (30 chars). No edge has the correct column position within its line.

**Root cause — three independent gaps in the pipeline:**

**Gap A** — `KeywordLocator._try_keyword_patterns()` at `sql_range_finder.py:276-308`:
```python
if _re.search(pat, line, _re.IGNORECASE):
    return global_idx   # ← returns LINE index only
```
`re.search()` returns a match object. `match.start()` gives the 0-based character offset within the line — the column position is **available but never captured**. The function signature returns `int` (line) instead of `(int, int)` (line, column).

**Gap B** — `KeywordLocator.find_best_line()` at line 252-274 returns `int` (line only). Both `_try_keyword_patterns()` and `_try_label_search()` return line indices without column info.

**Gap C** — `RangeBuilder.build()` at line 492-496 hardcodes:
```python
return SqlRange(
    start_col=1,                                # never set to anything else
    end_col=len(self.all_lines[end_line])       # always full line width
)
```

The `SqlRange` data class at line 25-31 supports `start_col`/`end_col`, but no code path ever populates them with real values.

**Additionally**, `StatementParser._parse()` at line 71-135 parses SQL via sqlglot but never records AST node character offsets (`node.start`, `node.end`), which would give column-level precision.

**Code review of implemented solution (v3.3.129, 2026-07-31):**

The implementer's version now includes all six changes — including the previously-missing keyword capture (change #1 was applied after the v3.3.128 review). Verified empirically:

| Path | Implementer's version (v3.3.129) | Previous suggestion |
|------|----------------------------------|---------------------|
| Keyword edges (JOIN/FILTER/ALIAS/DML/TABLE_FLOW/...) | ✅ `m.start()+1` captured — indented JOIN → col 3 | ✅ same |
| Label edges (REF, etc.) | ⚠️ col = first non-whitespace of line (approximate) | ✅ exact `line.find(term)+1` |
| End column | ✅ **better** — end of first word at matched col (`JOIN` → cols 3-6) | ⚠️ full line width |
| Robustness | ✅ `isinstance(result, tuple)` guard in find() | — |

**Verdict: the implemented solution is now equal or better than the previous suggestion.** The keyword path (majority of edge types) behaves identically; the end-column narrowing is a genuine improvement for visual highlighting; the isinstance guard adds robustness. The only remaining approximation is the label-search column (first non-whitespace instead of exact term position) — a minor edge case affecting only REF/TRANSFORM edges without keyword patterns; acceptable as-is.

**Suggested fix (6 small changes in `sql_range_finder.py`):**

1. `_try_keyword_patterns()` (~line 276): return `(global_idx, m.start() + 1)` instead of `global_idx` — capture the regex match's 1-based column:
   ```python
   m = _re.search(pat, line, _re.IGNORECASE)
   if m:
       return global_idx, m.start() + 1   # 1-based column
   ```
2. `_try_label_search()` (~line 310): track `match_col` from the first matching term's `line_lower.find(term) + 1`; return `(best_line, best_col)`.
3. `find_best_line()` (~line 252): change return type to `tuple`, return `(line, col)` from all strategies (Strategy C and fallback return `(i, 1)`).
4. `RangeBuilder.__init__()` (~line 384): add `matched_col: int = 1` param, store as `self.matched_col`.
5. `RangeBuilder.build()` (~line 492): replace hardcoded `start_col=1` with `start_col=self.matched_col`:
   ```python
   return SqlRange(
       start_line=start_line + 1,
       start_col=self.matched_col,          # ← real keyword column
       end_line=end_line + 1,
       end_col=len(self.all_lines[end_line])
   )
   ```
6. `SqlRangeFinder.find()` (~line 536): unpack the tuple and pass through:
   ```python
   best_line, best_col = locator.find_best_line()
   builder = RangeBuilder(statement, best_line, self.lines, edge_data, matched_col=best_col)
   ```

Note: the working tree currently has a partial whitespace-based heuristic in `build()` (computes first non-whitespace column) — replace it with the keyword-column approach; the whitespace heuristic is only correct when the keyword starts the line.

Verification: indented SQL (e.g. `  JOIN ...` at col 3) should report `start_col=3`; unindented SQL keeps `start_col=1` correctly.

**Files:** `backend/app/services/sql_range_finder.py` — `_try_keyword_patterns` (~line 276), `_try_label_search` (~line 310), `find_best_line` (~line 252), `RangeBuilder.__init__`/`build` (~line 384/396), `SqlRangeFinder.find` (~line 536)

---

## Bug 44: Step3 L2 `so`/`stg_orders` Missing `customer_id` Field

> **Found:** v3.3.121 | **Priority:** P2 | **Status:** ✅ Closed — correct behavior (2026-07-31 verified)

**Verified result:** Querying `stg_customers.customer_id` in step3 L2 correctly shows `customer_id` only on `sc` (alias of stg_customers) and `stg_customers` (canonical), but NOT on `so`/`stg_orders`. This is correct — `so.customer_id` is connected via JOIN (conditional edge), which does NOT propagate field values across scripts. `so.customer_id`'s value comes from step1's INSERT into `stg_orders`, not from any production operation within step3.

The alias sync correctly copies `customer_id` between `sc` and `stg_customers` (both have 1 field).

**Files:** `backend/app/services/l2_builder.py`, `backend/app/extractor/lineage.py`

---

## Bug 45: Step3 L2 Missing `so→⟐ output` JOIN Edge (Pattern 2, P2)

> **Found:** v3.3.121 | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.127) — verified

**Verified result (v3.3.127):** L2 step3 now shows both JOIN edges:
```
  JOIN  sc → ⟐ output    range=[5, 1, 6, 30]
  JOIN  so → ⟐ output    range=None          ← restored via survival pass
```

**Historical root cause:** The full graph has 2 JOIN edges. `filter_relevant()` removes 1 of 2 (the `so.customer_id→⟐ output` edge). After filtering: DML=0/6, JOIN=1/2 remain.

**Root cause:** A JOIN survival pass was added at `l2_builder.py:520-568` to re-add JOIN edges from the full graph after promotion. But it resolves field-level endpoints via `id_map.get(src_orig)`:

```python
# l2_builder.py:544-546
src_orig = fed.get("source", "")    # so.customer_id's original node ID
src_new = id_map.get(src_orig)      # → None! (field was filtered out)
if not src_new or not tgt_new:      # → skipped
    continue
```

`id_map` is built at line 359 from `field_nodes` — which only contains fields that survived `filter_relevant()`. Since `so.customer_id` is not in the lineage of `stg_customers.customer_id` (JOIN is conditional), it was filtered out, never added to `field_nodes`, and never entered `id_map`.

**The JOIN survival pass has the right intent but reads from the wrong data source.**

**Suggested fix — resolve via full-graph node data when `id_map` misses:**

```python
# l2_builder.py ~line 536, in the JOIN survival pass loop:
full_nodes = full_graph.get("nodes", [])
full_node_by_id = {}
for fn in full_nodes:
    fnd = fn.get("data", fn)
    full_node_by_id[fnd.get("id", "")] = fnd

for fe in full_edges:
    ...
    src_orig = fed.get("source", "")
    tgt_orig = fed.get("target", "")
    src_new = id_map.get(src_orig)
    tgt_new = id_map.get(tgt_orig)
    
    # FIX: when field-level endpoint was filtered out, resolve to parent table
    if not src_new and src_orig in full_node_by_id:
        src_node = full_node_by_id[src_orig]
        src_parent_label = (
            src_node.get("source_tables", [None])[0] or
            src_node.get("label", "").rsplit(".", 1)[0] if "." in src_node.get("label", "") else ""
        )
        # Find the table compound node matching this parent label
        for tn in table_nodes.values():
            if tn.get("table_name") == src_parent_label:
                src_new = tn["id"]
                break
    
    if not src_new or not tgt_new or src_new == tgt_new:
        continue
    ...

**Same fix also needed at line 546 for `tgt_new`** (when the JOIN target is a filtered field).

**Files:** `backend/app/services/l2_builder.py:520-568`

---

## Bug 46: Step3 L2 TABLE_FLOW Bypasses `⟐ output` (Pattern 2, P3)

> **Found:** v3.3.121 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.127) — verified

**Verified result (v3.3.127):** 0 TABLE_FLOW bypasses. Edges now route:
```
  TABLE_FLOW  so → ⟐ output
  TABLE_FLOW  sc → ⟐ output
  TABLE_FLOW  ⟐ output → analytics_orders   ← replaces the two bypass edges
```
> **Pattern 2:** Incomplete suppression check in DML simplification

**Confirmed test data:**
```
  TABLE_FLOW   so → analytics_orders    ⚠️ bypasses ⟐ output
  TABLE_FLOW   sc → analytics_orders    ⚠️ bypasses ⟐ output
```
Both TABLE_FLOW edges go directly from aliases to `analytics_orders` instead of routing through `⟐ output`. The correct routing should be: `so → ⟐ output → analytics_orders`.

**Root cause — verified via debug logging (`dml_targets_count=0`):**

A redirect pass was added at `l2_builder.py:631-640` to fix TABLE_FLOW bypasses:
```python
if intermediate_id:
    for e in new_edges:
        if tgt in dml_targets and src != intermediate_id and etype == "TABLE_FLOW":
            e["source"] = intermediate_id   # redirect through ⟐ output
```

But `dml_targets` is populated at line 591-594 from `new_edges` (the **filtered** edge list). `filter_relevant()` removed **all 6 DML edges** because their source columns are INSERT targets not in the lineage of `stg_customers.customer_id`. `dml_targets` is empty → the check `tgt in dml_targets` never matches → the bypass survives.

**The redirect code is correct. `dml_targets` reads from the wrong data source.**

**Suggested fix — populate `dml_targets` from `full_graph` instead of from `new_edges`:**

```python
# l2_builder.py ~line 586 — read DML targets from FULL graph:
dml_targets = set()
dml_sources = set()
dml_pairs = set()

# Use full_graph edges (not filtered new_edges)
for fe in full_graph.get("edges", []):
    fed = fe.get("data", fe)
    rel = fed.get("edge_type", "") or fed.get("relationship", "")
    if "DML" in rel.upper():
        tgt_new = id_map.get(fed.get("target", ""))
        src_new = id_map.get(fed.get("source", ""))
        if tgt_new:
            dml_targets.add(tgt_new)
        if src_new:
            dml_sources.add(src_new)
        if src_new and tgt_new:
            dml_pairs.add((src_new, tgt_new))
```

This ensures `analytics_orders` is in `dml_targets` even though DML edges were filtered out, so the redirect at line 631 fires correctly.

**Files:** `backend/app/services/l2_builder.py:586-594` (populate from full_graph), `:631-640` (redirect OK as-is)

---

## Bug 48: L1/L2 Rebuild `alias_map` From Scratch (Pattern 3, P3)

> **Found:** v3.3.121 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.127) — verified

**Verified result (v3.3.127):** Graph cache now includes `alias_map` as top-level key:
```
Top-level keys: ['alias_map', 'cte_count', 'edges', 'line_map', 'nodes', ...]
```

Consumers now read it:
- `l2_builder.py:188` — `alias_map = full_graph.get("alias_map", {})` (fallback scan kept for old cache data)
- `l1_builder.py:707-714` — merges `gdata.get("alias_map", {})` from graph caches (fallback to analysis caches only if no graph cache has it)

**Historical root cause:** `build_graph_data()` in `graph_service.py:121-125` builds `alias_map` during extraction and uses it to resolve `table_name`/`field_name` on graph nodes (P2). But the graph cache format (`graph_3_2_15_{hash}.json`) did NOT store `alias_map` as a top-level key. Consumers reconstructed it from scratch.

**Files:** `backend/app/services/graph_service.py:121-125`, `folder_index_service.py:88` (write), `l1_builder.py:707-714` (read), `l2_builder.py:186-198` (read)

---

# Lessons Learned & Architecture Review (2026-07-31)

> After fixing 11 bugs (Bug 33, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48) in one session, every bug traced back to one of **6 recurring architectural patterns**. The code is functionally correct, but the patterns that produced the bugs remain as structural debt. These are suggestions for the next refactor round.

## Weakness 1: Same Concept, Multiple Definitions (Divergence Risk)

**Evidence (verified in code):**

| Concept | Defined in | Duplicated in |
|---------|-----------|---------------|
| `EDGE_TYPE_STYLE` (16 edge types → colors/styles) | `graph_service.py:62` | `dataflow_service.py:391` |
| Production edge set | `lineage.py:77` (`_PRODUCTION`) | `l1_builder.py:701` (`PRODUCTION_TYPES`) |
| SQL range finding | `sql_range_finder.py` (708 lines, layered) | `l2_builder.py:815-1096` (`_estimate_sql_range`, **282 lines, never called — dead code**) |
| Alias map | `graph_service.py:121` | was in 2 consumers (Bug 48 — fixed, but fallback scans remain) |

**Why this caused bugs:** Bug 37 (two BFS with different edge sets) and Bug 47 (three extraction passes with different fallbacks) both existed because the "same" semantic was re-implemented per consumer. Each copy drifted.

**Solutions:**
1. **Delete `_estimate_sql_range`** (~282 lines in `l2_builder.py:815-1096`) — `find_sql_range` is the only implementation; nothing calls the old one. Highest-value cleanup.
2. Delete `EDGE_TYPE_STYLE` from `dataflow_service.py:391` (or import from `graph_service`).
3. Export `_PRODUCTION` as module-level `PRODUCTION_EDGES` from `lineage.py`; `l1_builder.py:701` imports it instead of redefining.

## Weakness 2: Information Computed but Not Carried (Data Loss at Boundaries)

**Evidence — this single pattern caused 4 bugs:**
- **Bug 43** — `match.start()` (column) computed but discarded at every pipeline layer
- **Bug 48** — `alias_map` built in extractor but not stored in cache format
- **Bug 41** — DML target name (`total_amount`) known to extractor but not indexed
- **Bug 45** — JOIN edges in full graph silently lost after `filter_relevant()`

**Why:** Each layer's output format was designed for the next layer's *minimum* needs, not the *full* information. Fixes so far were "add the missing field to the format" — correct, but the pattern will recur.

**Solution — contract-first cache format:** Define the graph cache schema explicitly with `format_version`:
```
graph_3_2_16_{hash}.json:
  format_version: 3
  alias_map, table_fields, line_map, input_tables, output_tables
  nodes[].{table_name, field_name, source_tables, pos}
  edges[].{source_label, target_label, sql_range, ...}
```
Every consumer reads from this one contract. New extraction information is *added to the format*, never reconstructed downstream. Bump the filename version when the schema changes (old caches invalidate cleanly instead of silently falling back).

## Weakness 3: Silent Fallbacks Everywhere

**Evidence (verified):**
- `l2_builder.py:190` — alias_map fallback scan "for backwards compatibility"
- `l2_builder.py:297-327` — three "fallback: attach to first table node" paths
- `l2_builder.py:413` — sql_range fallback
- `lineage.py filter_relevant()` — name-based fallback when lineage is empty
- `label.lstrip("★")` heuristics (now removed from l1_builder ✅)

**Why dangerous:** A fallback converts "data missing" into "wrong answer that looks plausible." Bug 27/30/47 all produced *plausible-but-wrong* graphs (garbage pairs filtered by more heuristics).

**Solution — explicit degradation:**
```python
# Instead of: fallback → first table node
if not parent_table_id:
    field_node["parent"] = None  # explicit: unparented
    log.warning("field %s has no parent table in script %s", label, script_name)
```
A test then asserts "no field is unparented in the multi_workflow fixture" — wrong data becomes loud, not silent.

## Weakness 4: "Value Flow" vs "Relationship Display" Mixed in One Rule

**Evidence:** JOIN is "conditional" (doesn't propagate values — Bug 30, Bug 44 correct) but JOIN edges are also "display-worthy" (Bug 45 — the survival pass re-adds what `filter_relevant` removed). Same edge type, two contradictory treatments, patched by a post-hoc exception.

**Solution — explicit semantics table:**
```python
EDGE_SEMANTICS = {
    "JOIN":   {"propagates_value": False, "show_relationship": True},
    "FILTER": {"propagates_value": False, "show_relationship": True},
    "REF":    {"propagates_value": True,  "show_relationship": True},
    ...
}
```
- `compute_field_lineage` uses `propagates_value`
- L2 builder keeps/re-adds edges per `show_relationship`
- The JOIN survival pass becomes a *rule*, not a *patch*; the formal definition's "JOIN is conditional" becomes precise ("conditional for value flow; shown as relationship")

## Weakness 5: Zero Integration Tests for the Builders

**Evidence:** 329 tests pass, yet 11 bugs were found by manual API testing. The suite covers the extractor and node types (unit level) but **not** the L1/L2 builders where all the bugs lived.

**Solution — add `tests/test_l1_l2_integration.py` over the `multi_workflow` fixture:**
```python
def test_l1_lineage_pairs_stg_customers():
    g = _build_l1_graph(ws_id, scripts, "stg_customers", "customer_id")
    assert {tuple(p) for p in g["lineage_field_pairs"]} == {
        ("stg_customers", "customer_id"), ("crm_customers", "customer_id")}

def test_l2_step3_join_edges_survive():   # 2 JOIN edges
def test_l2_step3_no_table_flow_bypass(): # all TABLE_FLOW route through ⟐ output
def test_sql_range_indented_column():     # start_col == 3 for indented JOIN
```
Each fixed bug should have left a test — that is the discipline that prevents regression.

## Weakness 6: Non-Deterministic Iteration

**Evidence:** During the Bug 43 fix: `search_terms` is a `set()` with arbitrary iteration order, so "first matching term" was non-deterministic — fixed by taking `min` position across terms. Other set/dict iterations (`lineage_field_pairs`, `_production_pairs`, `table_fields` sets) are also order-sensitive in places.

**Solution:** Audit set iterations for order sensitivity; sort where output is user-visible (L1 node ordering, sql_range selection). Rule: *any iteration whose result affects output must be sorted.*

## Priority Ranking

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 1 | ✅ Done — `_estimate_sql_range` deleted (282 lines) | 2nd range-finding implementation removed | S |
| 2 | ✅ Done — `PRODUCTION_EDGES` from lineage.py; `EDGE_TYPE_STYLE` + `EDGE_TYPE_ORDER` deduped | Divergence class killed | S |
| 3 | ✅ Done — `tests/test_l1_l2_integration.py` (5 tests) | Regressions of all 11 fixes now caught | M |
| 4 | ✅ Done — `format_version: 3` in cache writes + mismatch warnings in readers | Data-loss-at-boundary made loud | M |
| 5 | ✅ Done — `EDGE_SEMANTICS` (16 types) in lineage.py; PRODUCTION/ALWAYS_BIDIR derived | Single source for edge rules | M |
| 6 | ✅ Done (light) — silent fallbacks now log warnings (alias_map, attach-to-first-table) | Wrong data is loud, not silent | L |
| 7 | ⏳ Not needed — min-position fix in label search already removed order sensitivity | Determinism | S |

---

## Bug 49: Table Autocomplete Empty After Field Is Selected (P2)

> **Found:** 2026-07-31 (user report) | **Priority:** P2 | **Status:** ✅ Fixed (v3.3.129) — verified end-to-end

**Verified fix:** `field_index["customer_id"]["tables"]` now = `['c','crm_customers','o','raw_orders','sc','so','stg_customers','stg_orders']` (physical tables added via `alias_to_physical` resolution in `index_scripts()`); `table_index["crm_customers"]["fields"]` = `['customer_id','full_name','is_active','region','segment']`. Frontend `getTableOptions()` falls back to all tables when the field-restricted list is empty. Simulation: prefix `crm` → `['crm_customers']` ✅. Production workspace re-indexed; frontend rebuilt & deployed.

**Symptom:** In the search UI, after the user types a field (`customer_id`), typing a table name (`crm`) yields NO suggestions for `crm_customers`, even though the table exists and contains that field.

### Verified reproduction

The backend endpoint works fine:
```
curl ".../autocomplete?type=table&q=crm"   → {"suggestions":["crm_customers"]}   ✅
```
But the search UI never calls it — `FilterPanel.jsx` does all filtering **client-side** over the index JSON from `/index`. The `/autocomplete` endpoint (`workspace.py:308-326`) and `api.autocomplete()` (`client.js:99-101`) are dead code.

### Root cause (two layers)

**Layer 1 — backend index build** (`folder_index_service.py:110-118`): for each column variable, the table association is derived only from the qualified-name prefix:
```python
table_name = name.split(".", 1)[0]   # "c.customer_id" → "c" (the ALIAS)
```
`crm_customers` is registered only as a `table`-type variable with **empty fields**. The Bug 41 cross-reference block (lines 124-153) maps fields only to **INSERT target** tables — `crm_customers` is a SELECT *source*, so it never gets `field_index["customer_id"]["tables"].add("crm_customers")`.

Decisive evidence from `/tmp/workspaces/0d4ae2cefe6a/cache/`:
```json
field_index["customer_id"]["tables"] = ["c", "o", "sc", "so"]   // aliases only!
table_index["crm_customers"]["fields"] = []                      // empty
```

**Layer 2 — frontend filter** (`FilterPanel.jsx:83-88`):
```js
const getTableOptions = () => {
  if (!field || !fieldIndex[field]) return tableSuggestions;     // fallback: ALL tables
  return (fieldIndex[field].tables || []).filter(...);           // → [] when tables=["c","o","sc","so"]
};
```
With the exact field typed, suggestions are restricted to the alias-only set; filtering `["c","o","sc","so"]` by prefix `"crm"` yields `[]` → empty dropdown.

### Suggested fix

**Primary (backend, root cause)** — in `index_scripts()` (`folder_index_service.py:100-118`), resolve aliases via the existing `alias_map` (built from `source_tables` at lines 88-93) when indexing column variables:
```python
# for column "c.customer_id" with alias c → physical crm_customers:
field_index[field_name]["tables"].add(physical)     # "crm_customers"
table_index[physical]["fields"].add(field_name)      # table_index["crm_customers"]["fields"]
```
This fixes both the table-suggestion direction and the reverse direction (`getFieldOptions()` uses `tableIndex[table].fields`).

**Secondary (frontend, robustness)** — in `FilterPanel.jsx:83-88`, fall back to the full `tableSuggestions` when the field-restricted list is empty (degrade to "show all tables" instead of an empty dropdown).

**Optional cleanup** — either wire FilterPanel to the existing `/autocomplete` endpoint (which already returns correct results) or remove the dead endpoint + client helper.

**Files:** `backend/app/services/folder_index_service.py:100-118`, `frontend/src/components/FilterPanel.jsx:73-88`, `backend/app/routers/workspace.py:308-326` (dead endpoint), `frontend/src/api/client.js:99-101` (dead helper)

---

# Code Review Findings — v3.3.129 (2026-07-31)

> **Reviewer:** AI Code Review | **Scope:** Full codebase | **Files reviewed:** 42 Python + 12 JS/JSX
>
> **⚠️ Human-reviewed verdicts (2026-07-31):** Not all findings are correct. Verified against code:
> - ✅ **VALID — FIXED & VERIFIED (v3.3.129):** CW1 (6 inner `except Exception` now log warning/error; top-level safety net kept), CW3 (`_extract_table_field_pairs` helper replaces both duplicate loops, semantics preserved), CW7 (edge_type normalized on cache read in l1+l2; `or`-chains kept), CW8 (all 3 sql_range paths end in `or [1,1,1,1]`; JOIN-survival enriches labels before find_sql_range; verified 0 edges with None on fresh+cache-hit), CW9 (`import re` added; NameError reproduced-then-fixed; latent but one-line insurance)
> - ⚠️ **PARTIAL:** CW2 (defensive `n.get("data", n)` already pervasive; dataclass refactor speculative), CW4 (factual monolith; P1 overstated), CW10 (upload+index covered via API helpers, but L1/L2 tested via direct builder calls — HTTP journey test is a legit gap; "would have caught Bug 42" wrong — that was frontend wiring)
> - ❌ **WRONG/STALE:** CW5 (format_version: 3 **already implemented** — `folder_index_service.py:96`, `l2_builder.py:97-111`, `l1_builder.py:711`, Lessons Learned item 4), CW6 (4-file layout split is documented intentional design — CLAUDE.md:61 frozen offsets; "field drift" unverified; suggested fix contradicts design)
>
> **Corrected priority:** CW8, CW1, CW3, CW7, CW9 (take) — not the original "CW1, CW9, CW10". All five taken items implemented and independently reviewed (APPROVE), 334 tests pass.

---

## CW1 — Pervasive Silent `except Exception` Error Swallowing

> **Priority:** P1 | **Status:** Open | **Type:** Systemic defect

**Location:** `l1_builder.py` lines 384, 713, 726, 739, 752, 797, 831

**Symptom:** 7 bare `except Exception:` blocks silently discard errors. The top-level handler at line 831 returns a degraded fallback graph (just script nodes, no edges) when *any* internal error occurs. A user sees a "broken" graph with no clue what failed.

**Evidence:**
```python
# l1_builder.py:797 — catastrophic error silencer:
try:
    lineage_set = compute_field_lineage(gdata, tn, fn, ...)
except Exception:
    continue  # <-- silently skips multi-hop expansion if BFS fails
```
If `compute_field_lineage` raises (e.g., malformed graph data), all subsequent multi-hop expansions are silently abandoned. The L1 graph shows incomplete lineage but reports success.

**Impact:** This pattern caused multiple regression bugs (Bug 30, 39, 40). Each time the symptom appeared in the UI but the root error was silently swallowed, making debugging very costly.

**Suggested fix:** Wrap only anticipated exceptions (e.g., `KeyError` on malformed node data). For unexpected exceptions, log at `ERROR` level with the script name and re-raise or propagate. At minimum:
```python
except KeyError:
    _log.warning(f"Malformed graph data in {s.get('script_name','?')}, skipping")
    continue
except Exception as exc:
    _log.error(f"compute_field_lineage failed for {tn}.{fn}: {exc}", exc_info=True)
    continue
```

**Files:** `backend/app/services/l1_builder.py:384,713,726,739,752,797,831`

---

## CW2 — Unguarded Deeply Nested Dictionary Access

> **Priority:** P1 | **Status:** Open | **Type:** Systemic defect

**Location:** `l2_builder.py` line 208-340, and pervasive across all services

**Symptom:** Code repeatedly accesses deeply nested dicts with no `KeyError`/`AttributeError` protection:
```python
tn = nd.get("data", n)        # if nd is not a dict, .get() on e.g. str fails
label = nd.get("label", "")
table_name = nd.get("table_name", nd.get("label", "").rsplit(".",1)[0])
```
When graph cache format changes (v3.2.15 → v3.3.x), or when old cached data is read, these assumptions silently break. The code was already patched with `nd = n.get("data", n)` to handle both wrapped and unwrapped nodes — evidence that the data contract is fragile.

**Impact:** This has caused Bug 27, 28, and part of Bug 39 — all caused by `table_name`/`field_name` being absent in certain node formats or across version upgrades.

**Suggested fix:** Define a lightweight typed interface (e.g., `@dataclass` or `TypedDict`) and validate at cache read:
```python
@dataclass
class GraphNode:
    id: str
    label: str = ""
    table_name: str = ""
    field_name: str = ""
    variable_type: str = ""

def _validate_and_normalize(raw_node: dict) -> GraphNode:
    nd = raw_node.get("data", raw_node)
    return GraphNode(
        id=nd["id"],
        label=nd.get("label", nd.get("name", "")),
        ...
    )
```
Normalize once on cache read; all downstream code works with a stable contract.

**Files:** `l2_builder.py:208-340`, `dataflow_service.py:255-330`, `graph_service.py:217-304`

---

## CW3 — L1 Builder Duplicate Extraction Logic

> **Priority:** P2 | **Status:** Open | **Type:** Code smell

**Location:** `l1_builder.py` lines 700-830

**Symptom:** `_build_l1_graph` does three overlapping passes over the same data:
1. Lines 700-730: Build global alias map from graph caches
2. Lines 731-755: Build all_table_fields from P4 graph caches  
3. Lines 770-800: Extract lineage_field_pairs by iterating per-node field_name
4. Lines 805-830: Multi-hop expansion repeating the same iteration pattern

The node-iteration logic extracting `(table, field)` pairs at lines 786-799 is duplicated verbatim at lines 813-827. Bug 37 already reported duplicate BFS implementations (now fixed), but the field extraction pattern remains duplicated.

**Suggested fix:** Extract a shared helper:
```python
def _extract_table_field_pairs(lineage_set: set, nodes: list,
                                alias_map: dict, table_fields: set) -> set:
    pairs = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("id") not in lineage_set: continue
        tn, fn = _resolve_table_field(nd, alias_map)
        if (tn, fn) in table_fields or not table_fields:
            if tn and not tn.startswith("⟐"):
                pairs.add((tn, fn))
    return pairs
```

**Files:** `backend/app/services/l1_builder.py:770-830`

---

## CW4 — L2 Builder is 811-Line Monolithic Function

> **Priority:** P1 | **Status:** Open | **Type:** Architecture

**Location:** `l2_builder.py` entire file

**Symptom:** `_build_l2_graph` is a single ~750-line function that performs:
- Graph cache read
- Relevance filter application
- Compound node structure building (table_nodes, field_nodes, other_nodes)
- Table classification (source/intermediate/output)
- BFS upstream/downstream set computation
- Edge list building with `find_sql_range`
- Edge combining pass
- Field-level → table-level edge promotion
- JOIN survival handling
- DML phantom field handling
- Alias field synchronization
- Partition pass

Each step is interleaved with ad-hoc loops over `nodes` and `edges`. The function is nearly impossible to unit-test in isolation — only integration tests exist.

**Impact:** Every L2 bug fix requires understanding the entire 811-line function. Regression risk is high because changes in one pass (e.g., edge combining) affect downstream passes (e.g., JOIN survival).

**Suggested fix:** Split into pipeline stages:
```python
def _build_l2_graph(...):
    full_graph = _load_or_build_graph(ws_id, script_name, sql_text)
    graph_data = _apply_relevance_filter(full_graph, table, field)
    compound = _build_compound_structure(graph_data, table, field)
    edges = _build_edge_list(graph_data, compound.id_map, sql_text)
    edges = _combine_duplicate_edges(edges)
    edges = _promote_field_edges_to_table(edges, compound.id_map)
    edges = _survive_join_edges(edges, full_graph, compound.id_map)
    edges = _apply_partition(edges, sql_text)
    _sync_alias_fields(compound, alias_map)
    _sync_dml_phantom_fields(compound, dml_pairs)
    return _assemble_output(compound, edges)
```
Each stage becomes independently testable.

**Files:** `backend/app/services/l2_builder.py:1-811`

---

## CW5 — Unversioned Graph Cache Format

> **Priority:** P2 | **Status:** Open | **Type:** Data contract

**Location:** `l2_builder.py:97`, `dataflow_service.py:277`, `graph_service.py:120`

**Symptom:** Cache key is `graph_3_2_15_{md5}` but the format has changed substantially without a schema version inside the JSON. P4/P5 fields (`table_fields`, `alias_map`) were added after the format was frozen. Code has defensive fallback paths to handle old caches lacking these keys.

**Impact:** When format changes (which happened multiple times during v3.3.x development), old caches silently produce wrong results or crashes. Debugging takes the form of "delete workspace and re-upload" — masking the root cause.

**Suggested fix:**
```python
CACHE_SCHEMA_VERSION = "3.4.0"

def _read_graph_cache(path: Path) -> dict | None:
    data = json.loads(path.read_text())
    if data.get("_schema_version") != CACHE_SCHEMA_VERSION:
        _log.info(f"Cache schema mismatch: expected {CACHE_SCHEMA_VERSION}, "
                  f"got {data.get('_schema_version')}, rebuilding")
        return None
    return data
```
Write: `data["_schema_version"] = CACHE_SCHEMA_VERSION`.

**Files:** `backend/app/services/graph_service.py:120`, `l2_builder.py:97`, `dataflow_service.py:277`

---

## CW6 — Fragmented Frontend Layout Responsibility

> **Priority:** P2 | **Status:** Open | **Type:** Architecture

**Location:** `snakeLayout.js` (107 lines), `layoutCore.js` (206 lines), `elkLayout.js`, `DataFlowGraph.jsx`

**Symptom:** Layout computation is split across 4 files with overlapping responsibilities. `computeFieldRelPos` in `layoutCore.js` computes relative field positions, but Cytoscape applies transforms that break this relationship — causing the recurring "fields drift when dragging parent" bug. Each fix to field positioning must be applied in 2+ places.

**Impact:** The field positioning defect has re-occurred multiple times because fixes in snake layout don't propagate to pipeline layout, and vice versa.

**Suggested fix:** Unify field positioning into a single post-layout pass:
```javascript
export function positionFields(cy, layoutPositions) {
    cy.nodes('[type="field"]').forEach(field => {
        const parent = field.parent();
        if (!parent.length) return;
        const parentPos = layoutPositions[parent.id()] || parent.position();
        const relPos = field.data('relPos') || { x: 0, y: 0 };
        field.position({ x: parentPos.x + relPos.x, y: parentPos.y + relPos.y });
    });
}
```
Run once after any layout, fixing field drift regardless of layout algorithm.

**Files:** `frontend/src/utils/snakeLayout.js`, `frontend/src/utils/layoutCore.js`, `frontend/src/utils/elkLayout.js`

---

## CW7 — `edge_type`/`relationship` Dual Naming

> **Priority:** P3 | **Status:** Open | **Type:** Code smell

**Location:** Pervasive across backend

**Symptom:** The same concept appears inconsistently as:
- `ed.get("edge_type")` in `graph_service.py`
- `ed.get("relationship")` in `lineage.py`
- `ed.get("edge_type", "") or ed.get("relationship", "")` in `l2_builder.py`
- `rel = d.get("relationship", "")` in `graph_service.py`

This dual naming came from the V2→V3 migration and causes defensive `or` chains throughout. Adding a new edge type requires remembering to set both keys.

**Suggested fix:** Choose canonical key (`edge_type`) and normalize on cache read:
```python
def _normalize_edge(edge_data: dict) -> dict:
    if "edge_type" not in edge_data:
        edge_data["edge_type"] = edge_data.get("relationship", "REF")
    return edge_data
```

**Files:** `graph_service.py`, `lineage.py`, `l2_builder.py`, `dataflow_service.py`

---

## CW8 — `sql_range` None Propagation

> **Priority:** P2 | **Status:** Open | **Type:** Defect

**Location:** `sql_range_finder.py:find()`, `l2_builder.py:411-430`

**Symptom:** `find_sql_range` can return `None` (empty SQL) but `l2_builder.py` doesn't guard:
```python
r = find_sql_range(enriched_copy, sql_text)
if not r:
    r = find_sql_range(enriched, sql_text)  # fallback
# ...
"sql_range": r,   # r could still be None!
```
If both calls return `None`, the `sql_range` field is set to `None`. Any consumer expecting an array will crash (e.g., `sql_range[0]` → `TypeError`).

**Suggested fix:** Provide safe default:
```python
r = find_sql_range(enriched_copy, sql_text) or \
    find_sql_range(enriched, sql_text) or \
    [1, 1, 1, 1]  # safe default
```

**Files:** `backend/app/services/sql_range_finder.py`, `backend/app/services/l2_builder.py:411-430`

---

## CW9 — Missing `import re` in l1_builder.py

> **Priority:** P1 | **Status:** Open | **Type:** Defect

**Location:** `l1_builder.py` line ~130

**Symptom:** The function `detect_role` uses `re.search()` at approximately line 130:
```python
if target_full in sc or re.search(rf'\b{re.escape(target_field)}\b', sc):
```
But `import re` does not appear at the top of `l1_builder.py`. The `re` import exists only inside `_build_l1_graph` (~line 390). If `detect_role` is called from outside that function's scope, it raises `NameError`.

**Suggested fix:** Add `import re` at module top level.

**Files:** `backend/app/services/l1_builder.py:1` (add import), `:130` (usage site)

---

## CW10 — No Integration Test for Full User Journey

> **Priority:** P1 | **Status:** Open | **Type:** Test gap

**Location:** `backend/tests/`

**Symptom:** 334 unit tests exist, but there is no test simulating the complete user flow:
1. Upload `multi_workflow.zip`
2. Index workspace
3. Search `stg_customers.customer_id`
4. Verify L1 shows correct lineage pairs
5. Open L2 for `step2_enrich_customers.sql`
6. Verify L2 edges have correct `sql_range`
7. Click L2 edge → verify SQL highlight

Each component is tested in isolation, but the integration between them is the source of most regression bugs.

**Impact:** This single test would have caught Bug 27, 30, 39, 40, 42, 43, 45, and 46 before they reached manual testing.

**Suggested fix:** Add integration test:
```python
def test_full_user_flow_multi_workflow(client, sample_zip):
    resp = client.post("/api/workspace/upload", files={"file": sample_zip})
    ws_id = resp.json()["workspace_id"]
    client.post(f"/api/workspace/{ws_id}/index")
    resp = client.post(f"/api/workspace/{ws_id}/search",
                       json={"table": "stg_customers", "field": "customer_id"})
    l1 = resp.json()["l1_graph"]
    assert len(l1["lineage_field_pairs"]) >= 2
    view_id = resp.json()["view_id"]
    resp = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level2",
                      params={"script": "multi_workflow/step2_enrich_customers.sql", ...})
    l2 = resp.json()["graph"]
    assert len(l2["edges"]) >= 2
    for e in l2["edges"]:
        sr = e["data"]["sql_range"]
        assert sr[1] >= 1  # start_col valid
```

**Files:** `backend/tests/` (new file: `test_integration.py`)

---

## Summary Table — Code Review Findings

| ID | Title | Priority | Type | Effort | Verdict |
|----|-------|----------|------|--------|---------|
| CW1 | Silent `except Exception` swallowing | P1→P2 | Systemic | Low | ✅ FIXED (logs added) |
| CW2 | Unguarded nested dict access | P1→P3 | Systemic | Medium | ⚠️ PARTIAL — speculative |
| CW3 | Duplicate extraction logic in L1 | P2 | Code smell | Low | ✅ FIXED (`_extract_table_field_pairs`) |
| CW4 | L2 builder 750-line monolith | P1→P3 | Architecture | High | ⚠️ PARTIAL — factual, not urgent |
| CW5 | Unversioned cache format | P2 | Data contract | Low | ❌ WRONG — already done (format_version) |
| CW6 | Fragmented layout code | P2 | Architecture | Medium | ❌ WRONG — contradicts documented design |
| CW7 | `edge_type`/`relationship` dual naming | P3 | Code smell | Low | ✅ FIXED (normalize on cache read) |
| CW8 | `sql_range` None propagation | P2 | Defect | Low | ✅ FIXED (safe default + enriched survival) |
| CW9 | Missing `import re` | P1→P2 | Defect | Low | ✅ FIXED (module-level import) |
| CW10 | No integration test | P1→P2 | Test gap | Medium | ⚠️ PARTIAL — HTTP journey test is a legit gap |

**Corrected top 3 to fix first:** CW8, CW1, CW9 (one-line insurance) — with CW3 and CW7 as cheap follow-ups.

---

## Bug 51: Two-File Filter Uses Union Instead of Intersection (R19)

> **Found:** 2026-08-03 (user requirement) | **Priority:** P2 | **Status:** Design pending review (R19 in REQUIREMENTS.md)
> **Verified:** current code has NO intersection logic — `allowed_tables` is the union; only a diagnostic warning exists.

### Current code (verified)

`backend/app/routers/workspace.py:upload_filter_config`:
```python
# File 1: allowed_scripts, allowed_tables (= A), script_table_tables = snapshot of A
# File 2: allowed_tables |= table_col tables (= B)   ← UNION
# Warning only: new_tables = allowed_tables - script_table_tables  (B − A)
```

### Solution design

**Data structures (file 2 parsing, ~line 156):** keep the table→column mapping, not just a flat column set:
```python
table_columns = {}   # table_name -> set(column_names)   NEW
allowed_columns = set()                                   # kept for API compat
...
for row in rows:
    tn = row.get("TABLE_NAME", "").strip()
    cn = row.get("COL_NAME", "").strip()
    if tn:
        allowed_tables.add(tn)
        if cn:
            table_columns.setdefault(tn, set()).add(cn)
            allowed_columns.add(cn)
```

**Intersection step (after both files parsed, before filtering):**
```python
if script_table_tables is not None:            # file 1 present
    if allowed_tables is None:
        allowed_tables = set()
    # R19: effective table scope = A ∩ B (B is None-safe: file1-only → A)
    allowed_tables &= script_table_tables
    # Restrict columns to effective tables (file2-only → table_columns empty → no-op)
    if table_columns:
        allowed_columns = {cn for t, cols in table_columns.items()
                           if t in allowed_tables for cn in cols}
```

**Diagnostics (R16 update, replace the old scope-expansion warning):**
```
│ R19: ignored N tables from table_col.csv (not in script_table scope)
│ Result: X tables, Y fields in filtered index
```

**Edge cases:**
- A ∩ B = ∅ (both files present, no common table): filter stays active with 0 tables / 0 fields + diagnostic warning "no common tables — check CSVs". Flag for reviewer: alternative is to treat as filter-cleared.
- Table name case sensitivity: exact match (existing behavior, unchanged).
- A-only tables: excluded per symmetric interpretation — flagged for reviewer confirmation (alternative: keep A-only tables since script_table.csv is the authoritative script scope; but R19 as written by the user is symmetric).

### Test cases (new `backend/tests/test_filter_config.py`)

Fixture: workspace from `samples/multi_workflow.zip` + index (reuse pattern from `test_l1_l2_integration.py`).

| # | Test | Setup | Assert |
|---|------|-------|--------|
| TC1 | Table in both files kept | script_table has `stg_customers`, table_col has `stg_customers` | `stg_customers` ∈ filtered table_index |
| TC2 | Table only in table_col excluded | table_col adds `report` (not in script_table) | `report` ∉ filtered table_index |
| TC3 | Table only in script_table excluded (symmetric) | script_table has `raw_orders`, table_col omits it | `raw_orders` ∉ filtered table_index |
| TC4 | Column of excluded table dropped | table_col: `report.report_date` (report not in intersection) | `report_date` ∉ filtered field_index |
| TC5 | Column of intersection table kept | table_col: `stg_customers.customer_id` | `customer_id` ∈ filtered field_index |
| TC6 | File-1-only unchanged | only script_table.csv | tables = A exactly |
| TC7 | File-2-only unchanged | only table_col.csv | tables = B, columns = B's columns |
| TC8 | No files clears filter | upload with no files | `filtered_index.json` deleted, `filtered: false` |
| TC9 | Empty intersection | script_table: `x`, table_col: `y` | 0 tables, 0 fields, filter still active |
| TC10 | Script scope still from file 1 | two-file upload | filtered script lists ⊆ file-1 scripts |

**Files:** `backend/app/routers/workspace.py` (~lines 156-210), `backend/tests/test_filter_config.py` (new), `REQUIREMENTS.md` R19 (done), R16 diagnostic block in workspace.py.

---

# Code Review Findings — Codex (2026-08-04) — Verified & Triaged

> **Reviewer:** Codex (read-only) | **Source doc:** `wiki/CODE_REVIEW_2026-08-04.md`
> **Human verification (2026-08-04):** 13/15 findings confirmed valid against code; 1 partial (L1 wording); baseline test count partially off (review says 339/0; current run = 334 passed/5 skipped).

| ID | Title | Priority | Verdict | Status |
|----|-------|----------|---------|--------|
| H1 | Path traversal in `ws_id` → arbitrary dir deletion | P0 | ✅ VALID — no validation in `workspace_service.py`; `(root/'..').resolve()==/tmp`; `delete_workspace` does rmtree | **Fix in progress** |
| H2 | `target_field_sc` undefined in l2_builder (latent NameError) | P1 | ✅ VALID — defined only at `dataflow_service.py:442`, no import in l2_builder (circular) | **Fix in progress** |
| H3 | `source_columns` computed but dropped at graph boundary | P1 | ✅ VALID — extractor produces it; `build_graph_data` doesn't copy; 3 consumers read `[]` silently (Weakness 2 recurrence; same mechanism as CW9) | **Fix in progress** |
| M1 | Literal backspace (0x08) in adapter.py:66 regex | P2 | ✅ VALID — `cat -A` shows `SELECT^H`; subquery count always 0 | **Fix in progress** |
| M2 | L2 never uses index-time precomputed graph cache (key mismatch) | P2 | ✅ VALID — `graph_{key}.json` (indexer) vs `graph_3_2_15_{key}.json` (L2) | **Fix in progress** |
| M3 | Two-file filter union vs intersection (R19) | P2 | ✅ VALID — verified (Bug 51/R19 design pending) | **Fix in progress** |
| M4 | `_build_l1_graph` degraded fallback returned as success | P2 | ✅ VALID (design opinion) — l1_builder.py:865-877 | Deferred (design decision) |
| M5 | CATEGORY_MAP/helpers duplicated in dataflow_service.py:396-433 | P3 | ✅ VALID — only EDGE_TYPE_STYLE/ORDER deduped; copies likely dead | **Fix in progress** |
| L1 | DELETE /workspace no guard | P2 | ⚠️ PARTIAL — no guard true; "wipes ALL" imprecise (single ws; all-wipe = H1 traversal) | Deferred (decision) |
| L2 | SSE queues never auto-cleaned | P3 | ✅ VALID — remove_queue only on explicit delete | Deferred |
| L3 | `_INDEX_PROGRESS` no lock; errors reset | P3 | ✅ VALID | Deferred |
| L4 | adapter.py sys.path insert of non-existent path | P3 | ✅ VALID — `/home/huangyf/sql_field_extractor` doesn't exist | **Fix in progress** |
| L5 | `window_computed` stale type in graph_service.py:138 | P3 | ✅ VALID — extractor emits `window` | **Fix in progress** |
| L6 | ~170MB build artifacts in git | P3 | ✅ VALID — static.bak.* confirmed tracked | Deferred (needs decision) |
| L7 | Error swallowing (29 backend / 23 frontend) | P3 | ✅ VALID — counts confirmed | Deferred (systemic) |
| — | Baseline: CLAUDE.md stale (3.3.106/1989 vs actual 3.3.129/445) | — | ✅ VALID | Deferred (doc) |

**In-progress batch (this session):** H1, H2, H3, M1, M2, M3 (R19 + test_filter_config.py), M5, L4, L5 — per Codex action order.
**Deferred:** M4, L1, L2, L3, L6, L7 + CLAUDE.md/ONBOARDING.md refresh.

---

## Bug 52: Filter Diagnostic Reports 96 Scripts From 48 Rows (P3, diagnostic)

> **Found:** 2026-08-04 (user report + screenshot parse_filer_error.png) | **Priority:** P3 | **Status:** Open

**Symptom:** `script_table.csv` has 48 rows, but the R16 diagnostic says `Parsed: 96 scripts, 8 tables`. One row = one script → count is 2× inflated.

**Root cause (verified in `workspace.py:163-169`):** each row expands into matching variants:
```python
allowed_scripts.add(sn)                    # bare name
allowed_scripts.add(os.path.basename(sn))  # basename (dedup when no path)
allowed_scripts.add(sn + '.sql')           # + .sql variant (if no .sql)
allowed_scripts.add(os.path.basename(sn) + '.sql')
```
For names without `.sql` and without path → 2 unique variants per row → 48×2=96. The diagnostic reports `len(allowed_scripts)` (variant set size) as "scripts". Variants are required for Bug 15 matching (index stores path+`.sql`); only the **count/reporting** is wrong.

**Observed diagnostic (OCR from screenshot):**
```
File 1 (script_table): script-table.csv rows=48
  Parsed: 96 scripts, 8 tables            ← inflated
File 2 (table_col): table-column.csv rows=3136
  Parsed: 2385 columns, 81 tables         ← correct (no variants)
R19: ignored 73 tables from table_col.csv (81−8=73) ✅
Result: 2 tables, 74 fields               ← ⚠️ only 2 of 8 common tables survived script matching — needs user-data verification
```

**Suggested fix:** track distinct scripts separately during file-1 parsing:
```python
distinct_scripts = set()   # raw SCRIPT_NAME values, dedup
...
if sn:
    distinct_scripts.add(sn)
    allowed_scripts.add(sn)
    ...
# Diagnostic:
f"│   Parsed: {len(distinct_scripts)} scripts ({len(allowed_scripts)} matching variants), {len(allowed_tables)} tables"
```

**Files:** `backend/app/routers/workspace.py:163-172` (parse), `:172` (diagnostic line)

---

## Bug 53: Unqualified Column References Get No Table Attribution (P2, extractor)

> **Found:** 2026-08-04 (user investigation) | **Priority:** P2 | **Status:** ⚠️ Known issue — **no auto-fix** (2026-08-04 decision: report-only, see Bug 54)

**Symptom:** A table whose columns are referenced WITHOUT an alias/qualifier can end up with zero fields in the index — even though the SQL clearly uses its columns.

**Verified (extractor test):**
```sql
INSERT INTO stg_customers (customer_id, full_name)
SELECT customer_id, full_name FROM crm_customers;
```
```python
col: name='customer_id'  source_tables=[]     ← NOT attributed to crm_customers
col: name='full_name'    source_tables=[]
```
The indexer (`folder_index_service.py`) derives the table from the name prefix (`name.split(".",1)[0]`) — for unqualified columns the prefix is empty → the source table gets no field. This is the same "information computed but not carried" family (Weakness 2), now at the extractor→index boundary.

**Answer to "is a table without fields ever right?"** — yes in two cases:
1. Table mentioned only in comments / not used by any uploaded script (SQL-evidence diagnostic shows "table name NOT found in SQL text")
2. Table referenced with all columns unqualified (`SELECT customer_id FROM t`) — currently LOST (this bug)

**Not adopted (2026-08-04 decision):** auto-resolution (extractor scope threading, indexer heuristics, sqlglot qualify) is NOT implemented — see the superseded design in SOLUTION_DESIGN.md steps 1c′/1c″. Orphan fields are surfaced for human review instead (Bug 54).

**Note:** the R19 filter diagnostic now logs SQL evidence for every common table with result-fields 0 (actual SQL lines + extractor columns), so users can manually verify whether a fieldless table is real before trusting the filter result.

---

## Follow-up Review Findings — F1–F6 (from wiki/CODE_REVIEW_2026-08-04.md §7.3, verified)

> Review dated 2026-08-04 evening. Human triage: F1 + F2 are real defects; F3–F6 are improvements.

### F1 (HIGH) — Search HTTP 400 after empty-intersection filter

After a TC9-style filter (both files, no common tables), `filtered_index.json` = `{"table_index": {}, "field_index": {}}`. `_load_index` (`dataflow.py:26-30`) returns `({}, {})` → `search_dataflow` raises `400 "Indexes not found. Run index first."` even though indexing succeeded. **Fix:** persist a `"filtered": true` marker; `_load_index`/search treats filtered+empty as "filter active, 0 results" + R17 diagnostic instead of 400.

### F2 (MEDIUM) — Falsy empty `allowed_tables` means "no constraint"

Guards use `if allowed_tables and tname not in allowed_tables: continue` — an empty set (file-1-only upload with zero table rows) skips the constraint → all tables kept. Inconsistent with the R19 empty-intersection override (0/0 = match nothing). **Fix:** `is not None` guard style (same as Bug 36) + a test locking the semantics.

### F3 (LOW/MED) — COL_NAME-only rows silently dropped

`if tn:` wraps `if cn:` → rows with a column but empty TABLE_NAME are discarded silently. At minimum log a warning count.

### F4 (LOW) — ignored_count not in the API payload

The filter response lacks `ignored_tables`/`ignored_count`/`warning` — the frontend banner can't explain vanished tables. Add to payload.

### F5 (LOW) — Case mismatch → silent 0/0, similar-table hint disabled

`STG_CUSTOMERS` vs `stg_customers` → intersection empty → the Bug-52 similar-hint loop (over A∩B) never runs. Suggest case-insensitive near-match scan over A/B names.

### F6 (MEDIUM, maintainability) — `upload_filter_config` ~240 lines

Extract a `filter_service.py` (parse → scopes → intersect → filter) per the project's l1/l2 builder split; keeps the router thin and makes F1–F5 testable without HTTP fixtures.

### Review verification notes (Bug 53 section)

- §8.3 "sqlglot.optimizer.scope resolves customer_id → table" — **verified WRONG**: `scope.columns` leaves `table=''`; the working API is `qualify.qualify(..., validate_qualify_columns=False)`, and it covers only single-source SELECT contexts (NOT UPDATE/DELETE/multi-table joins). Design doc 1c′ records the full evaluation.
- §9 category 2 (alias coverage, tpcds dim tables) — worth a targeted check: do the tpcds dimension tables get 0 fields because of unqualified column-name-prefix access (category 1) or a real alias_map coverage gap? Check before implementing Bug 53.
- §9 advice "classify fieldless tables into 4 categories; only category 1 is a hard defect" — adopted (SQL-evidence diagnostic already surfaces 3+4).

---

## Bug 54: Orphan Field Check — field-without-table validation (feature)

> **Requested:** 2026-08-04 (user) | **Priority:** P2 | **Status:** Design done — **report-only** (2026-08-04 decision)

**Purpose:** surface fields with no table attribution so extraction gaps (Bug 53) are visible instead of silent. Verified signal: `field_index[field]["tables"] == []` ⇔ orphan field (exact — the indexer always registers fields, only table association is gated).

**Design (report-only — no auto-fix, no fallback, no patch):**

After scripts are extracted (index time), push an R16-style **ORPHAN FIELD REPORT** diagnostic block. Per orphan field it MUST include the corresponding **script segment** (SQL lines where the field appears) so a human can review and fix the SQL:

```
┌─ ORPHAN FIELD REPORT ────────────────────────────────────────────┐
│ 3 fields have no table attribution (check SQL, then re-index)     │
│ field: customer_id    script: load_customers.sql                  │
│    L2: INSERT INTO stg_customers (customer_id, full_name)         │
│    L3: SELECT customer_id, full_name FROM crm_customers;          │
│ field: full_name      script: load_customers.sql                  │
│    L2: INSERT INTO stg_customers (customer_id, full_name)         │
│    L3: SELECT customer_id, full_name FROM crm_customers;          │
└───────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- Orphans = `{f for f, d in field_index.items() if not d.get("tables")}`
- Per orphan: scripts from `field_index[f]["scripts"]`; SQL lines via case-insensitive line search of the field name in the script file (same mechanism as the filter's SQL-evidence diagnostic)
- Optional: persist `cache/orphan_fields.json` `{field: [scripts]}` + `orphan_field_count` in the index response

**Files (to implement):** `folder_index_service.py` (post-extraction report; optional cache + response fields)

**Pairs with:** Bug 53 (documented known issue) — the report is the visibility layer; the orphan count is the regression meter.

---

## Follow-up Review 2 Verdicts — D1–D9 on the (superseded) 1c′/1c″ design

> Source: wiki/CODE_REVIEW_2026-08-04.md §11–13. Context: the 1c′/1c″ auto-resolution design is SUPERSEDED (report-only decision) — D findings are judged as analysis; only those affecting the report design are taken.

| ID | Verdict | Evidence / action |
|----|---------|-------------------|
| D1 (alias counted as 2nd table) | ✅ VALID analysis | Correct — scope {crm_customers, c} would block attribution for `SELECT customer_id FROM crm_customers c`. Fix would be counting distinct physical tables. Moot (design superseded) — recorded as a correction to the superseded analysis. |
| D2 (no tests landed) | ✅ VALID | The "verified" claims were ad-hoc probes, not committed tests. **TAKEN**: the report implementation (Bug 54) must land with tests. |
| D3 (WHERE-clause columns not covered) | ✅ VALID analysis | Design threaded only SELECT paths. Moot for implementation. |
| D4 (aliased SELECT exprs) | ✅ VALID analysis | Moot — BUT the tpcds probe (below) shows expression-alias orphans are REAL and numerous; the report will surface them. |
| D5 (INSERT…VALUES columns ARE registered) | ❌ **WRONG — verified** | `INSERT INTO t (customer_id, full_name) VALUES (1,'x')` registers ONLY the table variable. Original design claim was correct. |
| D6 (len==1 guard) | ✅ Valid defensive note | Moot. |
| D7 (CTE name resolution) | ✅ Valid clarification | Moot — report shows SQL lines, human judges. |
| D8 (cache format_version) | ⚠️ Partially applicable | Bug 54 adds a NEW cache file (`orphan_fields.json`) — no graph-format change, no version bump needed; note only. |
| D9 (tpcds pre-check) | ✅ VALID — DONE | See classification below. |

### D9 pre-check result (tpcds, verified)

```
scripts: 99, tables: 107
FIELDLESS tables (8): call_center, catalog_page, inventory, promotion,
  reason, ship_mode, warehouse, web_site — ALL referenced in 2–7 scripts
  (not comment-only)
ORPHAN fields (283): Call_Center, Call_Center_Name, Manager,
  SR_RETURN_AMT_INC_TAX, act_sales, amc, amt, average_sales,
  avg_quarterly_sales, best_performing ...
```

**Classification:** the tpcds fieldless tables are NOT (mostly) Bug 53 unqualified-column cases — they are accessed via aliased/qualified patterns (category 2 suspicion) and the orphan pool is dominated by **SELECT-expression aliases** (a distinct orphan flavor). Implication: (a) the superseded 1c′ fix would not have covered them — the report-only decision is the right one; (b) the Bug 54 orphan report will surface a rich mix — the SQL-segment per field is essential for the human to classify alias-vs-expression-vs-unqualified.

---

## Orphan Scan Record — all samples (2026-08-04, team scan)

**10 workspaces, 330 scripts, 661 orphans.** Full table + classifications in the session report.

| Class | Share | Meaning |
|-------|-------|---------|
| expression-alias | ~2/3 | derived/aggregate/window/CTE aliases — mostly legitimate (aliases are not table columns) |
| unqualified | ~1/3 | Bug 53 pattern — human should check/fix SQL |
| qualified-but-unattributed | **0** | attribution mechanism (Bug 49 alias map + Bug 41 DML) is sound |

Key facts:
- `orphan_field_count` == `orphan_fields.json` size in every sample (check consistent)
- tpcds fieldless dim tables (call_center etc.) legitimately empty — FROM/JOIN/*/COUNT only
- spider_complex fieldless tables == exactly the tables its orphans query (unqualified access)
- dwh_analytics is a broken sample (12/13 scripts are 404 placeholders); its orphans are information_schema columns
- standalone/multi_workflow clean (fully qualified)
- Design option (pending user): report could mark each orphan's class ([alias] vs [unqualified]) to reduce review noise

---

## Code Review §14–17 Verdicts (R1–R6) — 2026-08-04 (reviewed via /subtask)

> Reviewer verified live: Bug 54 TC-A..D ✅, F1/F2/F3/F4/F5 ✅, suite 360 passed/0 failed (grew from 355).

| ID | Sev | Finding | Triage | Next step |
|----|-----|---------|--------|-----------|
| R1 | 🟠 Med | F2 silently changed the empty-COL_NAME case: file-2-only CSV with table row but blank COL_NAME → 1 table, 0 fields (before F2: all fields kept). R19 says single-file uploads unchanged. | ⚠️ Needs a semantics decision | Decide: blank COL_NAME row = table with no columns (current) vs ignore row (before). Add the missing test. |
| R2 | 🟡 Low/Med | F4 payload (warning/ignored_tables) not rendered — FilterPanel.jsx only reads table_count/field_count. | ✅ Valid | Frontend wiring to show the warning banner. |
| R3 | 🟡 Low | F1 early-return skips the R17 diagnostic + view persistence (empty search won't survive reload). | ✅ Valid | Emit R17 diagnostic on the no_matches path; persist the empty view. |
| R4 | 🟡 Low | Orphan SQL-evidence lines use substring match → short names (id, amt) get false-positive lines. | ✅ **Taken (applies twice)** | (a) Report: word-boundary `\b` or skip names < 4 chars. (b) **Resolution design invariant**: schema-based resolution must use exact/word-boundary name matching — orphan `id` must never match `customer_id` in an inferred schema. |
| R5 | 🟡 Low | `_resolve_orphan_script` duplicates the filter's script resolver. | ✅ Valid | Hoist a shared resolver with F6 (filter_service.py). |
| R6 | ℹ️ Info | tpcds orphan `Call_Center` is a TABLE NAME listed as an orphan field (from `cc_call_center_id Call_Center`). | ✅ **Taken (taxonomy guard class)** | Orphan-type taxonomy gains a **field-name == table-name collision** class — the resolver must never mis-attribute these; count them separately from plain unqualified. |

**Folded into the orphan solution design:** R4 (word-boundary invariant) + R6 (collision class) — see the orphan type analysis (tpcds/financial agents, in progress) and the upcoming solution design.

---

## Orphan Type Classification — subagent results (2026-08-04, batch 2)

> Source: orphan-type analysis agents (sqlglot scope-based classifier). Batch 1 = financial/spider_complex/dialect_test/mock_sql_test/multi_test (73 occurrences). Batch 2 (tpcds 283+303) pending.

**Per-class tallies (73 occurrences, 5 samples):**

| Class | Count | % | Meaning |
|-------|------:|---:|---------|
| plain_alias | 27 | 37.0% | `t.col AS x` — alias of a plain qualified column |
| expr_alias | 23 | 31.5% | `SUM(x) AS total` / `CAST(...) AS y` — expression output |
| unq_multi | 18 | 24.7% | bare column, statement ≥2 table sources |
| other | 4 | 5.5% | pseudocolumns (LEVEL), trigger vars (new/old) |
| unq_single | 1 | 1.4% | bare column, exactly 1 table source |
| sys_table | 0 | — | (dwh_analytics earlier scan: 8 info_schema orphans) |

**Strategy coverage:** (c) CTE/query-output attribution 68.5% — dominant; (b) schema-based 24.7% (13.7% genuinely schema-required); (a) scope resolution 1.4% whole-statement, **~12% with nearest-scope rule** (8 of 18 unq_multi have a local scope with exactly 1 FROM — e.g. `SELECT DISTINCT blocked_merchant_id FROM gps_risk_scores`); (e) unresolvable 5.5%.

**Design refinement from data:** resolve unqualified columns against the NEAREST enclosing SELECT's FROM (not the whole statement) — lifts scope resolution 1.4% → ~12% with no schema needed. The extractor already stores `sql_expression`/`source_columns` on alias vars — plain_alias resolution mostly consumes existing fields + alias map.

---

## Orphan Type Classification — CONSOLIDATED (all samples, 2026-08-04)

> Batches: financial group (5 samples, 73 occurrences) + tpcds (283) + tpcds_qualified (303) = 659 classified; + dwh_analytics 8 sys_table = 667 total.

**Per-class tallies (659 classified occurrences):**

| Class | Count | % |
|-------|------:|---:|
| unq_multi (bare, ≥2 table sources) | 379 | 57.5% |
| expr_alias (expression output) | 147 | 22.3% |
| plain_alias (`t.col AS x`) | 98 | 14.9% |
| unq_single (bare, 1 table source) | 31 | 4.7% |
| other (pseudocolumns/trigger vars) | 4 | 0.6% |
| sys_table (info_schema; +8 in dwh_analytics) | 0 (8) | 1.2% |

**Per-sample view:**

| Sample | total | expr_alias | plain_alias | unq_single | unq_multi | other |
|--------|------:|-----------:|------------:|-----------:|----------:|------:|
| financial | 46 | 18 | 26 | 0 | 2 | 0 |
| spider_complex | 10 (16 occ) | 0 | 0 | 0 | 10 (16) | 0 |
| dialect_test | 5 | 0 | 0 | 1 | 0 | 4 |
| mock_sql_test | 5 | 5 | 0 | 0 | 0 | 0 |
| multi_test | 1 | 0 | 1 | 0 | 0 | 0 |
| tpcds | 283 | 53 (18.7%) | 35 (12.4%) | 13 (4.6%) | 182 (64.3%) | 0 |
| tpcds_qualified | 303 | 71 (23.4%) | 36 (11.9%) | 17 (5.6%) | 179 (59.1%) | 0 |

**Strategy coverage (final):**
- (c) CTE/query-output attribution (expr+plain alias): financial group **68.5%**; tpcds **31–35%**
- (b) schema-based (unq_multi): tpcds **59–64%** — the big lever; financial 24.7% (13.7% genuinely schema-required)
- (a) scope resolution (unq_single, nearest-scope measure): tpcds ~5%; ~12% of financial's unq_multi lift with nearest-scope rule
- Combined (b)+(c): **~95% of tpcds orphans**

**Key design facts from the data:**
1. unq_multi dominates TPC-DS (join predicates `wr_web_page_sk = wp_web_page_sk`, filters `d_year=1999`) — schema-based resolution is the main lever there
2. plain_alias fix is CHEAP: the extractor already stores `source_columns`/`sql_expression` (e.g. `batch_total` → `sb.total_amount`); walk them through the Bug-49 alias map
3. scope-level (nearest query node) counting is the correct measure — statement-level counting would zero out unq_single in TPC-DS (every statement nests subqueries)
4. Alias-of-bare-column orphans (48/sample in tpcds) need two hops: alias → source column → table
5. sys_table/other are rare; pseudocolumn lists (LEVEL/new/old) are dialect-specific, not needed by these samples

---

## Residual-Orphan Fixes — Implementation Result (2026-08-06)

Implemented + landed (tests `test_orphan_residual_fixes.py`, 19 tests, all pass): Fix A (set-op scope edge — `_walk_columns_in_expr` now walks Subquery/Exists bodies that are UNION/INTERSECT/EXCEPT via `_walk_setop`, giving each branch its own scope; spider 052/053 DestAirport+SourceAirport → Flights), Fix B (S1 bare-column chain — alias of a plain column inherits the source column's single-table S3 attribution; `cc_call_center_id Call_Center` → call_center), Fix C (derived-table output columns — S2 extended from CTEs to aliased derived tables with one-hop → derived alias and two-hop → source table; q93 `act_sales`/`ss_customer_sk` → t). Also made the unresolved report name-level-consistent (a field attributed in ANY scope is not listed as an orphan — subquery phantom copies no longer pollute). Coverage sweep (index-level, post-S4): overall 95.8% → 96.6% (tpcds 94→95.7, tpcds_qualified 95.8, financial 99.4 unchanged, dwh 100 unchanged, dialect 97.5→100, spider_complex 99.6); residual orphans 291 (baseline 661); remaining classes are schema-required 1a/1b (tpcds multi-table bare columns/aliases, financial alias-only fields) — reported, never guessed.

---

## Batch Implementation — 2026-08-06 (4 parallel teams, all landed in v3.3.131)

| Item | Status | Evidence |
|------|--------|----------|
| F6 filter_service.py extraction | ✅ Done | New `services/filter_service.py` (427 L) — parse → scopes → A∩B → filter + diagnostics; router thin (workspace.py 199 L); TC1-TC10 + F1-F5 pass unchanged |
| R5 shared script resolver | ✅ Done | `filter_service.resolve_script()` single implementation; `_resolve_orphan_script` delegates |
| R1 blank COL_NAME semantics | ✅ Decision + impl | Blank COL_NAME row = table **unconstrained** (all fields kept); no-leak guard outside A∩B; new diag line; 4 tests (`TestR1BlankColName`); REQUIREMENTS.md R19 note |
| R3 no_matches diagnostic + persistence | ✅ Done | F1 branch emits R17 SEARCH DIAGNOSTIC via `_push`; view persisted to views.json via shared `_persist_search_view` (new test); frontend restores empty view via localStorage (`df_last_search_view`) |
| L2 SSE queue cleanup | ✅ Done | Ref-counted per-workspace queues; dropped when last client disconnects (GeneratorExit/CancelledError safe) |
| L3 index progress lock | ✅ Done | `_INDEX_PROGRESS_LOCK`; errors preserved not wiped; **bonus bug fixed**: R20 section overwrote `total` with `total_columns` → "done" progress showed 0/0 |
| R2 filter warning banner | ✅ Done | FilterPanel renders `warning` + `ignored_tables` (capped 10) |
| R20 coverage badge | ✅ Done | `ResolutionReport.jsx` + `resolutionReport.js` util (normalizes the 2 backend stats shapes); vitest 31/31 |
| Orphan Fix A/B/C | ✅ Done (c919471) | See record above — coverage 95.8% → 96.6%, residuals 291 |
| SELECT-side schema enrichment | 📋 Design only | Appended to SOLUTION_DESIGN.md — two-tier S4a (extractor) + S4b (index, scope-aware, replaces scope-blind loop); phased rollout report-only → auto; est. 55–65% of 1a/1b resolvable; 6 open questions for human |

**Full suite: 414 passed / 5 skipped.** Version 3.3.131 deployed, health OK.
**Next steps:** SELECT-side schema enrichment Phase 0/1 (instrumentation + report-only audit) per the design's 6 open questions.

---

## S4 Phase 0/1 — SELECT-Side Schema Enrichment: Instrumentation + Calibration Audit (2026-08-06)

**Phase 0 (instrumentation, report-only) + Phase 1 (report-only audit) implemented — behavior-neutral verified.**

### What landed (v3.3.132, not yet committed at record time)
- Extractor (`variable_extractor_v2.py`, +212 L): per-script `script_schemas` (canonical table → columns) from 3 evidence sources — qualified refs (alias→canonical resolved, db dropped), DML target column lists (INSERT/UPDATE/MERGE SET, evidence-only, no column vars), CREATE TABLE/CTAS column lists; `schema_candidates` stashing for unresolved bare columns in ≥2-table scopes ({field, visible_tables, loc, owner?}); `r6_collision` counter; `loc` from the tokenizer (first-occurrence caveat). NO attribution — `source_tables` untouched, `resolved_by["schema"]` stays 0, candidates remain in `unresolved`.
- Index (`folder_index_service.py`, +145 L): M_ws workspace schema map; cross-script re-test; ORPHAN RESOLUTION REPORT gains `schema candidates: N (unique visible owner found: M) | r6 collision: K` + per-orphan `field: x → owner (evidence: script Ln, visible: ...)` lines; response gains `schema_candidates_summary: {total, unique_owner, r6_collision}` (always present, zeroed on old caches — old-cache report output byte-identical). `coverage_pct` unchanged.
- Tests: `test_s4_instrumentation.py` (22) + `test_s4_report.py` (9). Full suite 445 passed / 5 skipped (was 414).

### Calibration audit (team scan, 10 samples + combined evidence workspaces)
- Sweep reproduced the baseline exactly: overall 96.60%, 291 orphans (behavior-neutral).
- Combined tpcds+tpcds_qualified: **118 orphans with a unique visible owner** (80.3% of the 147 orphans); bare tpcds → 0 (no qualified refs / no DDL — evidence must come cross-script).
- **Reality vs design estimate**: resolvable 76.6% (est. 55–65%) — higher; genuinely ambiguous 0% (est. 17–27%) — far lower (TPC-DS columns are schema-unique; the ≥2-owner rule is unit-tested but has no sample-level exercise — fixture corpus recommended).
- **Human audit: 52 unique-owner proposals read line-by-line against SQL + DDL → 52 ✅ / 0 ❌ / 0 ⚠️ (100% correct)**, 118/118 mechanically DDL-verified (owner table present in the evidence statement's FROM). Cases validated: join predicates (21), filters (12), projections/group keys (15), special (4: q91 7-table-scope implicit aliases `cc_call_center_id Call_Center` — Fix-B chain couldn't fire, S4b fills the gap; spider_complex `isofficial → countrylanguage` case-insensitive real-world match).

### Phase 2 gate: PASS (pending user go)
- **Recommendations before enabling auto-resolution (S4a attribution + S4b replacing the scope-blind loop):**
  1. Fix `loc` first-occurrence caveat (2/118: q76 string-literal `'ws_ship_hdemo_sk' col_name` — anchor to the candidate statement's line range, or suppress literal-only candidates)
  2. Report should show the schema-EVIDENCE line (the DDL/qualified-ref line that proves the owner), not the bare-use line — DDL (`tpcds_qualified/tools/tpcds.sql`) proved the dominant source (118/118)
  3. Add a small 1b fixture corpus (two visible tables both owning `id`/`name`) for sample-level never-guess validation
  4. Remaining 1a classes are S2-extension territory, not S4: q71 derived-table output chains (`sold_item_sk`/`time_sk`), financial's 7 CTE-chain aggregate aliases
  5. Design open-question 6 validated: an explicit "import schema from DDL file" workflow makes S4 effective for evidence-less workspaces
- Design open-question 2 validated: case-insensitive whole-name matching is correct (spider `IsOfficial` vs bare `isofficial`; DDL `sr_return_amt_inc_tax` vs `SR_RETURN_AMT_INC_TAX`).
