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

> **Found:** v3.3.120 | **Priority:** P3 | **Status:** ✅ Fixed (v3.3.129) — see Quick Status table

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
>
> **Re-verified 2026-08-13 (v3.3.153):** status lines below updated to current source. Net disposition — CW1/CW3/CW7/CW8/CW9 ✅ Fixed; CW4 ✅ Fixed (monolith split into named phases, C1); CW10 ✅ Fixed (`test_full_http_journey.py` + `test_l1_l2_integration.py` + `test_flow_roles.py`); CW2 ⚠️ Partial (refactor still judged speculative); CW5/CW6 ❌ Stale.

---

## CW1 — Pervasive Silent `except Exception` Error Swallowing

> **Priority:** P1 | **Status:** ✅ Fixed (v3.3.129) — 5 inner `except Exception as exc:` now log warning/error; top-level handler keeps the visible M4-B degraded fallback | **Type:** Systemic defect

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

> **Priority:** P1 | **Status:** ⚠️ Partial — defensive `n.get("data", n)` pervasive (33 sites); dataclass/TypedDict refactor judged speculative, not pursued | **Type:** Systemic defect

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

> **Priority:** P2 | **Status:** ✅ Fixed (v3.3.129) — `_extract_table_field_pairs` helper (l1_builder.py:196) replaces both duplicate loops | **Type:** Code smell

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

> **Priority:** P1 | **Status:** ✅ Fixed (addressed) — `_build_l2_graph` split into named phases (`_build_edge_list`, `_simplify_dml_edges`, `_map_search_target_ids`, `_promote_field_edges`, `_combine_edges`, `_dedup_edges`, `_closure_walk`, `_downstream_walk`, `_assemble_output`, …) | **Type:** Architecture

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

> **Priority:** P2 | **Status:** ❌ Stale — already implemented: `format_version: 4` + `GRAPH_CACHE_PREFIX` (cache_keys.py, single source of truth) version the graph cache | **Type:** Data contract

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

> **Priority:** P2 | **Status:** ❌ Stale — intentional design: `config/layout.js` (single source of truth) + `layoutCore.js` (shared helpers) + per-algo coordinators | **Type:** Architecture

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

> **Priority:** P3 | **Status:** ✅ Fixed (v3.3.129) — normalized on cache read (l2_builder.py:109-112 `setdefault("edge_type", …)`); `or`-chains kept for legacy safety | **Type:** Code smell

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

> **Priority:** P2 | **Status:** ✅ Fixed — safe defaults in place (`l2_builder.py` 441-442 and 461: `... or [1, 1, 1, 1]`); status line corrected 2026-08-06 | **Type:** Defect

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

> **Priority:** P1 | **Status:** ✅ Fixed (moot) — `detect_role` no longer uses regex; `re` is absent from l1_builder.py so the NameError cannot occur | **Type:** Defect

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

> **Priority:** P1 | **Status:** ✅ Fixed — `test_full_http_journey.py` + `test_l1_l2_integration.py` + `test_flow_roles.py` cover the full upload→index→search→L1→L2 journey | **Type:** Test gap

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

> **Found:** 2026-08-04 (user report + screenshot parse_filer_error.png) | **Priority:** P3 | **Status:** ✅ Resolved — diagnostic now reports distinct-script counts + per-common-table KEEP/DROP (SQL-evidence) lines; verified in the 08-04 follow-up review §7; status line corrected 2026-08-06

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

**Category-2 check — RESULT (2026-08-06, v3.3.133, live index of tpcds_qualified):** the check is **moot — S4 Phase 2 resolved the fieldless tables**. On v3.3.133 the 8 former fieldless tpcds dim tables all have fields via schema attribution: `call_center` (4: cc_call_center_id, cc_call_center_sk, cc_county, cc_manager), `catalog_page` (2), `inventory` (4), `promotion` (5), `reason` (2), `ship_mode` (3), `warehouse` (1), `web_site` (4). No alias_map coverage gap exists. The only remaining fieldless table is `dbgen_version` — **category 4 (legitimately empty)**: referenced solely via `SELECT COUNT(*)`, `DELETE FROM`, `DROP TABLE` (tools/count.sql + teardown scripts); no query ever uses one of its columns. Expected, correctly surfaced, not a defect. **Closed — no Bug 53 category-1/2 residue in tpcds.**

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

---

## S4 Phase 2 (AUTO-RESOLUTION) + Code Review 2026-08-06 — Batch Implementation (v3.3.133, 2026-08-06)

Four parallel workstreams (2 teams + 2 agents), all findings in `wiki/CODE_REVIEW_2026-08-06.md` verified against code first. Nothing committed by teams; single integration commit.

### A. S4 Phase 2 — auto-resolution (design gate PASS, Phase 0/1 audit 52/52)
- **Extractor S4a** (`variable_extractor_v2.py`, now 1765 L): `_finalize_schema_candidates()` called from `build_resolution_stats()` — R6 guard (field==visible table, counted, never attributed) → owners = visible tables with whole-name case-insensitive evidence (R4) → exactly 1 → auto-attribute COLUMN vars in the recorded contexts (`source_tables=[owner]`, `resolved_by["schema"]+=1`, candidate REMOVED — residual-only contract); 0/≥2 stay unresolved (never guess). Candidate `loc` statement-anchored (first-4-token head of `expr.sql(mysql)` with AS skipped both sides, tokenizer match — q76 string-literal capture fixed; merge evidence lines fixed). `script_schemas` is now dict-of-dicts `{table: {col: evidence_line_int}}` (first occurrence wins; old list shape still read).
- **S2 extensions** (mechanisms, never guesses): q71 set-op derived tables in JOINs now walked via `_walk_setop(derived_alias=...)` (sqlglot parses `FROM item, (SELECT… UNION ALL …) tmp` as CROSS JOINs — body was never walked); `setop_body=True` suppresses two-hop (per-branch sources differ); CTE set-op bodies via `_walk_setop(cte_name=...)`; qualified stars `pe.*`/`pnp.*` expand the referenced CTE/derived recorded outputs (sqlglot 30.12 parses as `Column(this=Star)`); `_walk_select` shadowing `cte_name=None` initializer removed (dropped cte_name for setop CTE bodies). Probes: q71 `sold_item_sk`/`time_sk` → `["tmp"]`; fin_query8 0 unresolved (was 7).
- **Index S4b** (`folder_index_service.py`): scope-blind S4 loop REPLACED by the S4b loop — per-candidate re-test only within its OWN `visible_tables` (never workspace-global), owner must already be in `table_index` (no fabricated entries, L1), exact table-name match first with case-variant fallback only when the exact name has no evidence (L2); attribution persists into the analysis cache (`_apply_s4b_cache_update`) + field/table index + `by_strategy["schema"]` + report owner lines with schema-EVIDENCE provenance (`evidence: script Ln` + `used:` when the bare-use loc differs; DDL-named scripts sort first).
- **M4-B degraded L1** (`l1_builder.py`): catch-all fallback now returns `"degraded": True` + emits an `L1 GRAPH DEGRADED` diagnostic box (R16/R17 channel); all normal paths `"degraded": False`.
- **Fixture**: `samples/ambiguous_id/` (1b — customers/orders own `id`+`name`, products owns only `name`; joins use `*_key` so `id`/`name` stay bare).

### B. Code review 2026-08-06 — verified findings, all fixed
- **H1 (P0) path traversal** — `resolve_script`: every candidate `resolve()`d + `is_relative_to(scripts_root)` containment; absolute/`../`/backslash rejected, basename/±.sql tolerance kept.
- **M2** Fix B × CTE: bare-column alias chain now checks scope.ctes outputs → scope.deriveds outputs → S3 (same order as `_register_column`); `WITH w AS (SELECT id FROM t2) SELECT id AS c FROM t1, w` → `c → ["w"]`, alias and source column land together.
- **M3** evidence canonicalization: case-insensitive CTE/derived membership guards (no phantom `C` from `SELECT C.x` with CTE `c`); MERGE target alias registered into `_table_aliases` + `merge_scope.aliases` (ON `tgt.id` now evidences `customers`, not `tgt`).
- **M4** Fix A double-count: raw walk prunes set-op subquery bodies (columns register once, via branch scopes); spider `total_columns` 4 (was 6). Coverage numbers are now denominator-clean.
- **M5** malformed CSV → 400 (`(row.get(..) or "").strip()` at all sites + try/except). **M6** R1 `filtered_fi↔filtered_ti` symmetry (same per-table predicate in `filtered_tables`). **M7** SSE queue: `_push` lock-guarded peek, never recreates a removed queue (L2 cleanup actually works).
- **M8** no-match banner survives reload: both persist sites now carry `match_mode` (+`message`); frontend merge overlays saved metadata onto the server entry (`??`, server wins).
- **M9/M10/L14** ResolutionReport: branches on `unresolvedCount` (names-absent → "details unavailable"); total=0+unresolved>0 → badge "—" (backend 100.0 not inherited); header shows the true count with "— showing first N".
- **M11** `schema_candidates_summary` rendered in ResolutionReport when present. **L8** diagnostic scope counts come from `_load_index` (no double read/TOCTOU). **L9** heavy writes via `asyncio.to_thread` (filtered index, views.json).
- **L10** filter CSV cap 20 MB → 400. **L11** `_decode_csv` utf-8-sig → gb18030 → latin-1 with R16 hint. **L12** `client.js` `errorDetail()` (non-JSON error bodies → `HTTP <status>`). **L13** resolution card follows `data-theme` light theme. **L15** no-match banner wraps.
- **L1/L2/L7/N2/N3** index-side (owner-in-table_index guard; exact-name-first owner matching; progress errors copied; report line clipping; all-three-keys `s4c_seen` gate). **L3** Fix C shadowing kept by design (corpus-audited, q71 relies on it) — documented + pinned. **L4** junk output names (`*`, literals) skipped. **L5** unaliased qualified projections keep two-hop. **N4** no_matches persisted cache shape parity (`target` key). **N5** dead `_diag_box` removed. **N6** R1 blank-row-wins diagnostic line. **N7** `.gitignore` entries (docker_image/, *.bak, static.bak.*).

### C. Tests
Backend **495 passed / 5 skipped** (was 445/5): +30 extractor (`test_s4_instrumentation.py` rewritten), +10 `test_s4b_resolution.py` (incl. 1b never-guess E2E + M4-B), +12 `test_logger.py`, +30+ `test_filter_config.py` additions (H1/M5/M6/L10/L11/N6/M8), +6 review tests in `test_orphan_residual_fixes.py`. Frontend **52 passed** (was 8): `restoreViews` (6), `ResolutionReport.test.jsx` (11), `FilterPanel` (2), `resolutionReport.test.js` (10) — first component tests (`@testing-library/react` now used).

### D. Coverage sweep (v3.3.133, definitive)
| corpus | scripts | orphans | coverage | schema events (S4a/S4b) |
|--------|---------|---------|----------|--------------------------|
| tpcds.zip | 99 | 123 | 96.2% | 37 / 0 |
| tpcds_qualified.zip | 108 | **9** | **99.7%** | 162 / 113 |
| combined | 207 | **8** | **99.9%** | 200 / 114 |

Combined orphans **291 → 8** (baseline 95.8% → 99.9%). The 8 residuals: evidence-absent fields in ≥2-table scopes and R6-adjacent cases — honest leftovers, reported in the ORPHAN RESOLUTION REPORT. Note: the M4 denominator fix makes numbers not directly comparable with the 96.6% Phase-0/1 figure (that denominator included phantom copies).

## A1 Schema Classification + Remaining Batch — Implementation (v3.3.134, 2026-08-06)

Five parallel teams (E/S/B/F/T), disjoint file ownership, nothing committed by teams;
single integration commit. Design unchanged; no tips added; issues resolved essentially.

### A1 — zip-time DDL classification (report-only, per settled design)
- `folder_index_service.py` `scan_folder` classifies every file `file_class: "schema" | "script"`:
  `.ddl`/`.schema` extensions → schema; `.sql` → schema only when ALL top-level statements are
  CREATE TABLE/VIEW/MATERIALIZED VIEW/GRANT/COMMENT/ALTER TABLE; parse failure/empty → script
  (conservative).
- Schema files contribute `script_schemas` to `m_ws` / `schema_evidence_by_script` (so S4b can
  resolve cross-script owners) but NEVER pipeline counts (script_count), table_index/field_index,
  caches, L1/L2, or filter scopes. No upload endpoint, no annotation, no tips.
- Index response gains factual `schema_evidence: {present, tables, columns}`; frontend renders
  "Schema evidence: none — N unresolved may be unresolvable" / "Schema evidence: T tables, C
  columns" (3 index sites, `schema_evidence` state). No advice UI.
- Gate reality check: only 2/108 tpcds_qualified files classify as schema (tpcds.sql CREATE
  TABLE ×25, tpcds_ri.sql ALTER ×102); drop.sql/empty.sql/count.sql stay scripts. Honest gate =
  orphans/coverage unchanged (see sweep) + script_count 106.

### A3 — R6 field==table collision guard (extractor)
- `_register_column` S3 single-table branch + S1/Fix-B alias path: `lower(col) ==
  lower(visible_table)` → not attributed, `r6_collision += 1`, stays unresolved.
- `build_resolution_stats` emits `r6_collision` (S4a finalize + recorded). Tests:
  `test_s4_instrumentation.py` (case-insensitive, alias mirror, regressions).

### A2/A4/F1/G3 — closed by decision (no source edits)
- A2: fieldless-table UI treatment — schema evidence now available; no new UI. A4: tpcds 8 dim
  tables resolved by S4 Phase 2 (dbgen_version category-4 empty: only COUNT(*)/DELETE/DROP refs
  — legitimately no data flow). F1: static.bak.* / docker_image / tar.gz blobs removed from git
  index (0 tracked). G3: bare-table keying kept (conservative ambiguity) — Q3 closed.

### Remaining small items (each fix leaves a test)
- **C1** `l2_builder.py` (960 L): `_build_l2_graph` split into 13 named phases; byte-identity
  verified on 10/10 corpus combinations.
- **C2** `l1_builder.py` (920 L): two disk-cache passes merged into one (`_absorb_p4`);
  **B2 real bug**: `detect_role` clause 5 `\b{target_field}\b` regex → `sc.rsplit(".",1)[-1]
  == target_field` (6 false matches on tpcds q3/q42/q52 where target_field="item" matched table
  part "item.i_brand"); same fix in l2 `_target_field_sc`.
- **CW4**: l2_builder monolith documented in the phase names. **CW1/CW2**: all 41 bare `except
  Exception` sites triaged per-owner (benign sites commented).
- **C4a** extractor stats add `resolved`/`unresolved_count`/`coverage_pct` (additive, old keys
  kept) → **C4c** frontend `resolutionReport.js` prefers unified keys, legacy fallback kept.
- **F2** workspace DELETE: 400 malformed id / 404 valid-but-missing / 200 deleted
  (`is_valid_ws_id`). **F3/F4/F5** filter_service: COL_NAME-only rows dropped by design +
  `ignored_rows`/`ignored_tables`/`warning` in response; case folding at parse + every predicate
  site. **F6** case-mismatch hint block removed (tips forbidden).
- **E1/E2** frontend: drag recomputes from frozen offsets (delta machinery deleted);
  `fieldPositionsForTable`/`positionTableFields`; 7 dead client.js exports deleted;
  7 silent console.error sites surfaced.
- **CW10** `test_full_http_journey.py`: one TestClient journey (upload multi_workflow.zip →
  index → search expanded → L1 → L2 → DELETE). **G2** lineage SCHEMA directionality pinned
  comment + test. Known oddity flagged (not fixed): L2 `filtered_nodes` 8 > `total_nodes` 7 for
  step3 in that workspace.

### Tests & gates
- Backend **523 passed / 5 skipped** (was 495/5): +170 l1/l2 integration, +66 S4
  instrumentation, +200 S4b/A1 classification, +128 filter config, +49 orphan extractor, +new
  full-HTTP journey. Frontend **70 passed** (was 52) + build OK.
- Coverage sweep parity EXACT vs v3.3.133 baseline: tpcds 96.2% / 123 orphans; qualified 99.7% /
  9 orphans / script_count 106 (evidence preserved: schema_evidence bare 16 tables/94 cols,
  qualified 25 tables/429 cols); combined 99.9% / 8 orphans.
- Deployed v3.3.134, health OK. Version bumped in /VERSION + repo VERSION.

## target_deploy.sh version guard + logging (2026-08-06)
- **Stale-pieces incident**: v3.3.130 was deployed from a stale checkout — `checksums.md5`
  matched the stale pieces, so the target silently loaded the old image. No link existed between
  the committed image pieces and the repo VERSION.
- **Added `docker_image/RELEASE.txt` manifest** (`VERSION=`/`COMMIT=`/`BUILT=`), generated by
  `release.sh` in the export step (right after checksums) and committed together with the pieces.
- **`target_deploy.sh` guards**: pieces-vs-repo VERSION mismatch → fail-fast before deploy;
  optional `origin/main` fetch + compare catches stale checkouts; loaded-image VERSION verify
  with rollback; health-JSON version verify with rollback.
- **Logging**: deploy writes a timestamped `target_deploy.log` in the repo root (gitignored).
- `release.sh` and `target_deploy.sh` both syntax-checked (`bash -n`).

## R21 — Remove L1 script-info popup (v3.3.135, 2026-08-06)

- **Requirement change** (user report): the bottom-right L1 popup (label +
  "Variables:"/"Inputs:"/"Outputs:" lists, fed by single-click on script nodes)
  has no `max-height` — long input/output table lists grow it to cover most of
  the L1 panel. Requested: remove it (see REQUIREMENTS.md R21).
- **Implementation** (deletions only, 3 files):
  - `frontend/src/components/DataFlowGraph.jsx` (−22): props destructure lost
    `scriptInfo, onScriptInfoChange`; the `onTap` handler removed from the
    `useCytoscapeGraph` options (the hook guards `if (o.onTap)` — handler simply
    never registered); popup JSX block removed. `onDblTap` (L2 open),
    `onEdgeTap`, `onEdgeHover`, `onHoverEnter`/`onHoverLeave` (cursor) intact.
  - `frontend/src/DataFlowApp.jsx` (−3 net): `scriptInfo` state, 5
    `setScriptInfo(null)` reset sites, and props at the L1 render site removed;
    L2 render site never had them (verified byte-identical vs HEAD).
  - `frontend/src/styles/app.css` (−8): `.script-info-popup` + `.sip-header`
    rules removed; `.graph-canvas` sizing untouched (popup was an absolute
    overlay — no layout impact).
- **Verification**: two-team flow — Team A implemented, Team B ran adversarial
  regression review (9/9 PASS): diff scope exact, handlers intact, zero
  dangling references (grep across frontend/src, `*.bak` gitignored), 70
  frontend tests pass, `npm run build` OK, popup data consumed nowhere else
  (App.jsx/export.js read the analyze-API summary objects — separate channel).
- Deployed locally (static copy + restart), health `{"status":"ok","version":"3.3.135"}`.
- `docker_image/` pieces still v3.3.134 — `target_deploy.sh` version guard will
  fail fast on a v3.3.135 checkout until `release.sh` regenerates pieces
  (intended: deploy must follow review approval).

## R22 — L2 table dedup + data-flow-participation search (v3.3.136, 2026-08-06)

- **Issues (user report, repro script OCR-reconstructed → `samples/sql_sample_v1/`)**:
  a. same physical table parsed into multiple L2 nodes (4× `bdm_acc_loan_info`; 64
     table nodes for ~15 real tables); b. search `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE`
     matched the script although the field is never queried by it (`fallback` padding);
     c. L2 degraded to a 5-node / 0-edge skeleton with no explanation.
- **Implementation** (parallel teams, contract: `search_matched` bool on `_build_l2_graph`):
  - **Issue a** (`l2_builder.py` +101/−5): TABLE branch keys compound nodes by label —
    one keeper per physical table, `merged_original_ids` per node, field nodes dedup by
    (parent, label), new `_map_search_target_ids` phase re-points search highlights via
    `id_map`, merge-created self-loops dropped, `_assemble_output` strips internal keys.
    Extractor/cache untouched — merge runs per request on the cached graph.
  - **Issues b+c** (`dataflow_service.py`, `routers/dataflow.py`): `create_search` drops the
    `field_scripts | table_scripts` fallback union → `no_matches` + message when the field is
    queried by no script (or never under the searched table); `get_level2_graph` returns
    `search_matched: false` + message + FULL graph when the view's field is absent from the
    script; level1 endpoint now applies the R18 lineage filter; R17 diagnostic fixed via
    `_load_base_index` (base-absent → "not queried by any indexed script", never CSV blame).
  - **Frontend** (`DataFlowApp.jsx` +9 hunks, `app.css`): `applyL2Result` helper captures
    `search_matched === false` + message at all 4 L2 response sites; L2 banner renders inside
    `.inline-l2-graph` (now `position: relative`) reusing `.no-match-banner`; L1 no_matches
    banner guard dropped to render whenever `match_mode === "no_matches"` with the message.
- **Verification**: live API on repro workspace `e3bb7297c663`: unfiltered L2 64→54 table
  nodes, `bdm_acc_loan_info` 4→1, `ods_hub_lsacmsp` 4→1, 0 dangling, 0 leaked keys; search →
  `no_matches` + message; L2 → `search_matched: false` + full graph (378 nodes / 147 edges);
  control search `lending_ref` still `exact`. Backend **556 passed / 5 skipped** (was 523/5),
  frontend **70 passed** + build OK. Deployed v3.3.136, health OK.

## Code-review fixes M12–M15, L16, R21-1/2 (v3.3.136, 2026-08-06)

- **M12** (`folder_index_service.py`): S4b is now two-phase (plan → conflict-detect → apply);
  ≥2 plans with different owners (or plan owner ≠ existing extractor attribution) → field marked
  `ambiguous_fields`, revoked from prior owners (index cleared, back to UNRESOLVED),
  `resolution_stats["ambiguous"]` added and surfaced in the report.
- **M13** (`folder_index_service.py:826-895`): `_apply_s4b_cache_update` gates attribution on
  `v.get("context") in cand["contexts"]` (mirrors S4a); records without `contexts` keep the
  legacy any-context behavior.
- **M14** (`cache_keys.py`): `GRAPH_CACHE_PREFIX` `graph_3_2_15` → `graph_3_2_16` (invalidation
  bump — post-S4b analyses can't be served from pre-attribution caches).
- **M15** (`folder_index_service.py:554-557,895`): `_apply_s4b_cache_update` returns
  `n_attributed`; `by_strategy["schema"]` increments only when ≥1 var was actually attributed.
- **L16** (`variable_extractor_v2.py`): new `_is_as_keyword` (text "as" ∧ non-STRING);
  `_statement_anchor` head/stream filters type-aware — `'as'` inside a string literal is never
  the anchor (test `test_loc_anchor_skips_string_literal_as`: red before, green after).
- **R21-1/2**: 8 stale tracked `.bak*` files removed (`docker-compose.yml.bak`,
  `App.jsx.bak.20260723_122525`, `DataFlowApp.jsx.bak`, `DataFlowGraph.jsx.bak`,
  `useCytoscapeGraph.js.bak*` ×3, `graphStyles.js.bak` — all verified unreferenced, build
  clean); `.gitignore` += `*.bak.*`; REQUIREMENTS.md R21 criterion reworded.
- **Tests**: +5 S4b (M12 ×3, M13, M15 — mutation-verified), +1 L16, +6 L2 dedup,
  +8 sample_v1 repro; all scoped suites green, full suite 556 passed at integration.
- Follow-up (out of scope): extractor S4a `_finalize_schema_candidates` still increments
  `resolved_by["schema"]` unconditionally — same pattern as M15, worth mirroring later.

## R23 — Remove browser auto-restore (v3.3.137, 2026-08-06)

- **Requirement**: opening the service must start clean — no previous workspace/search
  auto-restored (was added in `bc07592` v3.3.131 + `cb58c28` v3.3.133 via `restoreViews.js`).
- **Fix**: `DataFlowApp.jsx` mount effect removed entirely (zero network calls on load);
  `LAST_SEARCH_KEY`/`loadLastSearch`/`saveLastSearch`/`clearLastSearch` and
  `uploadTokenRef` deleted; `restoreViews.js` + `restoreViews.test.js` removed; one-time
  `localStorage.removeItem('df_last_search_view')` purge for users of the old restore;
  `client.js` loses the now-unused `getWorkspaceInfo`/`scanWorkspace` wrappers.
- **Tests**: restoreViews.test.js (6) deleted; frontend **64 passed** (was 70) + build OK.

## R24 — Single-script folder shows L1 script node (v3.3.137, 2026-08-06)

- **Requirement**: a workspace with exactly one script must still show it in L1, clickable
  into L2 (test corpus `samples/sql_sample_v1/`).
- **Root cause**: two-step drop — `_build_l1_graph`'s `len(script_data) < 2` shortcut
  (`analyze_multiple_scripts` refuses <2 scripts) returned a bare script node, then the
  R18.1 disconnected-script pruning (`_filter_l1_by_lineage`) removed it → 0-node L1.
- **Fix**: `l1_builder.py:272-300` — single-script branch now runs `run_full_analysis` +
  `build_graph_data` + `_classify_tables` inline, builds the same `all_scripts` dict shape as
  `analyze_multiple_scripts`, and falls through to the shared pipeline (bare-node early return
  gone; `<2` guard lives inside the try → bad script degrades to fallback + diagnostic);
  `dataflow_service.py:293` — `_filter_l1_by_lineage` guards `len(script_ids) > 1 and
  disconnected_scripts:` so the only script is never pruned.
- **Tests**: +8 in `test_dataflow/test_single_script_l1.py` (single-script search L1 contains
  script node + flow tables; level1 endpoint parity; no_matches preserved (R22); views.json
  cache non-empty; R18.1 guard: 1-script keeps, 2-script prunes). Backend **564 passed /
  5 skipped** (was 556/5), frontend **64 passed** + build OK.
- **Verification**: live — fresh upload of `samples/sql_sample_v1/` (workspace
  `8f843283a9d8`): L1 = 7 nodes / 5 edges (script node + 4 tables + 2 fields), script node
  click → L2 loads; search on single-script workspace: script node present; no_matches
  message still shown for non-matching searches.

## B-series — L2 field explosion: root cause + solution design (audit 2026-08-06)

**Trigger**: workspace `8f843283a9d8`, script `BDM_ACC_LOAN_INFO_SUP_M.sql`, search
`bdm_acc_loan_info.lending_ref` → L2 shows 122 nodes / 78 field nodes. The relevance filter
works (full graph = 378), but the closure is over-inclusive. All measurements below are
in-container simulations (read-only; no source changes).

### Classification of the 78 fields (by entry mechanism)

1. **SUBSET "safety-net" bridges treated as lineage (~40 fields — dominant)**.
   `dependency_graph.py` Phase 7/8 (`:386-457`) emit SUBSET edges purely as connectivity
   padding (`_add_edge(..., "SUBSET", "BRIDGE")`) for layout stability — zero lineage
   semantics. `compute_field_lineage` (`lineage.py:221-223`, SUBSET ∈ `_BIDIR`) walks them
   like real edges. The first CTE `rollover_loan_info` (legitimately in R — it defines
   `lending_ref`) carries **54 SUBSET edges**; every bridged neighbor enters R: the second
   statement's constants (`'Y'`→STATUS, `COUNT(1)`→total_rows, `getdate()`→load_time,
   `NULL`→remarks, `''`→sub_src_system, table-name strings, rec_creat_dt_tm, object_domain,
   reserved_field1–20 producers), p2's full 12-column set, label-subquery keys, partition
   columns (data_dt/p_dt ×6). Verified: `STATUS` (type literal) and `total_rows` (aggregate)
   connect to `rollover_loan_info` ONLY via SUBSET + SCHEMA→output.
2. **Output-node wholesale pull (54 = 27 unique × 2)**. The `⟐ output` qo node merges both
   INSERT statements' column lists (R22 one-node-per-physical-table). Each of the 27 renders
   twice — column node + ` ↻` expression-producer node — because the dedup key
   `(parent_table_id, label)` (l2_builder.py:347-352, 389-394) never collides: the producer
   is stamped ` ↻` (l2_builder.py:377) so `STATUS` ≠ `STATUS ↻`.
3. **Genuine flow (~20-25)**: seed, p2's 6 CONCAT key parts, p4's iiapty/iiblno,
   accu.vlookup_key_value, p6.lending_ref, output columns with real producers. Correct.
4. **Partition/filter keys** (data_dt/p_dt ×6) — by-design FILTER rule, noisy but intended.
5. **Parentless display (15)** — p2's columns lack `source_tables` → float as `<NOPARENT>`.

### Measured closure variants (seed `lending_ref`; R = lineage set size)

| Variant | R | Result |
|---------|---|--------|
| Current | 112 | 122 L2 nodes / 78 fields |
| Skip all SUBSET | 43 | over-prunes — loses p2 join keys & label keys |
| Skip SUBSET + JOIN always-bidir | 125 | over-pulls — internal subquery cols (a.*/b.*/c.*) |
| Skip SUBSET + JOIN expr-partners-only | 43 | no-op — JOIN edges are column↔**vtable** (33 col↔vtable, 29 col↔cte), never expressions |
| Skip SUBSET into constants only | 105 | −7 constants; keeps all legit nodes — ceiling ~−14 output fields |

**Key structural finding**: JOIN conditions are modeled as `column ↔ virtual_table` edges —
the join-key expression (`CONCAT(p2.poctcd,…) = p1.lending_ref`) has **no node**. No closure
rule can separate p2's 6 key columns from its 6 filter columns without an extractor change.

### Solution (3 phases)

**Phase 1 — closure stopgap (lineage.py, ~5 lines, ships alone)**: skip SUBSET edges whose
other endpoint is a constant producer (literal/aggregate/window/function-call types).
Measured 112→105, output fields 78→~64 (9 constant columns + 9 ↻ twins drop).

**Phase 2 — join-key modeling (dependency_graph.py Phase 6 — the real fix)**:
materialize the join-key expression as a node (CONCAT/RPAD/|| → expression node with REF
edges to its operand columns; JOIN edge points at the expression, not the vtable). Then:
exclude SUBSET from the closure entirely (112→43), and let JOIN admit expression partners
(recover: p2's 6 CONCAT parts — not the 6 filter-only cols podcg/poapty/poofla/pofdtt/
pocnlm/poclin — p4's iiapty/iiblno, accu.vlookup_key_value, p6/rollover chain). Estimated
R ≈ 60-70 → **L2 fields ≈ 25-35** = the true contributing set. Constants and the second
statement's columns have no production path → gone; a.*/b.*/c.* never enter. Side benefit:
join keys become visible expression nodes in the full graph.

**Phase 3 — renderer presentation (l2_builder.py)**:
- B4: dedup on the undecorated label (strip ` ↻` before the `(parent, label)` key) →
  column+producer pairs merge, output fields halve (−27).
- B3: parent-resolution fallback — when `source_tables` is empty, parent via the column's
  SCHEMA-edge table neighbor → p2's columns nest under `ods_hub_lsacmsp` instead of floating.
- B5: sanitize virtual-table labels — drop `⟐`/`}` path garbage; name `query_output` nodes
  after their target table.

### Regression test plan (samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql, search `lending_ref`)
- L2 filtered field count ≤ ~35 (Phase 2) or ≤ ~64 (Phase 1 only).
- Absent: STATUS, total_rows, load_time, remarks, table_name, job_name, sub_src_system,
  rec_creat_dt_tm, object_domain; contract_no/acct_no/product_code/branch_code_sk; a.*/b.*/c.*.
- Present + parented: p1.lending_ref, p2's 6 CONCAT parts (poctcd/pogmab/poacb/poacs/poacx/
  podtao), p4.iiapty/iiblno, accu.vlookup_key_value, output lending_ref.
- No ` ↻` twins, no `⟐`/`}`-mangled labels, no parentless fields.

## C-series — Code-review round-2: team-verified solutions (wiki/CODE_REVIEW_2026-08-06.md, 2026-08-06)

Verdicts from the 4-agent argumentation round **plus a 3-agent code-verification team**
(each issue checked against HEAD with file:line evidence). Trivial issues dropped below;
valuable ones kept with refined, code-grounded solutions.

| ID | Sev | Team verdict | Keep? |
|----|-----|--------------|-------|
| P1-1 | High | confirm, solution confirmed | **keep** |
| P2-2 | Med | confirm, + 1 missed miss-path | **keep (refined)** |
| P2-3 | Med | confirm, refinement needed | **keep (refined)** |
| P2-4 | Med | confirm, **trivial** (no consumer) | drop → 3-line note under C-2 |
| P2-5 | Med | confirm (stronger), refinement needed | **keep (refined)** |
| P2-6 | Med | **trivial** — half already covered | drop → residual-gap note |
| P2-7 | Med | confirm, refinement needed (reset guard) | **keep (refined)** |
| P3-8 | Low | confirm, **trivial** (stderr mirror, tiny race) | drop → note |
| P3-9 | Low | confirm, **root cause is extractor, not l2_builder** | **keep (re-scoped)** |
| P3-10 | Low | partial, (a) real (b) rephrase (c) no-op | **keep (refined)** |
| P3-11 | Low | confirm, **trivial** (cosmetic) | drop → note |
| P3-12 | Low | confirm, **trivial** (diagnostic nicety) | drop → note |
| P3-13 | Low | partial — 3+ parses real; `expr.start/end` fix **impossible** | **keep (refined)** |
| ENV-1 | — | refuted again (564 pass/5 skip, 7.88s; no hang) | drop (closed) |
| ENV-2 | — | sound, must track C-9 re-scope | **keep (refined)** |

### C-1 (P1-1, High) — CTAS `.sql` classified as schema — KEEP
- **Fix confirmed** (`folder_index_service.py:44-69`, kind check `:55`): in `classify_sql_text`,
  before the kind check — `if isinstance(stmt, exp.Create) and stmt.args.get("kind") == "TABLE"
  and stmt.args.get("expression") is not None: return "script"`. Plain CT / `LIKE` keep
  `expression=None` → schema; VIEW/MATVIEW untouched; mixed files return "script" at the first
  data statement. S4b evidence preserved (the file now flows through `run_full_analysis` whose
  `script_schemas` merge into `m_ws`).
- **Test**: +2 classifier tests (CTAS→script, plain CT→schema); regression: CTAS body fields
  appear in search/L1/L2.

### C-2 (P2-2, Medium) — S4b-mutated analysis caches vs stale graph caches — KEEP (refined)
- **Confirmed**: index-time graph precompute (`folder_index_service.py:315-342`, write
  `:327-330`) runs **before** the S4b apply loop (`:535-557`), which mutates only the analysis
  cache (`:826-895`) → every L2 cache-hit path (`dataflow_service.py:322-331`,
  `l2_builder.py:90-120`) serves pre-S4b graphs; miss paths re-run `run_full_analysis` which
  cannot reproduce index-time S4b attribution.
- **Fix**: (a) after the S4b apply loop, delete every `{GRAPH_CACHE_PREFIX}_*.json` (rebuild
  on demand); (b) **both** miss paths must build from the S4b-mutated analysis cache when
  present — `l2_builder.py:108` **and** `get_level2_graph`'s own parallel miss path
  (`dataflow_service.py:339-346`; missed by the review — this path also never writes the
  graph cache it builds). Cache keys align (`md5(rel_path+sql_text)` = `md5(script_name+
  sql_text)`). New miss-branch writes must stamp `format_version = 3` (`l2_builder.py:99-101`
  warns otherwise). Bump `GRAPH_CACHE_PREFIX` once (3_2_17).
- **Team-found gap (divergence exists at HEAD today)**: `l1_builder.py:461-482` already reads
  the post-S4b analysis caches while every L2 path sees pre-S4b graphs. Acceptance must
  assert **L1/L2 agreement on `source_tables`**, not just L2 behavior.
- **Hardening note (from P2-4, dropped as trivial)**: persisted `resolved_by["schema"] += 1`
  + unresolved drop (`folder_index_service.py:872-879`) run with no `n_attributed` gate (M13
  context mismatch → `n_attributed=0` yet counters mutate). No consumer at HEAD, but becomes
  load-bearing once the analysis cache is the L2 source → gate on `n_attributed > 0`
  (mirror `:554-556`); `schema_candidates` removal (`:880-888`) stays unconditional.

### C-3 (P2-3, Medium) — S4b revocation never touches analysis/graph caches — KEEP (refined)
- **Confirmed**: revoke (`folder_index_service.py:523-531`) mutates only in-memory
  field_index/table_index; caches written pre-revoke (`:254`) and prior-run S4b caches
  (`:891-892`) keep the revoked attribution. `l1_builder.py:461-482` consumes analysis caches
  today → revoked ownership leaks into **L1 lineage at HEAD already**.
- **Fix**: `_revoke_s4b_cache_update(cache, field, owner)` mirroring `_apply_s4b_cache_update`:
  clear `source_tables` on matching vars; re-add to `rs["unresolved"]` (membership guard);
  drop `resolved_by["schema"]` (floor 0); remove the `schema_candidates` entry. Call it in the
  ambiguous-fields loop with: (a) snapshot `_fdata["tables"]` **before** `.clear()` (`:531`)
  as the owners; (b) use `_fdata["scripts"]` for rel_paths; (c) **handle the cross-run case** —
  `if not _fdata: continue` (`:525-526`) skips exactly prior-run-cache attribution with an
  empty current-run index, where revocation matters most (iterate caches directly for fields
  not in the current field_index); (d) derive the graph-cache key from the analysis-cache
  name (analysis_ → `GRAPH_CACHE_PREFIX` swap) — no file re-read.
- **Test**: ambiguous-field fixture → L1 and L2 show no `source_tables=[old_owner]`;
  `resolution_stats` consistent.

### C-5 (P2-5, Medium) — SELECT * / expression-only references invisible to search — KEEP (refined)
- **Confirmed, stronger than the review states**: `_expand_star_columns`
  (`variable_extractor_v2.py:1385-1401`) deliberately records nothing for unqualified stars
  → `SELECT * FROM t` / `INSERT INTO x SELECT * FROM t` produce zero field-index entries →
  `create_search` returns a silent "not queried — no data flow" verdict for scripts that DO
  query the field.
- **Fix** (index-time star expansion, precise mechanics): structure is
  `field_index[field] = {tables, scripts}` (`folder_index_service.py:376-385`) — expansion
  writes `field_index[c]["tables"].add(t)`, `["scripts"].add(rel_path)`,
  `table_index[t]["fields"].add(c)`. Must be a **post-loop pass** (after ~`:426`) but before
  `pair_index` construction (`:564-573`). Star **detection** needs a per-script parse/text
  scan (no analysis output records unqualified-star projections) — reuse the C-13 single
  parse. No schema evidence → no expansion, no padding (BE2 intact: `no_matches`).
- **Test**: `INSERT INTO x SELECT * FROM orders` + orders schema → search `orders.order_id`
  finds the script; without schema → `no_matches` message.

### C-7 (P2-7, Medium) — target_deploy.sh guard edges — KEEP (refined)
- **Confirmed**: missing `RELEASE.txt` is warn-only (`target_deploy.sh:62-64`); the stale
  block (`:73-83`) has no fetch-success or ahead/diverged guard — fetch failure swallowed by
  `|| true`, stale local `origin/main` ref still yields a value, and the `reset --hard
  origin/main` advice (`:82`) prints whenever `REMOTE_VERSION != REPO_VERSION` — including
  **local-ahead** (would discard unpushed commits).
- **Fix**: (a) missing `RELEASE.txt` → red error + `exit 1`; (b) reset advice only when the
  fetch succeeded **and** `rev-list --count HEAD..origin/main > 0` **and** `rev-list --count
  origin/main..HEAD == 0` (strictly behind — the review's own ">0" is NOT enough: a diverged
  branch also yields >0 and must never trigger reset). Otherwise warn "local ahead/diverged
  or origin unreachable — resolve manually".
- **Test**: manual — no RELEASE.txt → exit 1; behind → advice; ahead/diverged → no advice.

### C-9 (P3-9, Low) — same-name computed expressions collapse across statements — KEEP (re-scoped)
- **Team finding: root cause is the extractor, not l2_builder.** `_add` dedups on
  `key = (name, var_type.value, context)` (`variable_extractor_v2.py:596-603`) and every
  top-level statement is walked with context `"TOP"` (`process_statement(statement, "TOP")`
  at `:417`) → `SELECT SUM(x) AS total…; SELECT SUM(y) AS total…` returns None for the second
  `total` — one aggregate var, one node; no l2_builder key can ever produce two nodes.
- **Fix**: give each top-level statement a distinct context (`TOP{stmt_idx}` at `:417`) or add
  a stmt index to the `_add` key; carry `stmt_idx` into the graph node JSON
  (`graph_service.build_graph_data`); then the L2 key `(parent_table_id, undecorated_label,
  stmt_idx)` (`l2_builder.py:347/389`) composes with B-series B4 (same-statement
  column+producer twins still merge via shared stmt_idx). Fix the stale comment at `:444`
  (the key includes context). Do NOT cite `_statement_anchor` as the index source — it
  returns a **line**, not an index.
- **Conflict to resolve deliberately**: R22 field-dedup acceptance
  `test_merged_table_fields_dedup` (`test_l2_table_dedup.py:110-130`) asserts one field per
  name under a keeper — a stmt_idx key can create two same-name nodes under one keeper
  (two statements over the same physical table) → relax/re-scope that assertion with a
  documented note (see ENV-2).
- **Test**: one script, two statements each `SUM(x) AS total` → two nodes (previously one);
  `total` + `total ↻` still one node (B4).

### C-10 (P3-10, Low) — not_in_flow double analysis + highlight flood — KEEP (refined)
- (a) **Confirmed**: miss path writes only `schemas_cache_path` (`dataflow_service.py:349`),
  never the graph cache → 2 full analyses on cold cache. Fix: write `graph_cache_path` with
  `format_version = 3` in the miss else-branch (`:337-349`), mirroring `l2_builder.py:113-114`.
  (Serves C-2(b) too.)
- (b) **Rephrase**: the not_in_flow rebuild (`:370`) is **already a cache hit** (the first
  `_build_l2_graph` call wrote it); the "second analysis" is the internal miss inside that
  first call — (a) removes it.
- (c) **Drop**: the highlight flood is deliberate — `highlight_ids` = all `filtered` node ids
  (`:374-377`), full graph in the not-in-flow branch (`:371`). If unwanted, fix the
  construction, not `_compute_highlight_ranges` (which already skips ids missing from
  `line_map`, `l2_builder.py:45-66`).
- **Test**: `run_full_analysis` counter → exactly 1 call on cold cache + not-in-flow script.

### C-13 (P3-13, Low) — A1 re-parses + _statement_anchor cost — KEEP (refined)
- **Confirmed, count corrected**: 3+ parses per script at index time — scan_folder classify
  (`folder_index_service.py:143`), loop classify (`:236`), `run_full_analysis`
  (`variable_extractor_v2.py:382`) + 2 fallback parses (`:394`, `:404`); schema files parsed
  again in `_process_schema_evidence` (`folder_index_service.py:767`).
- **Fix**: parse once per script; `classify_sql_text` takes an optional `preparsed`. Must
  cover the `:143` scan site too. **Do NOT reuse the extractor's `clean_sql` parse** — a
  `SET x=1; CREATE TABLE t(a INT)` file is "script" today but would flip to "schema" after
  SET-stripping, and the dialect differs (classify `read="mysql"`; extractor
  `_detect_dialect`).
- **`_statement_anchor`** (`variable_extractor_v2.py:516-577`, not `481-544` — that's
  `_find_position`): per-anchor cost is O(n) (rebuilds the AS-filtered token list `:556-557`
  + linear 4-token head scan `:563-575`), O(S·n) total. **The proposed `expr.start/expr.end`
  fix is impossible**: container sqlglot 30.12.0 sets no token offsets on AST nodes
  (verified empirically), and offsets would be shifted anyway (extractor parses stripped
  `clean_sql` while `_tokens` come from the original text). Fix: cache the once-filtered
  token list + a token-position index keyed by first-token text; keep the subsequence match
  as fallback; `_anchor_cache` stays.

### ENV-2 — deliberate behaviors: keep regression suites, track C-9 — KEEP (refined)
- Keep the R22/R24 suites (`l2_table_dedup` 6, single-script L1 8, create_search no_matches).
- Must track C-9's re-scope: the collapse lives in the extractor `_add` key
  (`variable_extractor_v2.py:596-603`), so the fix spans extractor + graph JSON + L2 key
  (an extractor-only fix would re-merge at `l2_builder.py:347/389`).
- "One node per physical table" stays table-level true, but the **field-level** R22
  acceptance (`test_merged_table_fields_dedup`, `test_l2_table_dedup.py:110-130`) conflicts
  with stmt_idx keys → document the deliberate relaxation alongside C-9.

---

### Dropped as trivial (with one-line rationale + where the fix lives if ever wanted)

- **P2-4** — counter drift only, no consumer of persisted `resolution_stats` at HEAD →
  folded as the 3-line hardening note under C-2.
- **P2-6** — test-only; the not-in-flow `search_matched:false` acceptance is already asserted
  (`test_dataflow/test_search.py:209-233`, `test_buggy_detection.py:28-43`) and
  `@testing-library/react`/`jest-dom` are already in `frontend/package.json:22-23`. Residual
  real gap: a `get_level2_graph` test on `samples/sql_sample_v1/` (filtered < full) + banner
  component tests — add when convenient.
- **P3-8** — loss window is only the live-stream connect race; every message also goes to
  stderr (`logger.py:29`) and the queue registers before analysis in the normal flow. If ever
  wanted: per-ws bounded deque (maxlen 200) drained by `register_queue` (`logger.py:56-67`).
- **P3-11** — cosmetic; the stale banner's text ("showing the full script graph") stays
  factually true while the full graph IS shown (`DataFlowApp.jsx:332-334` bypasses
  `applyL2Result`; banner at `:551` and `:617-620` — the review's `:626`/`:411-416` citations
  are wrong). If ever wanted: gate `:551` on `!loading`; route the cached branch through
  `applyL2Result({...(l2Result||{}), graph: l2FullGraph})` (a bare `{graph}` would clobber
  `l2Result` and break the Show-All button label at `:607-609`).
- **P3-12** — diagnostic nicety only. If ever wanted: casefold scan at
  `routers/dataflow.py:140-142`, pass the variant name into `_search_diagnostic_values`
  (`:67-69`, `:160-162`); search semantics unchanged.
- **ENV-1** — closed: 564 passed / 5 skipped in 7.88s in-container; `test_filter_config.py`
  = 54 tests, 1.05s, no hang; `pytest-timeout` not installed (the `--timeout` flag errors);
  review nits: "530 def test_" is wrong (438 across 27 files) and the `test_services/`
  subpath does not exist (suite is flat).

---

### ✅ B-series IMPLEMENTED + VERIFIED (v3.3.138, 2026-08-06 — parallel team)

All 3 phases shipped in one round (Team 1: extractor/lineage/l2; Team 2: index pipeline;
Team 3: deploy guard), 62 new backend tests, suites green (626 passed / 5 skipped).

- **Phase 1 — SUBSET never walkable** (`lineage.py` `EDGE_SEMANTICS`): `SUBSET` →
  `{propagates_value: False, always_bidir: False}` — removed from `_BIDIR`. The "safety-net
  bridge" no longer contributes lineage, so constants (`STATUS`, `total_rows`, `load_time`,
  `remarks`, …), the second statement's columns, label-subquery keys, and partition columns
  (data_dt/p_dt) all drop out of the closure.
- **Phase 2 — join-key materialization** (`variable_extractor_v2.py`
  `_walk_join_key_expressions`): CONCAT/RPAD/`||` expressions in JOIN ON become EXPRESSION
  vars (`defined_in="JOIN ON"`); `dependency_graph.py` Phase 6b emits JOIN edges from the
  other side → expression node; `_classify_relationship` → REF for JOIN ON expression
  targets; lineage JOIN rule admits expression neighbors unconditionally (vtables/ctes/
  plain columns keep production evidence). Recovered: p2's 6 CONCAT parts
  (poctcd/pogmab/poacb/poacs/poacx/podtao), p4's iiapty/iiblno, the p1/p2/p3/p4/p6 join-key
  operands. Filter-only columns (podcg/poapty/poofla/pofdtt/pocnlm/poclin) stay out.
- **Phase 3 — presentation** (`l2_builder.py`): B4 dedup on undecorated label
  (`(parent_table_id, undecorated_label, stmt_idx)`) — the 27 `↻` twins collapse; B3
  `_resolve_scope_parent` context-segment walk parents fields (CTE{…}/TOP{idx}:… segments);
  B5 label/table_name split — display strips `⟐ `, `table_name` keeps the raw sentinel.

**Verified on workspace `8f843283a9d8` (BDM_ACC_LOAN_INFO_SUP_M.sql, `lending_ref`):
L2 fields 78 → 12** (predicted band 25-35 was optimistic on the low side — the old 78 came
entirely from SUBSET bridges; strict production semantics legitimately excludes loan_final
computed outputs and NULL constants). Acceptance: absent = STATUS/total_rows/load_time/
remarks/contract_no/acct_no/product_code/branch_code_sk/a.*/b.*/c.*; present+parented =
p1.lending_ref (×2 — legitimate C-9 split, see below), p2's 6 CONCAT parts, p4's
iiapty/iiblno, output lending_ref; no `↻` twins, no `⟐`/`}`-mangled labels, no parentless
fields, no constant literals.

**Two documented follow-up observations (by-design, no code change)**:
1. **DML edges absent from filtered L2** — the 16 raw DML edges are `relationship`-keyed
   (pre-existing serialization; `edge_type` null) and target the *output* tables
   (`bdm_acc_loan_info_sup`, `rrcdm_job_log_exec_par`), never the searched table; their
   producers are reachable only via the now-severed SUBSET bridge, so the DML edges drop
   with the producers. Consequence of Phase 1, not a regression. If a DML write INTO the
   searched table is ever required, DML forward (col→table) is already walked
   unconditionally (`lineage.py:229-239`) — the producer needs a real production path.
2. **Comparison-side join keys render edge-less** — `p1.lending_ref` (TOP0) and
   `p1.lending_ref` (CTE{rollover_loan_info}/subq1/subq) are two distinct raw nodes
   (different contexts, `stmt_idx` 0 vs None → the C-9 split keeps them apart; verified NOT
   a B4 twin — different ids, never a `↻`-stamped duplicate). Both are JOIN ON operands
   whose own column source is only SCHEMA-reachable, so they show as fields under p1 with
   no edges. Cosmetic; the join-key chain itself (operands → CONCAT expression) is fully
   wired.

**Existing workspaces need re-index after deploy** for full B-series/C-9 fixes — old
analysis caches (pre-fix format) produce partial results (probe showed 1 field before
re-index, 12 after).

---

### ✅ C-series IMPLEMENTED + VERIFIED (v3.3.138, 2026-08-06 — parallel team)

- **C-1 CTAS → script** (`folder_index_service.py` `classify_sql_text`): kind==TABLE +
  expression not None → "script" before the `_SCHEMA_CREATE_KINDS` check. +classifier tests.
- **C-2 S4b-consistent caches**: index now deletes ALL `graph_3_*.json` after the S4b pass
  (unconditional, `_invalidate_graph_caches`); the index-time graph precompute was REMOVED
  (it wrote pre-S4b graphs that C-2 immediately deleted — double analysis per script);
  `precomputed_count` stays 0 in responses; the L2 miss path prefers the S4b-mutated
  `analysis_{cache_key}.json` and WRITES graph caches (format_version 3); L1/L2 agree on
  post-S4b `source_tables`; `GRAPH_CACHE_PREFIX` → `graph_3_2_17`.
- **C-3 revocation mirror** (`_revoke_s4b_cache_update`): `schema_candidates` cleanup +
  cached graph invalidation mirrored into the revoke path.
- **C-5 post-loop star expansion**: `SELECT a.*` is expanded from the schema evidence of
  its source tables AFTER the main resolution loop (no per-row evidence lookups).
- **C-7 deploy guard** (`target_deploy.sh`): missing RELEASE.txt → red ERROR + exit 1;
  strictly-behind (fetch OK ∧ behind>0 ∧ ahead==0) → reset advice + exit 1; diverged /
  ahead / fetch-failed → YELLOW + continue. `bash -n` verified.
- **C-9 per-statement dedup**: extractor contexts `TOP` → `TOP{stmt_idx}` (CTE walk threads
  the enclosing context); `stmt_idx` lands in node data (`graph_service._stmt_idx_of`);
  L2 dedup key = `(parent_table_id, undecorated_label, stmt_idx)`. Same-named vars in
  different statements no longer collapse. 18 tests pinning `"TOP"`/`"TOP0"`-style contexts
  updated to the new contract (verified not regressions); `test_l2_table_dedup.py`
  comment-relaxed for stmt_idx keys as C-9 specified.
- **C-10 + C-2(b) merged miss paths**: `dataflow_service.py` and `l2_builder._load_or_build_graph`
  both prefer analysis caches before re-analysis.
- **C-13 single parse + anchor fix**: `parse_by_script`/`parsed_cache` — one parse per script
  across the index pipeline; token-position index for `_statement_anchor` (sqlglot sets no
  `expr.start/end`, so line offsets are reconstructed from tokens). **C-13(b) is the
  P3-13(b) impossibility made practical** — `expr.start/end` still doesn't exist, the
  statement anchor is now derived from the token stream instead.
- **ENV-2 kept**: C-9 re-scope tracked through the whole round (this entry + B-series
  observation 2 document the stmt_idx consequence).

**Verification**: backend 626 passed / 5 skipped (baseline 564 → +62 net new), frontend 64
passed. All C-series items have dedicated tests (`test_c_index_pipeline.py` 32 tests:
TestC1CtasClassification, TestC2GraphCacheInvalidation, TestC3RevocationMirror,
TestC5StarExpansion, TestC13SingleParse).

---

## Round-4 review verdicts — wiki/CODE_REVIEW_2026-08-06.md (2026-08-06, analyzed vs HEAD 7982efe)

External review (Codex, 3 sub-agents) of the C/B-series implementation. It reviewed a
**mid-flight working tree** (before the integration test edits), so several headline
claims are stale at HEAD. 2-team verification (index pipeline + L2/lineage) with live
probes. **Decision (user): document only — no code changes this round.**

### Stale / wrong at HEAD (do NOT act on)

| Claim | Reality |
|---|---|
| "Working tree is RED — ≥5 regressions" (test_l1_l2_integration 3❌, test_s4b_resolution 2❌, test_c_index_pipeline "hangs") | All pass at HEAD: full suite 626 passed / 5 skipped; the 3 files pass 40/40. The "hang" is the reviewer's sandbox Python 3.14 (`asyncio.to_thread`), acknowledged as environmental in the review itself |
| "C-9/C-2(b)/C-10 have zero real automated coverage" (test_l2_table_dedup.py:133 references nonexistent test_b_series_c9.py) | Substance exists: `test_b_series_l2.py` — C-9 `test_c9_per_statement_dedup:170` / `test_c9_same_statement_still_merges:191`, C-10 `test_c10_miss_path_writes_graph_cache:212`, C-2(b) `test_c2b_analysis_cache_preferred:241,:292`. The :133 reference is a dangling comment |
| "4 `total` fields in a 2-statement mini-script" (C-9-vs-B-series conflict) | Not reproducible: `SELECT SUM(x) AS total FROM t1; SELECT SUM(y) AS total FROM t2;` → exactly 2 vars (TOP0/TOP1) — the correct C-9 contract. The 2 `lending_ref` fields under p1 are the documented legitimate split (different statements), 12 fields vs 78 preserved |
| "B5 breaks the pinned `⟐ output` renderer contract" | False: frontend has zero `⟐` references; the pinned tests assert via `table_name` (preserved by the label/table_name split); test_l1_l2_integration passes 10/10 |
| "C-3 shared/global `ul` guard → revoking 2 scripts decrements only the first cache" | False at HEAD: `_revoke_s4b_cache_update`/`_apply_s4b_cache_update` load each cache's own `unresolved` per script (`folder_index_service.py:1158-1160`, :1087-1090). Only the deleted-script cross-run sweep gap survives — latent, no consumer |
| "`accu.vlookup_key_value` absent from R — false negative of the global SUBSET exclusion" | Wrong causation: with SUBSET patched walkable at runtime, the node is STILL not admitted — it is excluded by the conditional-JOIN/SCHEMA-forward production rules (`lineage.py:256-261, 276-281`), not by SUBSET. No false negative on this sample |

### Real findings (documented for later; suggested fixes not applied)

1. **C-5↔C-3 ordering — star expansion can resurrect revoked/ambiguous fields**
   Star expansion (`folder_index_service.py:748-769`) runs after S4b revocation (:675-698)
   with NO ambiguity filter (only `_star_seen` dedup + `_evidence_columns` non-None). A
   `SELECT *` over a table whose m_ws evidence includes a revoked/ambiguous field re-adds
   the table attribution to `field_index`/`pair_index` — breaches the never-guess
   invariant and drops the field from `orphan_fields` (:810-813). Trigger needs a real
   script with that shape; unverified in the sample workspace.
   *Future fix*: exclude `extractor_unresolved`/`resolution_stats["ambiguous"]` fields
   from `_star_from_tables` expansion (small, ~5 lines).
2. **B3 — wrong-instance parenting for same-named derived tables**
   `_resolve_scope_parent` (l2_builder.py:208-243) plus first-match-wins loops (:355-388)
   land join-key fields under the FIRST same-named table node: `poctcd…podtao` (raw ctx
   `CTE{loan_final}`) parent under the rollover-CTE p2 alias (ctx
   `CTE{rollover_loan_info}/subq1/subq:join:p2`); the TOP0 `lending_ref` lands under the
   rollover p1. Rule 1 (exact context match) can't fire for derived tables because JOIN ON
   columns register in the ENCLOSING scope. Unfiltered graph: 7 nodes display `p2`
   (4 alias + 3 label-stripped) — B5 display collision.
   *Future fix*: score candidates by scope-distance (e.g. prefer a table whose own
   `context` is a suffix of the field's `defined_in` scope) instead of first-match.
3. **C-4 — apply-side persisted counter ungated**
   `_apply_s4b_cache_update` (`folder_index_service.py:1087-1094`) moves
   `resolved_by["schema"] += 1` + unresolved-drop on `field in ul` only — no
   `n_attributed > 0` gate (revoke side :1164 IS gated). Latent: cached
   `resolution_stats` has zero consumers (index response stats are in-memory, caches
   rewritten every run) — the review's "load-bearing" escalation is wrong, but the gate
   is 3 lines if the caches ever become the stats source.
4. **RELEASE.txt stale — deploy blocked**
   `docker_image/RELEASE.txt` = 3.3.134/2babb12 vs repo VERSION 3.3.138/7982efe →
   `target_deploy.sh` exits 1 (by design, C-7). Regenerate the manifest at deploy time.
5. **2/8 JOIN ON expressions unpaired** (pairing order-dependent,
   `variable_extractor_v2.py:1095-1100` exact name+context match) — zero lineage impact
   (JOIN edge via partner side; expression admission direction-independent,
   `lineage.py:273-274`). Cosmetic for now.
6. **Trivial nits**: `variable_extractor_v2.py:448` `_seen` annotation still
   `set[tuple[str,str]]` (keys now 3-tuples); `test_l2_table_dedup.py:133` dangling
   `test_b_series_c9.py` reference. 1-line each.

---

## Consolidated review-advice ledger — rounds 3 + 4 merged (2026-08-06)

Every advice item from CODE_REVIEW_2026-08-06.md (round 3 = C-series design review,
round 4 = implementation review) mapped to its final status. Rounds analyzed by parallel
teams against HEAD; verdicts merged here.

### Round-3 items (C-series design review) → final status

| Item | Verdict | Final status |
|---|---|---|
| P1-1 CTAS→script | keep | ✅ **C-1 implemented** (v3.3.138, `classify_sql_text` kind+expression check) + tests |
| P2-2 graph cache vs S4b | keep (refined) | ✅ **C-2 implemented** — index precompute removed, post-S4b cache invalidation, miss paths prefer analysis caches, prefix 3_2_17. Round-4: two C-2(a) test re-scopes done during integration (review's own recommendation #2) |
| P2-3 S4b revocation vs caches | keep (refined) | ✅ **C-3 implemented** (`_revoke_s4b_cache_update`). Round-4: "shared global ul" premise FALSE — guards are per-cache at HEAD; only deleted-script sweep gap survives (latent) |
| P2-4 counter drift | drop (trivial) | ⏸ Re-opened by round-4 as **C-4**: apply-side `resolved_by["schema"]` gate CONFIRMED missing (`folder_index_service.py:1087-1094`) but **latent** — cached stats have zero consumers. Documented, no code |
| P2-5 SELECT * indexing | keep (refined) | ✅ **C-5 implemented** (post-loop star expansion) + round-4: **C-5↔C-3 ordering gap CONFIRMED** (star pass post-revocation, no ambiguity filter — resurrection mechanism real, trigger needs specific script shape). Documented for later fix |
| P2-6 frontend coverage | drop | ⏸ Residual gap noted (get_level2_graph test + banner tests "when convenient") |
| P2-7 deploy guard | keep (refined) | ✅ **C-7 implemented** (RELEASE.txt fail-fast + reset-advice guard) + round-4: `docker_image/RELEASE.txt` still 3.3.134 vs repo 3.3.138 → deploy blocks until regenerated (documented) |
| P3-8 logger race | drop | ⏸ Note only (per-ws bounded deque if ever wanted) |
| P3-9 l2 dedup over-merge | keep (re-scoped) | ✅ **C-9 implemented** (per-statement dedup `(parent, undecorated_label, stmt_idx)`). Round-4: 2 `lending_ref` under p1 = legitimate split; "4 `total`" claim NOT reproducible (probe → 2, correct) |
| P3-10 double analysis | keep (refined) | ✅ **C-10 implemented** (miss path writes graph cache, format_version 3) |
| P3-11 banner flash | drop (cosmetic) | ⏸ Note only |
| P3-12 case-variant suggestion | drop (diagnostic nicety) | ⏸ Note only |
| P3-13 re-parse + anchor | keep (refined) | ✅ **C-13(a) single parse + C-13(b) token-position anchor** implemented |
| ENV-1 test env | drop (closed) | ⏸ Sandbox-only; full suite green in-container |
| ENV-2 deliberate behavior | keep | ✅ Tracked through C-9/B-series; consequences documented |

### Round-4 items (implementation review) → final status

| Claim | Verdict | Status |
|---|---|---|
| "Working tree RED — ≥5 regressions" | **STALE-FALSE** | All pass at HEAD: 626/5; the 3 named files 40/40; test_c_index_pipeline "hang" = reviewer sandbox Python 3.14 |
| "C-9/C-2(b)/C-10 zero coverage" | **FALSE** | Covered in `test_b_series_l2.py` (:170/:191/:212/:241/:292); dangling `test_b_series_c9.py` ref is cosmetic |
| "4 `total` fields (C-9-vs-B conflict)" | **NOT REPRODUCIBLE** | Probe → 2 (correct C-9 contract); 12-vs-78 reduction preserved |
| "B5 breaks `⟐ output` renderer contract" | **FALSE** | Frontend has zero `⟐` refs; tests assert via `table_name`; residual = 7 duplicate `p2` display labels (documented) |
| "C-3 shared global `ul` guard" | **FALSE at HEAD** | Per-cache guards; only deleted-script sweep gap (latent) |
| "`accu.vlookup_key_value` false negative from SUBSET" | **WRONG causation** | Still excluded with SUBSET walkable — conditional-JOIN/SCHEMA-forward rules exclude it; no false negative |
| C-5↔C-3 star resurrection | **CONFIRMED (real)** | Documented for later fix (ambiguity filter in `_star_from_tables`, ~5 lines) |
| B3 wrong-instance parenting | **CONFIRMED (real)** | 6-7 same-named `p2`/`p1` nodes; fields land on first-match instance. Documented for later fix (scope-distance scoring) |
| C-4 apply-side gate | **CONFIRMED (latent)** | Zero consumers today; 3-line gate if caches become stats source |
| RELEASE.txt stale (3.3.134) | **CONFIRMED (real)** | Regenerate at deploy time |
| 2/8 join expressions unpaired | **CONFIRMED (minor)** | Zero lineage impact; pairing order-dependence noted |
| `_seen` annotation + dangling test ref | **CONFIRMED (trivial)** | 1-line each, documented |

---

## L2 data_dt investigation — BDM_ACC_LOAN_INFO_SUP_M.sql (2026-08-06, 2-team probe)

User report: search `bdm_acc_loan_info.data_dt` (workspace 8f843283a9d8) → (1) many SQL
highlights on lines without `data_dt`; (2) only 1 field (`data_dt`), no contributing
fields. **Decision (user): document only — no code changes this round.**

### Complaint 1 — highlights: REAL bug (D1+D2), not the sql_range format

`sql_range` is well-formed `[start_line, start_col, end_line, end_col]` everywhere
(contract since v3.3.45; all 55 data_dt edges + 67 lending_ref edges verified; the
`[16,5]`-style readings were the first 2 elements of 4-element tuples). The defect is the
**initial `highlights` pipeline** (`map_variables_to_lines` → `graph_service.line_map` →
`l2_builder._compute_highlight_ranges`):

- **D1 (root cause)** — `extractor/sql_line_mapper.py:42-45` picks the FIRST line
  containing `expr[:40]`, comments included. Line 3 of this script is a header comment
  listing every source table → 21 vars map to `[3,3]`; initial highlight lands on a
  comment line.
- **D2** — multi-line expressions never match any line → `(0,0)` for 76/354 vars →
  `[0,0]` leaks into the response (no filter in `_compute_highlight_ranges`).
- Observed data_dt response: `highlights=[[0,0],[3,3],[43,43],[160,160],[204,204]]` —
  line 18 (`data_dt = '$(load_date)'`, the actual predicate) NOT highlighted; "Show All"
  grows to 68 lines. General across searches (lending_ref identical pattern).
- **Proposed fix (backend only, ~10 lines + tests)**: skip comment lines in the match
  loop (`sql_line_mapper.py:42-45`); drop `start < 1` in `_compute_highlight_ranges`
  (`l2_builder.py:45-59`). Regression tests: table var maps to FROM line not header
  comment; highlights contain the predicate line and no `[0,0]`. No frontend change.
- D3 (by design): edge-click ranges span whole clauses (Bug 4 AND/OR continuation) —
  token-only highlighting is a product decision, not a bug.

### Complaint 2 — 1 field: SEMANTICALLY CORRECT (input column), 2 display gaps

`bdm_acc_loan_info` is READ-ONLY in this script (all 10 data_dt occurrences are
predicate reads: L18/L43/L55/L93/L158 WHERE; L202 JOIN ON p2.data_dt; L160/L211 output
PARTITION/insert columns on OTHER tables). DML targets = `bdm_acc_loan_info_sup` +
`rrcdm_job_log_exec_par` only. Node-by-node audit: zero production edges
(REF/COMPUTED/TRANSFORM/AGGREGATE/ALIAS/DML) into any of the 18 raw data_dt nodes →
contributors live in the upstream script that writes bdm_acc_loan_info (outside this
workspace). Pre-B-series simulation: 113 nodes / 30 phantom fields (pure SUBSET
padding); B-series: 42 nodes / 4 fields → the 1-field result is truthful.

Display gaps (documented for later):
- **P1 — seed on wrong instance**: field parents under the first `p1` alias
  (`l2_tbl_ace84be2f9`, rollover CTE scope L29) while the searched `bdm_acc_loan_info`
  node shows no field. B3 first-match (`l2_builder.py:369-381`) + Bug 28 Sync 1 dead for
  `p1` (`alias_map` collapsed `p1→loan_final`; `l2_builder.py:999-1003` no break → last
  p1, holds no fields). Larger fix = B3 scope-distance scoring (round-4 ledger item 2).
- **P2 — seed edge-less at field level**: its 4 FILTER edges promoted to the p1 table
  node (`_promote_field_edges` `l2_builder.py:683`); the `data_dt → FILTER → CTE` usage
  (L18) visible only at table level. Proposed fix: skip promotion for target/direct seed
  fields. Quirk: all 4 promoted FILTER ranges anchor L17-18 (first-match) even for the
  L158 seed.
- Seed-matching quirk: the canonical L18 unprefixed `data_dt` node (`ab16ed071f73afbc`)
  has only a SUBSET edge to its table (no SCHEMA) → not seedable; seeds are the qualified
  `p1.data_dt` nodes (dependency_graph Phase 7/8 artifact).

---

## v3.3.139 — ALL DOCUMENTED ITEMS IMPLEMENTED + VERIFIED (2026-08-06, 3-team round)

Round-4 verdicts and the data_dt investigation items are now closed at v3.3.139.
Integration verification: backend suite **635 passed / 5 skipped**; live HTTP on
workspace 8f843283a9d8 (service 192.168.0.66:8000): `data_dt` search → 1 field
(`data_dt` on `l2_tbl_d5ff4bbf35` = `bdm_acc_loan_info`), 4 incident FILTER edges at
field level, highlights `[[16,16],[43,43],[52,52],[118,118],[151,151],[160,160],[204,204]]`
(predicate line 18 covered, no `[0,0]`, no header-comment line 3); `lending_ref` search →
12 fields preserved, highlights clean.

| Item | v3.3.139 status |
|---|---|
| D1 — highlights land on header comment lines | ✅ **IMPLEMENTED** — `sql_line_mapper.py` match loop skips `--`/`/*` comment lines (Team A) |
| D2 — `(0,0)` highlight leakage | ✅ **IMPLEMENTED** — `_compute_highlight_ranges` drops `start < 1`; stale-cache reads recompute line_map via `_recompute_line_map` (`l2_builder.py:66-68`, :82, :45, :122, :151) |
| P1 — seed fields parented under wrong alias instance | ✅ **IMPLEMENTED** — B3 scope-distance parenting (`_scope_distance`/`_pick_scope_candidate` in `_resolve_scope_parent`) + seed re-parent pass moves `is_target` seeds onto the searched table's compound node (`l2_builder.py:619-640`); Sync 1 iterates all same-name alias instances (first with fields + canonical source) |
| P2 — seed FILTER edges promoted to table level | ✅ **IMPLEMENTED** — `_promote_field_edges` skips `target_field_ids` (is_target seed fields stay field-level) |
| B3 wrong-instance parenting (round-4 ledger) | ✅ **IMPLEMENTED** — scope-distance scoring replaces first-match in `_resolve_scope_parent` rule 1; src_tables/prefix loops stay first-match (pinned 12-field lending_ref result preserved) |
| C-4 apply-side gate (latent) | ✅ **IMPLEMENTED** — `_apply_s4b_cache_update` moves counters only when `n_attributed > 0` (mirror of revoke-side `n_revoked > 0` gate), `folder_index_service.py:1102-1113` |
| C-5↔C-3 star resurrection | ✅ **IMPLEMENTED** — star expansion excludes `extractor_unresolved | ambiguous_fields` (`_star_excluded` built pre-loop, `folder_index_service.py:750`) |
| 2/8 join-key expressions unpaired | ✅ **IMPLEMENTED** — `_pair_join_key_sides` deferred cross-link in `variable_extractor_v2.py:1107-1145`; now 0/8 unpaired (test `test_bdm_sample_join_key_expressions_all_paired`) |
| `_seen` annotation + dangling test ref | ✅ **IMPLEMENTED** — `set[tuple[str, str, str]]`; `test_l2_table_dedup.py:133` comment points at `test_b_series_l2.py::test_c9_per_statement_dedup` |
| RELEASE.txt stale | ✅ **Regenerated** — `VERSION=3.3.139`, `BUILT=2026-08-06 22:17:07 +0900`; COMMIT fixed to the integration commit hash |

---

## v3.3.140 — STRICT TABLE.FIELD DATA FLOW + STATEMENT-ANCHORED LINES (2026-08-07, 4-team round)

Requirement change (user): L2 must show **exact table.field data flow** instead of
table-level flow. The legacy path (`compute_field_lineage`/`filter_relevant` in
`lineage.py`) is kept **byte-identical** for L1 + legacy consumers; the new strict
walker (`compute_field_flow`/`filter_by_field_flow`, `lineage.py:523-680`) runs only on
the L2 path (`l2_builder.py:_apply_relevance_filter`). Design: wiki/SOLUTION_DESIGN.md
§v3.3.140.

| Item | Status |
|---|---|
| Strict walker | ✅ `FIELD_LIKE`/`FIELD_LAND`/`NEVER` sets; seed = searched table.field identity (per-instance var); expand only where the field participates; ALIAS iff neighbor.source_tables[0]==target; FILTER/JOIN iff seed-zone endpoint; DML forward-only; owner resolution via source_tables[0] → qualifier label → unique same-context table-like var; container rule (CTE admit); identity admissions to fixpoint (`lineage.py`) |
| Phantom dedup (raw-walk re-registration) | ✅ `_explicitly_walked_selects` prune — subquery-interior columns registered ONCE, in their own scope (`variable_extractor_v2.py:1222,1238,1248`); sample1: 344→253 vars, 1102→660 deps, bdm_acc_loan_info 4→3 contexts, 8→7 JOIN ON exprs (one phantom duplicate removed) |
| Partition walk | ✅ bare `INSERT ... PARTITION(...)` parses onto the **Table** node; registers bare `exp.Column` AND `exp.EQ`(Column left) partition exprs (`data_dt='$(load_date)'` and `CHARGE_DEPARTMENT` both land on L160) |
| Line-mapping bug (root cause of wrong highlights) | ✅ `map_variables_to_lines`/`_find_position` were **first-occurrence text scans** — p1.data_dt@158→43, alias p1@84→29, CHARGE_DEPARTMENT@160→44. Fixed: statement anchors recorded at `_walk_select/_walk_insert/_walk_merge/_walk_create` tops (`_record_stmt_anchor`); `_find_position_scoped` text-searches expr[:40] within `[anchor, next_anchor)` (nested-context anchors excluded), token-scan fallback, whole-stream fallback; `_add` uses it; `map_variables_to_lines` prefers var-carried `line_start`/`line_end` when > 0 (stale-cache text search kept as D1 fallback). `EXTRACTOR_VERSION = "2026-08-07.2"` |
| Highlights contract change | ✅ highlights = **single line numbers** `[line,line]` from node-carried `line_start` of the closure's field-like vars (node data now carries `line_start`/`line_end`, `graph_service.py:201-202`; `format_version` 4; cache prefix `graph_3_2_18`) |
| Verified on BDM_ACC_LOAN_INFO_SUP_M.sql | ✅ seed `bdm_acc_loan_info.data_dt` → closure 13 nodes; highlights `[[18,18],[43,43],[158,158],[160,160]]` **byte-exact** (E2E probe); L2 shows the seed on the physical table, the p1 alias copy (P1 MOVE→COPY), and the INSERT target's partition column; full suite **635 passed / 5 skipped** |
| Behavior deltas vs 139 (pinned tests updated) | step3 L2 JOIN edges 2→1 (only the seed-side JOIN survives — the seed zone never propagates through a JOIN edge; the mirror key column is a different field instance); data_dt seeds 1→3 (physical + alias copy + target partition, all is_target); subquery outer phantom copies gone (S3/M13 assertions updated); Sync 1 canonical copy may coexist with a same-name CTE field under the merged keeper (C7, distinct original vars) |

---

## v3.3.141 — DATA-FLOW ANALYSIS FINDINGS (2026-08-08, analysis-only round)

User questions on BDM_ACC_LOAN_INFO_SUP_M.sql (`bdm_acc_loan_info.data_dt` flow):
(a) "is the target field really used in the data flow" (p1@67 shows no field),
(b) "rollover_loan_info should have p1 in the dataflow, but there is not — why?".
Both answered with probe evidence — see below for the two **suggestions** raised
(analysis-only; no source changes, per diagnostics-not-fix).

**Answers established (not bugs):**

| Question | Answer |
|---|---|
| Is data_dt really used? | YES — 4 reads, all in the strict field flow: 18 (rollover WHERE, bare), 43 (rollover derived WHERE via p1@29), 158 (loan_final WHERE via p1@67), 160 (INSERT PARTITION). Highlights `[[18,18],[43,43],[158,158],[160,160]]` byte-exact; closure = 13 nodes incl. both p1 aliases |
| Why no p1 in rollover's dataflow? | TABLE-level chain exists (`bdm→p1@29→⟐subq→⟐subq1→rollover`, verified edge-by-edge) — but data_dt never appears in the subq's OUTPUT (SELECT DISTINCT lending_ref, loan_maturity_dt), so the SUBSET edges into rollover carry no data_dt and the strict walker (v3.3.140 design decision 21: exact table.field flow) correctly cuts them. The only surviving structural link is the SCHEMA containment edge `rollover→⟐subq` (points OUT of rollover). Proof: searching `lending_ref` restores the full chain (subq output columns `lending_ref@26/22/50` connect into rollover) |

**Suggestions (reported, NOT fixed):**

| Item | Evidence | Suggestion |
|---|---|---|
| **S1 — L2 field-attribution gap for qualified columns** | `_register_column` (:1379) registers qualified columns (`p1.data_dt`) with EMPTY `source_tables` (R20 `if table:` branch returns early; S2/S3 is unqualified-only by design). L2 `_classify_compound_nodes` then falls back to the label-prefix `p1` → FIRST matching p1 compound (p1@29, registration order) → the 43 AND 158 reads both attach to p1@29; the `(parent, label, stmt_idx=None)` dedup collapses 158 into 43's field node (`merged_original_ids`). Net: p1@67 renders with ZERO field children; only 3 of the 4 data_dt fields materialize in L2; the 158 occurrence survives only as highlight `[158,158]` + a merged id. C5's scope-picking (`_pick_scope_candidate`) is NOT applied to the prefix branch (only to the src_tables branch) | Extend C5 scope-picking to the label-prefix branch (`label.split(".")[0]` → `_pick_scope_candidate(field_ctx, prefix-candidates)`), or attribute qualified columns in R20 (owner = qualifier label → alias_map). Verify against the pinned lending_ref 12-field count — scope-splitting same-named fields across alias instances is exactly what C5's docstring warns about, so test counts may shift |
| **S2 — SUBSET BRIDGE artifacts target the first CTE** | Phase 8 of dependency_graph (:458-473, "ensure ≥2 edges for non-table nodes") glues under-connected reads to the first TABLE-type anchor of the main component — `data_dt` vars at L93 (accu subq, loan_final ctx), L160 (PARTITION), L213 (main SELECT output) all got `data_dt→rollover_loan_info` SUBSET edges although none of those reads is inside rollover. Display noise in the L2 view (edges pointing at an unrelated CTE) | Consider scope-aware anchor selection for Phase 8 (prefer same-context / enclosing-context TABLE anchors before the global first-match), or drop BRIDGE edges when the read already has ≥2 real edges |
| **S3 — p1@67 node label was the alias-line bug (v3.3.140)** | the loan_final p1 alias (def L84) resolved to L67 (first name occurrence — AS-composition bug); L2 alias label `p1@67` and the ALIAS edge range [67,14,67,30] displayed the wrong line | ✅ **FIXED (v3.3.145 + v3.3.152, verified 2026-08-11)**. I1 (v3.3.145) definition-line refactor fixed the flagship symptom: every alias node label + every ALIAS edge range now matches the SQL definition (flagship probe: 0 issues — p1@84, no p1@67 anywhere; 14 table aliases + 5 derived aliases + 2 CTEs all on def lines). Corpus-wide alias probe: 324 files, 962 alias vars, 0 mis-resolved. Residual S3-family (first-occurrence-beats-definition) found corpus-wide in repeated statement/subquery bodies (tpcds q14 join:x@61→@136, q9's 5 identical count(\*) subqueries, the flagship's two identical `LEFT JOIN (SELECT podcg…ods_hub_lsacmsp)` blocks @L32/@L108, q66/q4/08/11 union arms) — fixed by occurrence-aware statement anchors (`_anchor_head_last`, v3.3.152): the k-th anchor call for an identical head searches strictly after the last matched occurrence, so each body lands on its own lines. Full-var corpus diff (15214 vars): only line corrections, all verified against script text; 6 L2 snapshots rebaselined (documented in PHYSICAL_MODEL_MIGRATION_MAP.md Appendix B) + WINDOW-3 pin 15→21 (fixture repair with extractor evidence). Jaccard gate 1 passed; full suite 796 passed / 5 skipped. Known residual (separate family, context-dedup): q14/q39 second statement's CTE vars still collapse (WARNs, tracked elsewhere) |

---

## v3.3.142 — BDM_ACC_LOAN_INFO_SUP_M.sql: CONSOLIDATED ISSUE LIST (2026-08-07, analysis-only round)

User asked for all existing issues on this script, each with: symptom → SQL-anchored
reason → solution → expectation. Consolidates S1/S2/S3 (v3.3.141) + the artifact
findings from the full-flow listing round. Analysis only — no source changes.

### I1 — Alias definition-line bug: `p1` shows @67, defined @84 (family: S3)
| | |
|---|---|
| Symptom | L2 alias node label `p1@67`; ALIAS edge range starts L67. Definition is L84 |
| SQL reason | `FROM bdm_acc_loan_info p1` (L84) has an IMPLICIT alias (no `AS`). `_register_table` (:1055-1058) composes `"bdm_acc_loan_info AS p1"` — never matches → falls back to FIRST occurrence of the table name → `,p1.lending_ref` (L67). Same family: derived-table aliases `accu@75` (def ~L94 `) accu ON …`), `branch@72` (def ~L104), `p2@40` (def ~L119), `p4@74` (def ~L150) — registered with the whole SELECT as sql_expr → text search impossible → first occurrence |
| Solution | Definition-line refactor (designed, census of all 23 `_add` sites: 20 definition-anchored / 3 occurrence-anchored): keyword-anchored token scan (FROM/JOIN/CTE/INSERT/UPDATE/MERGE + name [AS] alias) resolved in the extraction walk, `_find_position_scoped` demoted to fallback. ✅ **DONE — v3.3.145 (I1, definition-site lines from the pre-tokenized stream + statement anchors) landed 2026-08-08; verified 2026-08-11 (see S3 row — FIXED)** |
| Expectation | Labels/edges/highlights on the DEFINITION line: `p1@84`, `accu@94`, `branch@104`, `p2@…`, `p4@…`; the alias line contains both table name and alias name |

### I2 — L2 field-attribution gap: p1@67 renders with ZERO field children (family: S1)
| | |
|---|---|
| Symptom | loan_final's p1 shows no fields although it reads `p1.data_dt` (L158) and `p1.lending_ref` (L67); both reads attach to p1@29 instead |
| SQL reason | Qualified columns (`p1.data_dt`) are registered by `_register_column` (:1379) with EMPTY `source_tables` (R20 `if table:` branch early-returns; S2/S3 unqualified-only). L2 `_classify_compound_nodes` falls to label-prefix FIRST match → p1@29 for BOTH the 43 and 158 reads; dedup key `(parent, label, stmt_idx=None)` collapses 158 into 43's node. C5's scope-picking is NOT applied to the prefix branch |
| Solution | Attribute qualified columns in R20 (qualifier → alias_map → source_tables), OR extend `_pick_scope_candidate` scope-distance to the label-prefix branch |
| Expectation | p1@67 shows ITS OWN reads (`lending_ref@67`, `data_dt@158`); p1@29 shows its own (`data_dt@43`, `lending_ref@26`, `loan_maturity_dt@27`); no cross-alias field merge |

### I3 — SUBSET BRIDGE artifacts: unrelated reads get edges to rollover_loan_info (family: S2)
| | |
|---|---|
| Symptom | `data_dt@93` (accu's own read, loan_final ctx), `data_dt@160` (PARTITION), `data_dt@213` (TOP1), `rrcdm@211` — all carry SUBSET edges → rollover_loan_info though none is inside rollover (L9-63) |
| SQL reason | Phase 8 (dependency_graph.py:458-473) "ensure ≥2 edges for non-table nodes" safety-net picks the FIRST TABLE anchor of the main component, which is rollover_loan_info@9 |
| Solution | Scope-aware anchor selection (same / enclosing context first), or skip the bridge when the node already has ≥2 real edges |
| Expectation | No cross-CTE SUBSET bridge edges; L2 shows only real reads |

### I4 — ALIAS cross-product: 6 edges instead of 3; cross-statement `sup@223 → p2@181`
| | |
|---|---|
| Symptom | `bdm_acc_loan_info@16/@29/@84` each connect to BOTH `p1@29` and `p1@67` (6 ALIAS edges); the TOP1 read `bdm_acc_loan_info_sup@223` also connects to the TOP0 alias `p2@181` |
| SQL reason | Alias map keyed by name only — no scope/statement: every physical read of a table connects to every same-name alias whose `source_tables` matches. Three reads of bdm (L16/L29/L84) × two p1 aliases (L29/L84) = 6; sup read at L223 × p2@181 = cross-statement |
| Solution | Scope the alias edges (physical read and alias must share context / statement) |
| Expectation | Exactly the real pairs: `bdm@16→p1@29`, `bdm@29→p1@29`, `bdm@84→p1@67`, `sup@160→p2@181`, `sup@223→(TOP1 alias if any)` |

### I5 — SCHEMA containment edge inside the field-flow closure
| | |
|---|---|
| Symptom | `rollover_loan_info@9 → ⟐subq` appears in the data_dt closure — points OUT of rollover, looks like a flow arrow but is containment |
| SQL reason | SCHEMA edges are emitted for container→nested-VT containment; the strict walker admits every edge with both ends in the closure (pure filter) |
| Solution | Tag containment separately from field ownership (subtype), exclude containment from closure edges / L2 flow display (nesting already shows it) |
| Expectation | data_dt closure 13→12 nodes / 18→17 edges without the containment edge; no outward "flow" arrows from a CTE to its own subqueries |

### I6 — data_dt cut at ⟐subq: CORRECT by design (documented, not a bug)
| | |
|---|---|
| Symptom | rollover_loan_info's data flow shows no p1 / no data_dt — the chain stops at the subquery |
| SQL reason | v3.3.140 decision 21 (exact table.field semantics): the subq OUTPUT is `SELECT DISTINCT lending_ref, loan_maturity_dt` (L26-27) — data_dt never appears in it, so no SUBSET edge carries data_dt into rollover. PROOF: searching `lending_ref` restores the full chain (26 nodes / 48 edges) |
| Solution | None (correct). Optional: surface a hint "field filtered out by subquery output" in UI |
| Expectation | For data_dt the cut is CORRECT; the table-level chain `bdm→p1@29→⟐subq→⟐subq1→rollover` exists (L1 / table-level flow); lending_ref/loan_maturity_dt are the fields that actually flow through |

### I7 — Partition constant has no incoming edge (minor / informational)
| | |
|---|---|
| Symptom | Target partition `data_dt@160` has no source edge (appears in closure only via the wrong I3 bridge); 15 DML edges cover the SELECT columns only |
| SQL reason | `PARTITION(data_dt='$(load_date)')` (L160) is a literal constant — no source column exists |
| Solution | Optional: emit a literal-source edge (REF from the literal var) or document partition constants as literal-fed |
| Expectation | Either a visible "source = '$(load_date)' @160" on the partition column, or at minimum no misleading bridge edge |

### Context notes (real script behavior, NOT bugs)
- `p2@181` reads `bdm_acc_loan_info_sup` (the INSERT's own target) — the script genuinely self-reads the target (L204 LEFT JOIN context).
- `p1@162` in TOP0 aliases `loan_final` (not bdm_acc_loan_info) — main-statement `p1.data_dt` reads are therefore correctly EXCLUDED from the bdm_acc_loan_info.data_dt flow.
- The 4 data_dt reads of bdm_acc_loan_info are L18 / L43 / L158 / L160(partition) — highlights `[[18,18],[43,43],[158,158],[160,160]]` byte-exact; L93's `data_dt` belongs to bdm_gdc_label_fin (different table) and is correctly excluded.

### Fix order proposal (when authorized)
1. I1 definition-line refactor (unblocks I2's attribution? no — I2 independent) — actually: 1. I2 (field attribution, small: R20 or C5), 2. I4 (scope alias edges), 3. I3 (Phase-8 scope-aware anchor), 4. I1 (definition-line refactor, largest), 5. I5 (containment tag), 6. I7 (literal edge, optional)

---

## v3.3.143 — ESSENTIAL SOLUTIONS FOR I2/I3 (2026-08-07, user directive: no patch solutions)

User directive: never use patch solutions; solutions must come from the essential
perspective — extraction already has everything; remove scope-context-string
reliance where it was used to reconstruct what extraction should have recorded.

**Discovery (code-verified): the extractor ALREADY carries the scope alias table.**
- `_SelectScope` (variable_extractor_v2.py:272-286) is built per SELECT with
  `aliases: dict` (alias → table name), `tables`, `ctes`, `deriveds`.
- Walk order verified (:973-1014): FROM → JOIN → USING → SELECT expressions →
  WHERE/HAVING — i.e. `scope.aliases` is FULLY populated before any qualified
  column is registered (SELECT list at :1001, WHERE at :1011).
- `_resolve_alias(qualifier, scope)` (:1517-1531) already resolves a qualifier
  via `scope.aliases` first (case-insensitive), script-global map second.
- `_register_column` (:1391-1401) is the ONLY missing piece: for qualified
  columns it records evidence (REPORT-ONLY) then early-returns WITHOUT
  attribution.

### I2 — ESSENTIAL solution (replaces the L2 context-string patch)
1. In `_register_column` (:1391-1401): replace the bare early-return with
   `var.source_tables = [_resolve_alias(table, scope)]` (system-schema branch
   unchanged). One call — the scope lookup is already populated and already
   resolved for evidence.
2. L2 then attributes fields via the EXISTING src_tables branch; the
   label-prefix first-match fallback (:582) and the context-string machinery
   (`_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent`,
   l2_builder.py:283-362) become dead code for attribution — DELETE them
   (cache/format_version bump; no old-cache fallback needed).
3. Derived-table qualifiers (accu.x, p2.x): `_resolve_alias` falls back to the
   qualifier name → `source_tables=[accu]` → existing owner resolution finds
   the same-context SUBQUERY var. Same path, no context strings.
Verified by simulation on BDM_ACC_LOAN_INFO_SUP_M.sql: every `p1.x` field
resolves to its own-scope alias (43→p1@29, 158→p1@67, TOP0→p1@162).

### I3 — ESSENTIAL solution (replaces Phase 7/8 first-match + context equality)
The bridge phases are line-blind and order-dependent; replace their anchor
selection with line containment + statement anchor (extraction info already on
every var: line_start/line_end; statement anchors recorded since v3.3.140):
- Phase 7 (:436-439): anchor `comp_list[0][0]` (first var registered — the
  WITH CTE wins, hence rollover) → pick anchor with
  `anchor.line_start <= v.line_start <= anchor.line_end` in the same statement;
  skip bridge when the component already connects.
- Phase 8 (:457-471): replace `(x.context or "TOP") == ctx` equality with
  line containment + statement-anchor equality; delete the global first-match
  fallback (:468-471).
Verified expected anchors: data_dt@160 (L160) → bdm_acc_loan_info_sup@160
(L160∈[160,208]); data_dt@213 → rrcdm@211 (213∈[211,225]);
ods_hub_lsacmsp@33 → bdm@29 (33∈[29,61]). No context strings anywhere.

---

## v3.3.144 — HIGHLIGHT SOLUTIONS REVIEW + COVERAGE VERIFICATION (2026-08-07, analysis-only round)

### Highlight solutions enumerated (review sample: tools/HIGHLIGHT_REVIEW_SAMPLE.sql)
| # | Solution | Verdict |
|---|----------|---------|
| A | Definition-line extraction (AST positions at registration: alias identifier / CTE name / `)` b / DML target / read occurrence) | **CONFIRMED** — the line solution |
| B | Statement-scoped text search (current `_find_position_scoped`) | Replaced by A; machinery DELETED (patch layer) |
| C | Occurrence line for everything | Dropped — wrong on aliases (a(mid)→20, b→21, a(main)→31 vs defs 22/26/33) |
| D | Span highlight (CTE/derived bodies) | Moved to display-strategy module (future) |
| E | Label-only (no SQL-panel highlight) | Moved to display-strategy module (future) |

Probe on sample (live extractor, S-B today): a(mid)→20 ✗, b→21 ✗, a(main)→20 ✗✗
(cross-CTE), CTEs/tables/reads correct. Real script: p1@67/accu@75/branch@72/p2@40/p4@74
— all first-use lines; A gives p1@84/accu@94/branch@104/p2@116/p4@149 (def lines).

### A's uncovered classes — rulings + evidence
1. **Virtual nodes (⟐, line 0)** — by design: synthetic names, no SQL text; never in
   highlights (line<1 guard). Optional extension: ⟐ nodes get their own SELECT keyword
   line (extraction-time) for clickability — OPEN.
2. **Unregistered constructs** — probed: `LATERAL VIEW explode(...) x AS c2` parses as
   `exp.Lateral` at SELECT level (arg `laterals`; extractor only handles exp.Lateral
   inside JOINs, :1071) → alias `x` NOT registered; `FROM (VALUES ...) v(c1)` → `v` NOT
   registered; `CROSS JOIN UNNEST(t.arr) AS u(c2)` → `u` NOT registered. Columns always
   register with correct read lines (x.c2@5, v.c1@2, u.c2@2). Extractor feature gap,
   not a highlight gap — optional registration in the walk — OPEN.
3. **Parse failure** — user ruling: report in DIAGNOSTIC panel, human fixes the SQL
   (today it is silently skipped under ErrorLevel.IGNORE). Include diagnostic entry in
   the implementation order.
4. **SQL formatting/preprocessing module** — **REJECTED** by user: dialect-specific
   constructs can change meaning on transpile round-trip; too dangerous. Census
   evidence: 85 workspace scripts, 0 minified (max line 374, 7 files >300).
5. **One-line (minified) SQL** — highlight line 1 is acceptable (raw mode); formatting
   module dropped, so no granularity workaround.

### Display-strategy module (D/E home — design, not implemented)
- Extraction (A) is the single source of truth for lines; the display layer consumes
  node line_start/line_end and renders highlight ranges.
- New `services/highlight_strategies.py`: registry name → strategy
  (closure node lines → highlight ranges). `single_line` = current v3.3.140 behavior
  (default); `label_only` = [] ranges (E); `span` deferred — needs span_start/span_end
  on CTE/derived vars (extraction-time) + graph cache format bump (v5).
- Selection: workspace/view config key (`highlight_strategy`), response `highlights`
  field unchanged; SqlPanel.jsx untouched. single_line/label_only are render-time
  (no cache impact); span forces format_version 5.

### Open decisions (before implementation order)
- Display module now (registry + single_line only) vs also label_only? span deferred?
- Search-highlight semantics: reads-only today ([[18],[43],[158],[160]]) — optionally
  add closure table/alias def lines (A makes them available) as a strategy.
- Include ⟐ SELECT lines (case 1) and/or lateral/values/unnest registration (case 2)?
- I5 (containment subtype) / I7 (literal edge) inclusion in the order.
- tools/HIGHLIGHT_REVIEW_SAMPLE.sql → pytest fixture (def lines 13/18/22/26/33 + reads).

### I3 tie-break design — final (2026-08-07, implementation round)
Probed during implementation: sqlglot 30.12.0 expressions carry NO positions; all vars are
single-line [L,L] (line_end == line_start) — var-range containment cannot produce the
expected anchors. Final deterministic rule (extraction-time only, no context strings):
- keep the candidate stages (exact context equality → parent/prefix context), replace first-match;
- within a stage: candidates with line <= v.line_start → take the MAXIMAL line (nearest owner);
- tie at equal line: empty source_tables (physical table) > non-VIRTUAL_TABLE > variables order;
- no candidate anywhere → SKIP the edge; the global first-match fallback is DELETED.
Verified: data_dt@160→bdm_acc_loan_info_sup@160 (max<=160; p1@162 excluded), data_dt@213→rrcdm@211
(<=213), ods_hub_lsacmsp@33→bdm@29 (tie vs p1@29 broken by empty source_tables).
Also: alias_of keyed by VariableDefinition.id (:104, exists); VariableDependency.containment
(:126, already exists) reused as the I5 tag — no new fields needed.

## v3.3.145 — I2 EXPECTATION NOT MET: alias nodes empty in L2, dropped from filtered closure (2026-08-08, post-deploy review)

### Finding (live-verified on 3.3.145, workspace 7d219a9100e1, BDM_ACC_LOAN_INFO_SUP_M.sql)

The I2 requirement's stated expectation is NOT met. Requirement text (v3.3.141:3098):
"Expectation: p1@67 shows ITS OWN reads (lending_ref@67, data_dt@158); p1@29 shows its
own (data_dt@43, ...); no cross-alias field merge" — and the v3.3.143 solution's own
verification: "every p1.x field resolves to its own-scope alias (43→p1@29, 158→p1@67,
TOP0→p1@162)".

Measured on the live API:
- FULL L2 (search_matched=false mode): 16 alias nodes (p1@29, p1@84, p2@116, a@52, ...)
  — ALL render with **0 field children** (empty shells).
- Physical nodes hold everything: bdm_acc_loan_info 13 children (reads from rollover's
  scope AND loan_final's p1 reads merged), bdm_acc_loan_info_sup 20, loan_final 23.
- FILTERED L2 (search bdm_acc_loan_info.data_dt): 7 nodes / 5 edges — **no alias node
  at all**; closure (strict walker) = 11 nodes: the 4 data_dt seeds + FILTER targets
  (loan_final@64, ⟐subq@0) + identity admissions (owner-holders bdm@16/29/84/sup@160,
  CTE containers rollover_loan_info@9/loan_final@64).

Conclusion: the ORIGINAL I2 symptom ("p1 renders with ZERO field children") persists in
a new form — fields moved from "wrong-alias by first-match (p1@29)" to "physical node,
all scopes merged". The "no cross-alias field merge" promise is unmet, and the filtered
view lost alias visibility entirely (pre-145: p1@29/p1@67 in the 13-node closure).

### Root-cause chain (why it happened)

1. I2 attribution implemented as specified: `source_tables = [_resolve_alias(table, scope)]`
   → qualified field carries the PHYSICAL table name.
2. L2 field attachment ("existing src_tables branch") attaches by source_tables[0] →
   the physical-table compound node — NOT the own-scope alias node. The brief's
   assumption ("158→p1@67" via simulation) was never validated against the real branch.
3. Strict walker (v3.3.140): owner resolution = source_tables[0] → physical table;
   SCHEMA ∈ NEVER (lineage.py:411) — fields land on owners via the identity pass, and
   alias nodes are not owners anymore. ALIAS edge bdm@84→p1@84 exists but bdm@84 enters
   the closure only post-BFS (identity pass), so the edge is never traversed.
4. Verifier (A6) judged the alias-drop "legitimate I2 consequence, not a regression" —
   checked closure counts only, never against the requirement's expectation text.

### Fix direction (essential-perspective, NOT implemented — documentation only per user order)

- L2 compound build: attach each qualified field to its own-scope alias compound node
  using extraction-time info only — qualifier (var name prefix), context (on the var),
  alias node identity (the v3.3.139 dedup key `(alias_parent_id, label, alias_line)`
  already exists). Physical node keeps unqualified reads.
- Filtered view (optional): walker rule to admit the ALIAS edge from an in-closure
  physical owner to its same-scope alias (rule at lineage.py:620-623 already admits
  when nb.source_tables[0]==target_table — owners must enter the BFS-visited set
  instead of only the post-BFS identity pass, or the alias target must be added
  alongside its owner in the identity pass).
- Re-check expectation: after fix, full L2 p1@84 children == loan_final's p1 reads
  (lending_ref@67/84, data_dt@158...); filtered closure regains p1 nodes; I5 13/17
  numbers re-verified.

## v3.3.146 — NEW-METHOD L2 EXPERIMENT: source_tables-driven closure vs. graph walk (2026-08-08, analysis-only round)

### The new method (prototype, ran in-container — NO source changes)

Input: only extraction-time `source_tables` + variable `context` (the info that
already exists on every var). No graph edges at all — sidesteps the 4 missing
edge types (ground truth §4.3) instead of waiting for them.

```
STEP 1  occurrences   = column vars named data_dt whose source_tables ∋
                        bdm_acc_loan_info (the reads) + the DML-target
                        partition write (column whose line == container's
                        line, TOP0/TOP1)                      → [18, 43, 158, 160]
STEP 2  table_of(occ) = qualified → alias table var with same name+context;
                        bare → physical table var in same ctx  → bdm@16, p1@29,
                                                                    p1@84, sup@160
STEP 3  scope closure = fixed point: container_of(t) (TOP0/TOP1 → DML target,
                        CTE{X} → cte var, nested → virtual_table), VT parent
                        chains via ctx.rsplit('/'), then ANY table-like read
                        whose canonical name (source_tables[0] else own name)
                        is in the closure's scope names        → 6 scopes incl.
                        rrcdm_job_log_exec_par@211 (via sup@223 read)
STEP 4  edges         = READ field→table (×4), table→container (×3),
                        consumption canonical→scope (×4), VT feeds (×3)
```

KEY FIX vs. first prototype: physical table reads have EMPTY source_tables
(only alias reads carry it: p3@204 → ['bdm_sys_acc_loan_info']); the fixed
point must fall back to the var's own name, else `bdm_acc_loan_info_sup@223`
(read → stmt2) is invisible and the closure dies at stmt1 — exactly where
the graph walk dies too.

### Result (prototype run, deterministic)

```
new-method closure:  10 semantic nodes = 4 field occurrences + bdm_acc_loan_info@16
                     + rollover_loan_info@9 + ⟐ subq@0 + ⟐ subq1@0 + loan_final@64
                     + bdm_acc_loan_info_sup@160 + rrcdm_job_log_exec_par@211
2 sinks reached:     bdm_acc_loan_info_sup@160, rrcdm_job_log_exec_par@211  ✓
14 edges:            4 READ (18→bdm@16, 43→p1@29, 158→p1@84, 160→sup@160)
                     3 container (bdm@16→rollover@9, p1@29→⟐subq, p1@84→loan_final@64)
                     4 consumption (rollover→loan_final, loan_final→sup,
                                    sup→sup self-join, sup→rrcdm)   ← the old #4!
                     3 VT feeds (⟐subq→⟐subq1, ⟐subq1→rollover, ⟐subq→rollover)
highlights:          [18, 43, 158, 160] — byte-identical to existing tool
propagated:          sup.data_dt [202, 213] — matches ground truth §5.2 (225 still
                     unextractable, Defect 5)
```

### Comparison — new method vs. the two existing calculations

| what | filter_by_field_flow (11/5) | downstream BFS (14/10) | NEW method |
|---|---|---|---|
| field lines | [18,43,158,160] | [18,43,158,160] | [18,43,158,160] |
| reaches stmt2 | ✗ dead-end at sup@160 | ✗ dead-end before stmt2 | ✓ rrcdm@211 in closure |
| read edges field→alias (#1 #2 missing) | ✗ (stub tables @29/@84, 2 disconnected) | ✗ (source-blind) | ✓ READ 43→p1@29, 158→p1@84 |
| DML output→sup (#3 missing) | ✗ | partial (TABLE_FLOW p1@198…) | ✓ consumption loan_final→sup |
| cross-statement write→read (#4 missing) | ✗ | ✗ | ✓ sup→rrcdm via sup@223 |
| sinks | 0 | 0 | 2 |
| noise | 2 disconnected stubs | — | 0 |

VERDICT: the new method is strictly more accurate — it reaches both sinks and
covers all 4 missing-edge semantics using only extraction-time info. It also
independently CONFIRMS the existing highlights [18,43,158,160] are correct.

### Why the new method works where the walk fails

1. `source_tables` are extraction-time (written when the read is parsed) —
   they cannot be lost to edge-type bugs, cross-scope SCHEMA contamination (I2),
   or first-match range anchoring.
2. Consumption is keyed by canonical NAME (source_tables[0] or own name), so a
   physical re-read of a known table (sup@223 → rrcdm stmt) joins the closure —
   the graph can't express this because missing edge #4 never links stmt2.
3. container_of() gives scope→node identity directly from context; no
   find_sql_range anchoring, no range merging, no id re-pointing.

### Suggestion (implementation only on order)

- If adopted, the natural home is a new builder that runs BEFORE the edge walk:
  closure over (variables × context × source_tables) as above, then reuse the
  existing range finder ONLY for highlight lines (which the prototype confirms
  correct). The L2 endpoint would return this closure + existing highlights.
- Caveats before adopting: (a) partition-write rule (STEP 1 tgt_write) assumes
  the write column's line == container line — verified only for INSERT
  OVERWRITE PARTITION; (b) cross-statement link relies on same table NAME —
  alias-of-alias or renamed physical tables need the alias resolution first;
  (c) this is a closure over CONSUMPTION — pure SELECT-on-select chains
  (no write in between) need the same name-keyed rule to pass through, which
  the fixed point already does via source_tables on alias reads.
- Prototype script: throwaway heredoc, not committed. Re-runnable on request.

### Root cause of the 4 missing edges (code-verified in dependency_graph.py)

| missing edge | where the code drops it |
|---|---|
| #1/#2 field→alias-table read | Only two column↔table relations exist: SCHEMA (line 250, table→column OWNERSHIP, I2-contaminated) and FILTER (line 375, column→scope CONTAINER). No phase emits column→own-table; the pairing exists on the vars (qualifier+context+source_tables) but is never materialized as an edge. |
| #3 output VT→DML target | Phase 1c (line 151) emits DML only from vars with source_columns (the 15 field-level edges); the output VT has none. Phase 1c-extra (line 170) links source aliases DIRECTLY to the target, bypassing the VT. Result: ⟐ output@0 fed but never consumed. |
| #4 cross-statement write→read | Phase 1a line 117 `if not v.source_tables: continue` — physical reads get zero edges; alias reads link only to their own ctx's VT (line 121). All edges are same-context; no mechanism links a table written in stmt N to the same physical table read in stmt M. stmt2 is an island by construction. |

RECOMMENDATION (analysis only): fix the edges — root repair. Each is a small
local emission (one read-edge phase for #1/#2; one anchor→target DML edge in
1c for #3; one cross-statement name-keyed pass for #4). After the fix, ground
truth §4.4 predicts BOTH old calculations converge to the 10-node/2-sink
closure; the new method above becomes the regression oracle. Implementation
only on explicit order.

## v3.3.146b — LOOP ROUND 1 CONVERGED; OPEN CONCERNS FROM THE AUDIT (2026-08-07)

Round-1 outcome: benchmark 6/6 (closure 13 nodes / 16 edge pairs / 2 sinks /
highlights byte-exact; deps snapshot 649→737 updated with evidence). Full
audit record in GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md §7.4.

Open concerns (non-blocking, from the main-session audit of commit da6e18f):

1. **1c-cross lacks a statement-ORDER check** — write→read is emitted for any
   other-statement reader of the same canonical name, even if that reader
   statement comes BEFORE the writer (reversed-time edge). Correct on the
   benchmark sample (2 stmts, reader is later); refine with a TOP-index
   comparison (writer idx < reader idx) when other scripts exercise it.
2. **1c-self vacuous guard** — `if ek in seen_edges: continue` can never be
   true (self-loops are forbidden by _add_edge) — dead code, harmless.
3. **Walker clause (b) is O(V) per candidate edge** — compute_field_flow's
   TABLE_FLOW VT clause scans node_map.values() for every candidate edge
   (context ancestor check). Fine at 253 vars; memoize visited field-var
   contexts before large-script scale-up.
4. **1c-direct redundancy** — direct CTE→reader CTE / CTE→DML-target edges
   duplicate the ALIAS+TABLE_FLOW consumption chains (rollover→p6→loan_final
   vs rollover→loan_final). Accepted by design so canonical endpoints pair
   exactly; benign, but the ALIAS chain edges become unreachable for the
   walker's closure (the ALIAS rule keys on target_table) — re-visit if the
   full L2 view should render the alias intermediate.

## v3.3.147 — HIGHLIGHT REDEFINITION: edge-driven, no field highlight (2026-08-10, user ruling — definition only, NOT implemented)

### The ruling (user, verbatim intent)

- The highlight feature visualizes the corresponding SQL script lines for
  **the data flow of a certain edge**.
- Initial assumption: **every edge corresponds to one data flow**.
  1. In L2, every edge corresponds to one data flow; multiple data flows
     between nodes ⇒ multiple edges (no merging).
  2. **There is no field highlight** — visualizing script lines for fields
     is not what we want.
  3. The highlight must contain **at least one script line**; when the
     exact range is difficult, fall back to a single line via **field-name
     text matching** of the flow's field (simplicity, by design). The
     module that expands one parser-extracted line to a range
     (`sql_range_finder`) is exactly the mechanism for this.

Formal definition written into GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md §8
(edge contract §8.3, counting invariant §8.4, benchmark impact §8.5).
§5 / §7.2-Highlights marked SUPERSEDED. This entry is the implementation
checklist for the next iteration round.

### Implementation targets (on explicit order only)

1. **Remove the field-highlight layer.** Level2 response `highlights` must
   no longer be derived from field-like closure vars; `highlight_strategies`
   `single_line`/`label_only` concept is obsolete for L2 search. The
   closure-level highlight set = union of per-edge spans (edge `sql_range`).
2. **Fix edge `sql_range` quality** (live-verified defects, workspace
   73044295bb66, 2026-08-10):
   - SUBSET edges (incl. the v3.3.146 Phase-4d READ edges): inverted
     `[94,32,94,19]` — start col 32 > end col 19, L94 (`) accu`) is 15 chars
     → empty fragment. Must be ≥1 real line per §8.3.
   - ALIAS edges: anchored at the alias's first column use
     (`[66,14,69,30]` → `p1.lending_ref` in the SELECT list) instead of the
     alias-def line (L29). Re-anchor to the def site.
   - Coarse table-read spans `[15,5,15,32]` (just `FROM`) — acceptable
     fallback only if the exact range is genuinely hard (§8.3.2 field-name
     match would give the field's line instead; prefer the more specific).
3. **Rework the benchmark to edge-range ground truth.** Replace
   `CANONICAL_HIGHLIGHTS`/`CANONICAL_PROPAGATED` with
   `CANONICAL_EDGE_RANGES` (16 canonical edges → expected span, exact or
   fallback single line). `test_highlights`/`test_propagated_field` →
   `test_edge_ranges` asserting per-edge: ≥1 line, not inverted, and each
   canonical edge's span matches. Old invariant "highlight count == edge
   count" holds by construction (16 edges ⇒ 16 spans, §8.4).

### Unchanged by this ruling

- §7.2 closure spec (13 nodes / 16 edge pairs / 2 sinks) — untouched.
- Defect 5 (L225 no var) stays a known gap; under the new model it surfaces
  as a possible missing edge/span for stmt2's WHERE read, with §8.3.2
  field-name match as the documented fallback path to still show L225.

### v3.3.147 addendum (2026-08-10) — synthetic-flow anchors refined to creation lines

§8.3.3 refined (user proposal, accepted): VT-sourced edges highlight the
VT's **creation line** — subquery VTs = their own SELECT line; statement
output VTs = the statement's DML-clause line (INSERT/MERGE keyword), NOT
the whole-statement anchor (TOP0 raw anchor is L9 `WITH` while the flow is
at L160 — probe-verified). VT-targeted edges keep the feeding var's exact
def line (no hub collapse; creation line never overrides an exact line).

Implementation consequence for the next iteration's fix list (target 2):
- VTs must carry their creation line at extraction time (currently all
  line 0): `line_start` = context statement anchor at VT creation
  (`_stmt_anchor_for(context)`); statement-level VTs need the DML-clause
  line refinement (scan the statement for INSERT/MERGE keyword token —
  extraction-time info, no reconstruction).
- Expected creation lines on the canonical sample: ⟐ subq1 → L22,
  ⟐ subq → L26, ⟐ output (TOP0) → L160, ⟐ output (TOP1) → L211.
  Canonical VT-sourced edges' expected spans: `⟐ subq@0 → ⟐ subq1@0` =
  L26 (source creation line), `⟐ output@0 → sup@160` = L160.

### v3.3.147 addendum 2 (2026-08-10) — line-resolution collapse (3→1) + no stale-cache repair (user rulings)

**Ruling A — no stale-cache repair, ever.** Caches are empty in every new
deployment. A cache whose variables lack carried lines is a cache MISS —
rebuild from extraction — never repaired on read.
- Removed (on implementation order): `map_variables_to_lines` text-search
  fallback + D1 comment skip; any `_recompute_line_map`-style read-side
  repair; `line_start <= 0` fallbacks that search text.
- Carried lines are the single source of truth; the mapper either becomes
  a pure passthrough or is deleted (callers read var-carried lines
  directly).

**Ruling B — collapse the 3 line-resolution mechanisms to 1** ("remove
what we have decided to remove"):
- Removed: `_find_position` (whole-stream text search — was fallback-only),
  `_find_position_scoped` (v3.3.140 statement-scoped text search — the
  pre-collapse default, and the Defect-5 source), and the `def_site`
  branch in `_add`.
- Kept and extended: `_find_def_position` token-run matching (v3.3.145 I1)
  becomes the ONLY mechanism, used for every add — reads included. L225's
  WHERE column then matches its own token (225), not the first `data_dt`
  text (213): Defect 5 dissolves, and the duplicate `data_dt@213`
  (literal + column sharing one stamp) splits into alias-def@213 +
  read@225.
- Statement scoping stays: `_stmt_anchor_for`/`_next_anchor_after` are
  SCOPE, not a resolution mechanism — the token search runs inside
  `[stmt_anchor, next_anchor)` as today.

**Consequence for the working layers** (target 2, implementation order
only): extraction is the sole source of lines; L2 computes per-edge
highlight entries from var-carried lines + alias-def info; display
strategies and the payload/frontend are unchanged in shape (see the
working-layers walkthrough in the conversation). **SUPERSEDED by addendum
3/5:** `sql_range_finder` is removed entirely (line-only model, user:
"we only highlight a line instead of a range") — its span quality defects
(inverted `[94,32,94,19]`, coarse FROM spans, ALIAS mis-anchors) die with
the module instead of being fixed.

### v3.3.147 addendum 3 (2026-08-10) — self-join read ruled IN; the 19-pair spec (user ruling)

**Ruling (user, verbatim intent):** "It should be included… It is also a
type of data flow" — the L202 self-join key read
(`LEFT JOIN bdm_acc_loan_info_sup p2 … AND p2.data_dt =
DATEADD(DATE'$(load_date)',-1,'DD')`) is a genuine flow: the script joins
the table to itself, and the join-key read is a data flow like any other.
**Edge D confirmed → the spec is 19 pairs** (16 canonical + B + C + D).
Written into GROUND_TRUTH §8.3 (per-edge anchor table) / §8.4 / §8.5.

**Amendments to the implementation targets above:**
- Target 3 becomes `CANONICAL_EDGE_LINES` with **19 pairs** (not 16
  `CANONICAL_EDGE_RANGES`); `test_edge_lines` asserts the exact anchor line
  per pair; the three extras are canonical (existence + exact line + ≥1).
- Target 2 becomes: **remove `sql_range_finder` entirely** (user: "we only
  highlight a line instead of a range") — the payload carries edge
  `highlight_line`; the frontend click highlights that one line; the
  range-expansion behaviors die with the module, including the Bug-4
  AND/OR continuation extension (v3.3.66) — intentional regression,
  **CONFIRMED acceptable 2026-08-10** (addendum 5).
- New target: **type promotions** so the Flaw-5 boundary rule (ruled in
  addendum 4) admits the confirmed flows — pair 17: SUBSET/BRIDGE →
  value-write type (REF/DML semantics); pair 19: SUBSET/READ → honest
  join-key read (FILTER/JOIN semantics); VTs carry creation lines (pairs
  5/6/15). **AMENDED by addendum 5 (probe-pinned): the SUBSET set is SEVEN
  pairs — 1, 2, 12, 13, 14, 17, 19** (§8.7 per-pair map).
- Edge-D anchor: L199 (p2's alias-definition line) — the READ rule applies.

### v3.3.147 addendum 4 (2026-08-10) — Flaw-5 boundary rule RULED: chain edges count

**Ruling (user):** "I think this is better: chain edges count." The Flaw-5
boundary rule is ACCEPTED as proposed:
- **Counts**: a real anchor line (field appearance / alias-definition-FROM /
  VT-creation) OR a walkable chain edge (TABLE_FLOW / ALIAS / DML) — the
  row-set carriers between field appearances, anchored at the flow's entry
  line (source def / VT creation). The 19-pair spec stands, including the
  8 chain pairs (2/4/5/6/8/9/10/11) anchored on lines without field tokens —
  the trace stays continuous between L18 and L160 (the field is inside the
  flow, not printed on the carrier's lines).
- **Never**: SUBSET/BRIDGE — peremptory, not even a tie-breaker
  (`sup@223 → rrcdm@211` out; the `data_dt@213 → rrcdm@211` bridge variants
  out as bridges); SCHEMA containment (I5); INDIRECT endpoint-decided.
- **Prerequisite accepted**: type promotions — pair 17 (SUBSET/BRIDGE →
  value-write type), pair 19 (SUBSET/READ → join-key read type); without
  them the peremptory exclusion would drop flows already ruled in.
- **Rejected alternative**: field-appearance-only (11 pairs, gaps between
  field appearances).
Written into GROUND_TRUTH §8.3 (boundary-rule block). The formal definition
is now complete: §8.1 line-only model, §8.3 five anchor rules + 19-pair
table + boundary rule, §8.4 counting 19 ⇒ 19, §8.5 CANONICAL_EDGE_LINES,
§8.6 gaps.
**Still open before implementation**: (a) the AND/OR continuation
regression confirmation (sql_range_finder removal — a multi-line WHERE
lights only the anchor line) — **CONFIRMED 2026-08-10, addendum 5**
("one line highlight is very simple and efficient. Just use it.");
(b) the implementation order itself — **replaced by the work list in
addendum 5** (no source code before user approval).

**Defect-5 root cause (recorded, probe-verified 2026-08-10):** the WHERE
walk DOES register L225's `data_dt` (new COLUMN var, TOP1 context), but
`_find_position_scoped` (v3.3.140) stamps it 213: the anchor is 212 (the
SELECT keyword line — `_walk_insert` records 211 first, the source SELECT's
walk overwrites it; anchors are last-wins), and the statement-scoped search
finds the first "data_dt" TEXT in [212, ∞) = L213 (`'$(load_date)' AS
data_dt`). Hence no var carries line 225, and the duplicate `data_dt@213`
(literal + column sharing one stamp) is the same root cause. Fix (ruled,
addendum 2): token-run matching extended to reads — L225 matches its own
token, the duplicate dissolves, pair 18 is unblocked.

### v3.3.147 addendum 5 (2026-08-10) — final rulings + probe matrix + WORK LIST (definition complete)

**Four rulings (user):**
1. **AND/OR continuation regression CONFIRMED**: "one line highlight is
   very simple and efficient. Just use it." — multi-line conditions light
   only the anchor line; accepted, not to repair.
2. **Definition must include both edge types + highlight decision + rules**,
   updated in the formal definition, requirement, and solution BEFORE any
   source code: GROUND_TRUTH §8.7 (16-row real-type → flow-kind →
   highlighted? map + per-pair real-type table), REQUIREMENTS R25, this
   addendum. **Plus a new L2 display requirement**: the reason of highlight
   (flow kind) must be visible in L2 before clicking — RULED 2026-08-10:
   flow-kind labels on the edges + reason panel below the SQL panel
   (second-round rulings below).
3. **Verify-first approved (option b)**: probe real-SQL anchors for
   INDIRECT/WINDOW/CORRELATED/SET_OP before implementation — candidates
   pinned (§8.9): `snowflake_qualify.sql` (WINDOW), `tpcds_qualified/86.sql`
   (SET_OP+WINDOW), `spider_complex/046_pets_1_s6.sql` (INDIRECT).
   **Discovery: CORRELATED is never emitted as a relationship** — correlated
   subqueries are INDIRECT/CORRELATED(_OUT) (dependency_graph.py:487/495).
4. **Payload/UI statements written** (§8.6, §8.8): payload carries
   `highlight_line` + `flow_kind` + `reason` only; `highlights`/`propagated`/
   `sql_range`/`sql_ranges` die; shared lines accepted with multiplicity
   (rendering decision only).

**Probe matrix (2026-08-10, both closures, seed-parameterized probe):**
- **Closure seeds split the spec**: bdm seed → pairs 1–16 (16 nodes / 24
  edges); sup seed → pairs 11, 12, 15, 16, 17, 19 (8 nodes / 12 edges).
  No single seed covers all 19 → benchmark asserts pairs 1–16 on the bdm
  seed, 17/19 (+18 post-fix) on the sup seed (§8.5).
- **Seven pairs typed SUBSET today** (promotions, §8.3/§8.7): SUBSET/BRIDGE
  — pairs 1, 2, 12, 17; SUBSET/READ — pairs 13, 14, 19 (+18 post-fix).
- **Pairs 4 & 8 have no direct edge** — 2-hop (ALIAS + TABLE_FLOW/FROM),
  both hops anchor at the pair's line; pairs 9 & 10 are direct (p6@155 /
  p1@198 never materialize).
- **Extras with real anchors — RESOLVED (counted, option 1)**: ALIAS hops
  bdm@29→p1@29 (29), bdm@84→p1@84 (84), sup@160→p2@199 (160) + JOIN
  condition p2.data_dt@202→⟐output@0 (202). Counted per the boundary rule;
  pinned as verified extras E1–E4 in §8.5 (GROUND_TRUTH).
- **Defect-5 re-confirmed**: `data_dt@225` exists in NO closure; sup@223
  exists with only the excluded bridge. Pair 18 stays blocked until the
  token-run fix.
- **All edges highlight (ruled 2026-08-10)** — the SCHEMA containment
  edges (p1@29→p1.data_dt@43/158, p1@84→p1.data_dt@43/158,
  p2@199→p2.data_dt@202) and the residual bridge (sup@223→rrcdm@211)
  are highlighted too: S1–S5 + B1 in the benchmark (anchors 43/158/202/
  223 — all already-lit lines). Plus the chain-completeness rows C1–C4
  (rollover@9→⟐output, loan_final@64→⟐output, p2@199→⟐output, p2@199→
  sup@160; anchors 9/64/199) — the closure bijection is complete:
  23 → 33 entries, still 16 distinct lines. The seven promotions stand
  (type honesty); only B1 remains SUBSET after promotion. Peremptory
  exclusions superseded.

**Docs updated this round:** GROUND_TRUTH §8.3 (prerequisite + probe
findings), §8.5 (two-seed benchmark), §8.7 (mapping), §8.8 (L2 display),
§8.9 (verification plan), §8.10 (open confirmations); REQUIREMENTS R25;
addenda 2–4 amended (stale promotion list, pending marks, sql_range
quality item).

**Second-round rulings (2026-08-10 — L2 display, user):**
1. **Flow-kind labels on the edges** — every L2 edge shows its flow-kind
   label at the edge midpoint; label = flow kind ONLY (never edge type,
   never SQL text). Kind names per §8.7 (`chain` / `field flow` / `read` /
   `write` / `filter` / `structure` / `bridge`); every edge highlights
   (ruled — SCHEMA/SUBSET included), labels render in the edge's category
   color. Always visible, no toggle.
2. **Click → SQL highlight + NEW reason panel BELOW the SQL panel** — the
   panel shows flow kind + anchor + reason.
3. **Reason includes the string-format data flow — full path + current
   edge location (both, ruled)** — `<flow kind> — <flow string>`: the
   walkable chain `{label}@L{line} → …` from the closure entry to the
   edge's target (overview), with the clicked edge's own segment
   emphasized (current edge location). Built at L2 build time (never
   reconstructed at render). Worked example in §8.8.3 (pair 4).
4. **Every edge highlights — RESOLVED (2026-08-10, user ruling)** —
   "There is an edge, there should be a highlight… every edge in L2
   representing a data flow, doesn't it? so the scheme edge is also
   included." SCHEMA (structure, rule 6: member's appearance line) and
   residual SUBSET (bridge, rule 7: source's def line) are highlighted
   like any flow. No excluded category; the former peremptory exclusions
   are superseded (kept as history in §8.3). New benchmark rows S1–S5 +
   B1 + C1–C4 (probe-pinned; closure bijection) — 33 entries, 16
   distinct lines.
W5/W7 updated below; GROUND_TRUTH §8.8 rewritten RULED; R25 amended.

**THE WORK LIST (implementation order — NO SOURCE CODE before user
approval of this list and of §8.10's confirmations):**

| # | Item | Depends on | Verification |
|---|------|-----------|--------------|
| W1 | Anchor probe round on the 3 candidates (WINDOW / SET_OP / INDIRECT) — pin §8.9 expectations | — | probe output → §8.9 table complete |
| W2 | Defect-5 fix: token-run matching extended to reads (L225 registers, duplicate `data_dt@213` dissolves) | — | pair 18 present, anchor 223 |
| W3 | Type promotions at extraction: pairs 1, 2, 12, 13, 14, 17, 19 → honest types | W2 (pair 18) | per-pair map §8.7 |
| W4 | Line-resolution collapse 3→1: delete `_find_position`/`_find_position_scoped`; `_find_def_position` for every add; no stale-cache repair (`map_variables_to_lines` fallback gone) | — | probe: no text-search paths left |
| W5 | Per-edge payload: edge `highlight_line` (+ `flow_kind` + `reason`, where `reason` includes the string-format data flow — full path + current edge segment, closure walk `{label}@L{line} → …`, §8.8.3); remove `sql_range`/`sql_ranges`/`highlights`/`propagated`; remove `sql_range_finder` + dead import | W2–W4 | payload shape test |
| W6 | VTs carry creation lines (pairs 5/6/15: 26/22/160) | — | anchors 26/22/160 |
| W7 | Frontend (R25, ruled 2026-08-10): edge flow-kind labels at edge midpoint (kind only, category color — every edge incl. SCHEMA/SUBSET); click → `highlight_line` + NEW reason panel below the SQL panel (kind + anchor + reason incl. string-format flow, full path + current edge); hover tooltip + legend stay secondary | W5 + §8.8 (ruled) | live check |
| W8 | Benchmark rework: `CANONICAL_EDGE_LINES` 19 pairs + 4 verified extras (E1–E4) + SCHEMA/bridge entries (S1–S5, B1) × two seeds; `test_edge_lines` (exists + exact anchor + ≥1) | W2–W6 | pytest green |
| W9 | Docs closed out (benchmark contract update), version bump, deploy per target_deploy.sh | W7–W8 | live check on 192.168.0.66:8000 |

Gates: G1 = §8.10 confirmations — extras counting + two-seed benchmark
RESOLVED; display design RULED (2026-08-10); all micro-decisions RESOLVED
(flow-string scope: both; excluded edges: every edge highlights, no
excluded category). G1 is fully cleared. G2 = user approves this work
list; G3 = per-item verification. Docs-only until G2.

---

## Round 11 — User reports 2026-08-10 (analyzed + recorded, NO source changes)

### R11-1 · No flow reason in the panel below the script panel (L2)

**User report:** the panel below the script panel shows no reason; besides the
path (the SQL anchor highlight) there should be a reason explaining why the
edge is a valid data flow.

**Analysis (verified end-to-end, no code defect found in the chain):**
- Backend: every served L2 edge carries `reason` + `flow_kind` — live-verified
  24/24 edges on the bdm view (e.g. `chain — data_dt@L18 → bdm@L16 → ‖rollover@L9 → ⟐ output@L160‖`).
  The reason IS the full flow path + the clicked edge's ‖…‖-wrapped segment
  (§8.8.3, built at L2 build time). Not a backend gap.
- Frontend source: `EdgeReasonPanel` is rendered BELOW `SqlPanel`
  (DataFlowApp.jsx:660-664); edge tap → `onEdgeClick(e.target.data())`
  (DataFlowGraph.jsx:24-29); hook binds `cy.on('tap','edge',…)`
  (useCytoscapeGraph.js:109) with background-tap guard (`e.target === cy`,
  :111-114); CSS present (styles/app.css:347-383); vitest 5/5 pass
  (EdgeReasonPanel.test.jsx: empty state + kind/anchor/reason + ‖‖ emphasis).
- Served bundle: built 2026-08-10 20:21:58 from the same tree committed
  20:23:06 (28d8210, v3.3.147) — panel strings + CSS confirmed in the live
  bundle (`index-Dq68Ow1O.js`, `index-Bq4l-YRX.css`).
- L1 on this workspace has no edges (R24 single-script), so L2 is the context.

**Root-cause candidates (in likelihood order):**
1. **Stale browser cache** — any session that loaded the page before
   2026-08-10 ~20:22 holds the pre-R25 bundle (no panel at all). Hard
   refresh (Ctrl/Cmd+Shift+R) fixes it.
2. **Click-to-reveal empty state (UX gap)** — the panel intentionally shows
   "Click an edge to see its flow reason" until an edge is clicked. A user
   who expects the reason to be visible without interaction reads this as
   "no reason". Matches "besides the path, there should be the reason".
3. No reproducible code path for "clicked an edge → still nothing" — would
   need a browser console capture.

**Suggested solution (later, after user approval):** make the reason visible
without interaction — (a) auto-select the seed-zone edge on L2 load so the
panel is never empty; (b) render the FULL closure path by default (the
per-edge `reason` strings already contain it) with the clicked edge
emphasized; (c) strengthen the empty-state hint ("Click an edge — e.g. the
green flow edge — to see why this data flow is valid"). No code now.

### R11-2 · Duplicate fields under the rrcdm_job_log_exec_par table node

**User report:** the rrcdm_job_log_exec_par table node shows two identical
`data_dt` fields (both filtered L2 views, bdm + sup).

**Analysis (code-verified root cause):**
- Served sup view: rrcdm node `l2_tbl_ffdb91ce89` has exactly two children,
  both `data_dt`: `dml_fld_cd6b13c9fb_l2_tbl_f` and `dml_fld_41923d6d37_l2_tbl_f`
  (DML phantom fields, `dml_` prefix = Sync 2 copies). bdm view: same
  duplicate (`data_dt` × 2).
- Mechanism: `_sync_alias_and_dml_fields` Sync 2 (l2_builder.py:1166-1187)
  creates one phantom per (DML pair × source-field instance). Two data_dt
  instances flow into rrcdm — the sup output column (`fld_e2b38f37a7`,
  parent sup) and the output-VT column (`fld_faa927ddff`, parent output) —
  each sources a phantom under the target. The exists-check
  (l2_builder.py:1177-1181) is **stmt-aware** (`orig_stmt` of the source's
  `original_id`): two instances from different statements are treated as
  distinct (C-9 per-statement design) and both pass → duplicate same-label
  fields under ONE target table node.
- Pre-existing behavior (Sync 2 untouched by the v3.3.148 fixes); the flood
  previously hid it; the clean closure now exposes it.
- The Jaccard benchmark's B pins rrcdm as a node WITHOUT field children —
  the benchmark is blind to field-level duplicates (no field-uniqueness
  invariant yet).

**Suggested solution (later, after user approval):** the phantom
exists-check should dedup by **(target, label)** — stmt-awareness is
meaningful for source-side fields (C-9) but not for a target table's column
display (a table node shows each column once). E.g. drop the
`orig_stmt` term in the Sync 2 exists-check. Optionally add a benchmark
invariant: no duplicate (parent, label) field pairs in A. No code now.

### R11-3 · Data flow is hard to understand — def-site anchors vs reference sites

**User report:** "It is hard to understand the data flow. For example: there
are two edges of rollover_loan_info@L9 → loan_final@L64. And we can see the
script. But it is difficult to understand why the script segments mean data
flow. Do you have any good method please?"

**Analysis (probe-verified, sample BDM_ACC_LOAN_INFO_SUP_M.sql):**
- **Anchors are def-sites, not reference-sites.** The chain edge's hl=9 is
  rollover's CTE def line (`WITH rollover_loan_info AS (`, rule 5: chain
  anchors to the SOURCE's def line). The actual consumption site is L155
  `LEFT JOIN rollover_loan_info p6` — 146 lines away inside loan_final's
  body (L64..159). The user cannot connect the highlighted L9 to loan_final.
- **One node pair, several distinct flows.** Full graph rollover→loan_final:
  TABLE_FLOW@9 (chain), COMPUTED@82 (value: `p6.lending_ref` → `reserved_field8`),
  JOIN@82 (key: `p6.lending_ref = p1.lending_ref` @L156). "Two edges" = the
  COMPUTED+JOIN pair sharing anchor 82. Unlabeled arrows conflate structure,
  value, and join-key flows.
- **Reason strings show the path, not the mechanism.** No clause/alias/line
  of reference; "why valid" is not answerable from the panel.
- **Extraction-time evidence exists** (probe `_probe_ref.py`, 253 vars):
  `p6` (TABLE, line=155, `defined_in='JOIN'`, context=`CTE{loan_final}`,
  `source_tables=['rollover_loan_info']`) — the reference site is already a
  per-var extraction fact (I1 def-lines + I2 source_tables + defined_in
  variable.py:112). Script lines confirmed: L82 CASE, L155 JOIN, L156 ON,
  L160 INSERT OVERWRITE sup, L211 INSERT INTO rrcdm.

**Suggested solution (the "code evidence" method — later, after user
approval):**
1. Per-edge payload extension at L2 build time: `ref_line` (var in dst's
   def-range whose source_tables contains src) + `mech` (that var's
   `defined_in` clause). Build-time + cache-versioned (never-patch
   compliant; no render-time reconstruction).
2. Reason panel shows four blocks: flow sentence ("loan_final (L64) reads
   rollover_loan_info (L9) via LEFT JOIN at L155 (alias p6)"), the actual
   SQL lines (src def / dst def / reference site + ON line / value-use
   line) clickable → SQL panel scroll, value path for value edges, and the
   edge-type legend.
3. Graph disambiguation: same-pair edges get mechanism chips
   (`chain@9` / `computed@82` / `join@155`).
4. No graph-semantics change → Jaccard benchmark untouched; cache-prefix
   bump required for the payload format. Worked examples (A rollover→
   loan_final, B data_dt@L18→bdm@L16, C →rrcdm@L211) presented to the user
   2026-08-10; pending evaluation. No code now.

**Formal spec (2026-08-10, user asked for the formal format + new data/functions):**

Payload — new per-edge `mech` object (existing keys id/source/target/
edge_type/category/highlight_line/flow_kind/reason unchanged):
```jsonc
"mech": {
  "clause": "JOIN",            // consuming var's defined_in (JOIN|JOIN ON|WHERE|SELECT|INSERT|PARTITION|...)
  "ref_line": 155,             // first line where src is consumed inside dst's def range
  "alias": "p6",               // TABLE-typed ref var name ("" when none)
  "use_lines": [82, 156],      // other consumption lines, sorted
  "sentence": "loan_final (L64) reads rollover_loan_info (L9) via LEFT JOIN at L155 (alias p6)"
}
```
Derivation: `ref_vars = {v : src_label in v.source_tables and dst.line_start <= v.line_start <= dst.line_end}`;
ref_line = min line among TABLE-typed ref_vars else min overall; alias = that var; clause =
its defined_in; use_lines = rest; fallback (no ref_vars: write-side/def-only/alias-hop) =
clause from edge origin (DML=INSERT anchor, chain=src def line rule 5), ref_line=highlight_line.
Sentence templates per clause (JOIN/JOIN ON, SELECT/FROM, INSERT/DML via ⟐ output,
WHERE-filter, COMPUTED value, ALIAS, structural fallback) — see chat 2026-08-10.

NEW DATA (only 3 items): (1) compound node `line_start`/`line_end`/`defined_in` —
currently absent (l2_builder.py:392-400 dict has id/label/type/table_name/
variable_type/original_id/context only; per-var dicts in graph_service.py:202-203
have the lines but the compound merge drops them); keeper var supplies them
(`loan_final` CTE var L64, `bdm_acc_loan_info_sup` TABLE var L160), line_end =
next stmt anchor − 1 (`_stmt_anchor_lines` exists). (2) per-edge `mech` — only
`_src_line`/`_tgt_line` carriers exist today (l2_builder.py:659-660) and are
stripped at assembly (:1329). (3) script text — already both sides (backend file,
frontend sqlText).

NEW FUNCTIONS: `_carry_node_lines` (~10L), `_ref_site_vars` (~15L),
`_build_mechanism` + template renderer (~40L) — all build-time in l2_builder
(payload phase `_attach_flow_payload`, R25-consistent), `GRAPH_CACHE_PREFIX`
bump; frontend `EdgeReasonPanel` code-evidence block (~40L) + `SqlPanel.
scrollToLine`/`onJumpToLine` (~15L). Tests: 1 backend ground-truth invariant
(`mech.ref_line==155`, clause JOIN, alias p6 for bdm rollover→loan_final) + 1
vitest render test. Graph semantics/ids/reason string/Jaccard unchanged.

**Implementation status (2026-08-10, user approved → "implement all new
requirements"):**
- **Frontend — DONE (commit f2fa2f8, 96/96 vitest, build green):**
  `EdgeReasonPanel` renders the code-evidence block (mech.sentence +
  clickable SQL-line rows: reference site · clause, join key / value use,
  def of source; text from sqlText display-only, out-of-range →
  "(line not available)"; byte-identical fallback when `mech` absent);
  `SqlPanel` → `forwardRef` + `scrollToLine`; auto-show (R11-1) via pure
  `pickAutoEdge` util (seed zone → chain → first edge; falls back
  gracefully until backend ships compound-node line_start/line_end);
  `DataFlowApp` wiring (sqlText + onJumpToLine). Contract consumed exactly
  as specified: mech.clause/ref_line/alias/use_lines/sentence.
- **Backend — IN FLIGHT (Team E2):** `_carry_node_lines` (compound nodes
  gain line_start/line_end/defined_in from keeper vars),
  `_ref_site_vars` (pre-filter index scan: src_label ∈ v.source_tables ∧
  dst range ∋ v.line_start), `_build_mechanism` + sentence templates,
  attached in the R25 payload phase (`_attach_flow_payload`),
  `GRAPH_CACHE_PREFIX` bump, invariant test (mech.ref_line==155 /
  clause==JOIN / alias==p6 for bdm rollover→loan_final).
- Follow-up doc update pending E2/E3 completion (final payload shape +
  test evidence).

---

## Round 12 — Jaccard end-state iteration (2026-08-10, Team E1; doc + fixtures only, no source changes)

### J12-1 · Row 11 (`sup@160 → sup@160` self-loop) removed from the canonical set — degenerate direct pin

**Evidence (Team A probe + live matcher, 2026-08-10):** the row-11 pin
(`bdm+sup`, anchor 160) was the only canonical row unmatched in both seeds
(bdm E=0.8000/H=0.9231, sup E=0.7333/H=0.8571 pre-repair). The self-loop's
read endpoint is **L199** — the incremental self-read is the `LEFT JOIN
bdm_acc_loan_info_sup p2` (p2@199), not L160 — so the pin describes a
direct sup→sup edge that bypasses the ⟐ output VT: the same defect class
as the DML-routing repairs of rows 10/12/16/17/B1/C4 (no-bypass rule). The
engine never emits a table self-loop; the flow is already fully canonical
as the routed cycle E3 (`sup@160 → p2@199`) + C3 (`p2@199 → ⟐output@0`) +
row 15 (`⟐output@0 → sup@160`) — the self-loop would double-count it.

**Repair (doc + fixture, never engine):** row 11 struck in
`tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md` §8.5 with the Repair note;
both seed entries removed from `backend/tests/jaccard_canonical.py`
(CANONICAL_EDGES / CANONICAL_ROWS); the "remaining backlog" paragraph in
§8.5 deleted; Round-12 header counts updated (38 entries = 24 bdm + 14
sup). Backlog entry closed — the benchmark is now end-state on rows.

### J12-2 · X1–X5 canonization — five probe-verified genuine flows added

**Evidence (live filtered L2 output, both seeds, 2026-08-10):** five
response edges were genuine closure members the canonical set missed.
Each was matched by the live matcher BEFORE pinning, with no existing
row's match changing (candidate sets disjoint — different type prefixes
at the shared anchors 16/160/213):

| Row | Seed | Edge | Type | Anchor | Rationale |
|-----|------|------|------|--------|-----------|
| X1 | bdm | `data_dt@16 → bdm@16` | REF | 16 | FROM-line read companion of row 1's FILTER@18 |
| X2 | bdm+sup | `data_dt@160 → ⟐output@160` | REF | 160 | partition-field read redirected into the output VT (`_simplify_dml_edges` step 2) |
| X3 | bdm+sup | `⟐output@213 → data_dt@213` | SCHEMA | 213 | TOP1 output-VT membership edge (S1/S3 kind) |
| X4 | bdm | `data_dt@213 → ⟐output@213` | TABLE_FLOW | 213 | TOP1 value-write — closes the bdm side of row 17 (sup-only pin, doc closure asymmetry) |
| X5 | sup | `data_dt@225 → sup@225` | FILTER | 225 | TOP1 WHERE read companion of row 18's REF@223 |

**Result:** 38/38 canonical edges matched, 0 unmatched, all canonical
nodes realized (verified live; `_jaccard_selfverify.py`).

### J12-3 · FLOORS raised to the measured end-state values

Benchmark scores after J12-1/J12-2 (measured live, exact): **bdm
1.0000/1.0000/1.0000** (nodes/edges/highlights), **sup 0.9000/1.0000/
1.0000**. `FLOORS` in `backend/tests/test_jaccard_benchmark.py` raised to
these values. The sup nodes score stays 0.9 while the rrcdm node carries
the extra non-canonical DML phantom `data_dt` — the R11-2 duplicate — and
moves to 1.0 when the engine lands the R11-2 Sync-2 dedup fix (R11-2
above; Team E2/E3 in flight). The three existing invariants (hl ≥ 1, all
canonical nodes realized, summary print) are kept.

### J12-4 · Field-uniqueness invariant added (R11-2 regression guard)

The naive (parent, label) uniqueness over ALL fields is impossible: the
sup seed legitimately repeats `(sup, data_dt)` twice (C-9 per-statement
dedup key `(parent_table_id, label, stmt_idx)` — source-side fields may
repeat across statements). The new invariant scopes to the Sync-2 DML
phantom set only (id prefix `dml_`): no duplicate (parent, label) pairs
— a target table's column display must show each column once. Currently
FAILING on both seeds (the rrcdm `data_dt` × 2) — by design, until the
engine R11-2 fix lands; it is the single remaining benchmark failure and
the R11-2 acceptance check.

### J12-5 · b3 pin rewritten to extraction-attributed ownership

`test_b3_subquery_scope_field_parents_under_its_subquery` (test_b_series_l2.py)
pinned the old Bug-31 bulk-SCHEMA behavior (every subquery node carries
fields). Probe-verified actual ownership (2026-08-10): ⟐ subq1 →
{lending_ref}, ⟐ accu/subq3 → {data_dt}, ⟐ branch/subq4 → {MAXp_dt}, ⟐
subq / ⟐ subq2 / ⟐ p2 → no fields (their outputs resolve to the physical
bdm_acc_loan_info at extraction — I2 exact source_tables), and the
rollover CTE's `loan_maturity_dt` parents under the bdm_acc_loan_info
compound. Scope-existence asserts kept; docstring notes the 2026-08-10
pin update.

### J12-6 · X3 removed from the canonical set (E3a fix-3 DML-target attribution)

E3a fix 3 (INSERT-target columns attribute to the DML target table,
`rrcdm_job_log_exec_par`, instead of the synthetic ⟐output VT) reparented
`data_dt@213` — the TOP1 output VT no longer holds a data_dt member, so
canonical X3 (`⟐output@213 → data_dt@213`, SCHEMA, the S1/S3-kind
output-membership edge pinned 2026-08-10) has NO post-fix counterpart.
Evidence (E3a cold-cache matrix M1–M4, `rm graph_*` + rebuild per matrix
cell): X3 was the sole unmatched row pre-repair and the only gate-breaker
was fix 3 — the versionless graph cache had contaminated the earlier
"stale canonization" reading (E2's conclusion, exonerated). Repaired in
the DOC (§8.5 strike-through) + fixture (`jaccard_canonical.py` point 8,
X3 removed both seeds) — never the engine; the canonical write edge
`data_dt@213 → ⟐output@213` (X4 / row 17) is unchanged. Final B set:
23 bdm + 13 sup = 36 entries; gate GREEN at bdm E=1.0000 / sup E=1.0000;
full suite 702 passed / 0 failed. Also landed with the repair: the
l2_builder graph cache is stamped `extractor_version` (build-time stamp +
load-time mismatch → miss, mirror of the analysis-cache check) so
extraction-semantics changes can never serve stale graphs again
(commits 2a45709 E3a, 9566140 repair).

### J12-7 · Round 12 engine-side records (teams E2/E3a/E4)

- **E2 (b793336)**: R11-2 Sync-2 phantom exists-check dedup by
  (target, label) — dropped the `orig_stmt` term; R11-3 mech payload
  (per-edge `mech = {clause, ref_line, alias, use_lines, sentence}`,
  compound-node lines, `_ref_site_vars` derivation); adapter
  parse_errors + `alias_of`; E1 1c gates (src.context direct + cross
  writer-vs-reader order guard); N8 `_safe_int`; C-5 case-insensitive
  star exclusion; `test_mech_payload.py` invariant.
- **E3a (2a45709)**: 6 walker/lineage gaps from the case sweep —
  `_walk_update` (UPDATE SET targets as fields), `_split_hive_multi_inserts`
  (FROM-led multi-insert arms), INSERT-target attribution (fix 3, see
  J12-6), comma-join CTE attribution guard, `_walk_merge`
  (`merge_target` in `_table_like`), PARTITION seed scoping
  (`source_tables[0] == target_table`); also carried E2's uncommitted
  lineage changes (L1 REF/READ gate + D1 cap log) per its report.
- **E4 (72e9e25)**: probe-verified path traversal on level2 `script`
  (arbitrary file read + cross-tenant) closed by resolve_script +
  `is_file()` containment; async handlers running the sync pipeline
  froze the event loop (~40 min stuck service) — handlers moved to
  threadpool `def`; autocomplete `type` whitelist (cross-workspace
  read); /highlight 404; dataflow graph cache stamped extractor_version;
  view-persist `_views_lock` + `_atomic_write_text`; `_load_views`
  corrupt → []; logger stderr backpressure env-gated.
- **Backlog (deferred, recorded)**: "Jaccard 4-decimal tolerance"
  → J12-12 (scoring replaced by the recall/precision pair — A=B
  semantics; the tolerance problem dissolves by construction);
  **Issue 1** (L2 edge-click viewport refit, frontend — analysis in
  the Issue 1 section below; fix decided 2026-08-11: constant height
  pre-drag + drag-to-resize handle),
  **Issue 2** (L2 "3 parallel lines, 1 inverse" — the inverse edge is
  the DML write leg, mis-styled as a chain; analysis in the Issue 2
  section below; **fix DECIDED 2026-08-11: A — extractor-side DML
  output→target edge, validated by simulation; benchmark blind spot:
  the gate cannot see the kind flip (anchor/type unchanged) — needs
  the R19.3 path-level assertions to pin it**),
  **Issue 3** (L2 missing the bdm → rrcdm / sup read chain — bare FROM
  refs get no source_tables → read edge only as a non-walkable SUBSET
  bridge; analysis in the Issue 3 section below; fix = extractor
  source_tables for bare refs + closure admission; verified at raw
  level),
  3 frontend nits (Show-All cached-branch banner staleness,
  parentViewIdRef phantom parent after view delete,
  window.__cy/__cy1 globals — fixed in ce83f57, to be struck from
  this list). Former entries superseded by user rulings: "hl=0 clamp"
  → J12-8 (restart-time cache purge); "substring seed match" → J12-9
  (exact match confirmed, matcher simplified to one predicate);
  "L1 cache perf" → J12-11 (deferred by ruling — file reuse kept,
  memory reuse only when a real perf issue appears);
  MERGE_TARGET keeper merge (#7), floating fields/parenting (#8/#9),
  dml_dml_ proxy chaining (#12) → **J12-10 further work** (Physical
  Model Layer design, dissolves them by construction — see
  wiki/SOLUTION_DESIGN.md).

### J12-8 · Restart-time cache purge (user ruling 2026-08-11) — closes the hl=0 item

**Decision (user's solution, ruling 2026-08-11)**: on every container
start (docker restart / new deploy), ALL cached files are removed. The
service does not promise to keep user data; the caches exist only to
save rebuild time, and redoing that calculation after a restart is
accepted ("But it is OK"). Simple — no version marker, no gating.
Execute later, batched with the other backlog items.

**Why it closes the hl=0 item**: probe evidence (2026-08-11, 457
scripts) — the engine never produces `line_start < 1`; a served
`highlight_line: 0` can only arrive from a stale/corrupt cache carrier.
Wiping the caches at restart removes that only source entirely. The
previously drafted hl=0 clamp (`/tmp/hl0_ban_draft.patch`, 402 lines,
`_safe_int` default 0 → None, verified 705 passed) is superseded by
this ruling as the fix; the draft stays on disk as optional contract
hardening (a served `highlight_line` is always ≥ 1), not part of this
solution.

**Implementation sketch (for the batch)**:
- Hook: FastAPI lifespan startup (`backend/app/main.py:27`) — runs on
  every process start; `docker restart` triggers it.
- Scope: `WORKSPACE_ROOT` (`/tmp/workspaces`, named volume
  `workspace_data` — survives container recreation, so a startup hook
  is the correct place; an image-build purge would not reach the
  volume) → each `{ws_id}/cache/` → delete the cache-prefixed files
  (`graph_*`, `analysis_*`, `schemas_*` `.json`). Never `views.json`,
  never user scripts/samples.
- Existing stamps stay as-is (format_version + extractor_version) —
  they remain the read-time backstop for anything that slips through
  between restarts.
- Consideration to confirm at execution: the dev compose runs uvicorn
  `--reload`, which re-runs lifespan on code edits → purge on every
  dev save. Acceptable in practice (dev workspaces are small), or gate
  the purge on a reload-detection env flag if it becomes annoying.
  Production (`release.sh` image) has no reload, so it purges exactly
  on restarts/deploys as intended.
- Executed 2026-08-11 (v3.3.151): the reload question resolved WITH a
  gate — the dev container runs `--reload` (verified: Cmd has
  `--reload`), and every code save wipes caches under the naive hook,
  so the purge is gated by a marker file in the workspace volume
  (`/tmp/workspaces/.cache_purge_marker`, survives container
  recreation; never swept — cleanup/purge only descend into dirs).
  Marker content = `hostname|pid-of-process-1|pid-1 starttime` (field
  22 of /proc/1/stat; the pid NUMBER is always 1 in a container, the
  starttime carries the instance identity). The purge runs only when
  the marker differs from the current identity, then rewrites it.
  Verified live (uvicorn 0.51 --reload): a real StatReload worker
  restart keeps pid-1 starttime and does NOT purge (dummy cache files
  survived); docker restart spawns a new pid-1 → purge → marker
  rewritten. Side benefit: in-process TestClient lifespans (test
  suite) no longer wipe live caches either.

### J12-9 · Seed matcher simplification — exact match confirmed, 5 paths → 1 predicate (user ruling 2026-08-11)

**Ruling**: seed matching uses **exact match on `table.field`** —
substring matching is NOT adopted. This closes the former "substring
seed match" backlog item. No further design needed.

**Evidence** (probe 2026-08-11): analysis-cache `source_columns`
entries are bare field names (`'lending_ref'`, `'podcg'` — never
`table.field`), so the `target_full in sc` substring path can never
fire — dead code; no live substring path exists in the matcher today.

**Simplification decision**: the 5 match paths at l2_builder.py:196-213
decompose into ONE exact-field-part predicate:
`value.rsplit(".", 1)[-1] == field`, applied to the node label and to
each `source_columns` entry. Reasoning: "table.field" is itself a
dotted label, so `name == target_full` (path 1), `name == field`
(path 2) and suffix-after-dot (path 3) are all one rule — the unified
rule is a strict superset, behavior-identical. Path 4 (`target_full
in sc`) is dead → deleted. Path 5 (`_target_field_sc(sc, field)`) is
the same suffix rule on `source_columns` → helper redundant (retired
with the H2-era NameError history). The vt whitelist
(`column/cte_column/expression/aggregate/window/case/transform/
literal`) duplicates `FIELD_LIKE_TYPES` (already imported in
l2_builder) → reuse. Net: ~15 lines → ~5, one helper, **no substring
anywhere** (R4 invariant, doc line 2137: short names must never match
inside longer ones).

**Kept semantics — do NOT narrow**: field-only labels (`data_dt`) and
alias-qualified labels (`p1.data_dt`) must keep matching a search for
`bdm_acc_loan_info.data_dt` — the alias-copy seed depends on it (doc
line 3055: "data_dt seeds 1→3 = physical + alias copy + target
partition, all is_target"; `p1.data_dt` matches only via the suffix
rule). Narrowing to literal `name == target_full` would drop the
alias copy, seeds 3→2, and **regress the Jaccard gate**.

**Batch**: implement together with J12-8; verify behavior-identical —
run `test_jaccard_benchmark.py` before/after; bdm/sup node Jaccard
must be unchanged.

**Executed 2026-08-11 (v3.3.151)**: verified already landed — the
collapse shipped in 307cd01 and was carried through the J12-10
stage-3 refactor (034eaa2, physical-model seed search) with identical
semantics: the matcher is ONE exact field-part predicate
(`value.rsplit(".", 1)[-1] == field`) applied to the node label and to
each `source_columns` entry (node-carried fallback when the model is
absent), gated on `FIELD_LIKE_TYPES`; the old paths (`name ==
target_full`, `name == field`, `target_full in sc`, `_target_field_sc`)
are gone and no substring matching exists anywhere. Both MUST-KEEP
semantics hold: field-only labels (`data_dt`) and alias-qualified
labels (`p1.data_dt`) match a `table.field` search via the suffix
rule. Behavior-identical verification: Jaccard gate before/after
identical (1 passed, floors bdm 1.0/1.0/1.0, sup 1.0/1.0/1.0); full
suite before/after identical in pass/fail (the 797→796 collected-case
delta in the after-run is the concurrent R26.3 mech-payload test
removal, unrelated to the matcher).

### J12-10 · Physical Model Layer — design proposal, further work (user ruling 2026-08-11)

User-approved direction: introduce a **physical layer** between the
syntax layer (per-occurrence vars/deps) and the display layer (L2) —
one entity per physical table and per physical field, built at
extraction time; data flow (walk/closure/seed) built FROM this layer;
the display becomes a pure projection. Root cause it addresses: the
display layer today synthesizes physical identity at render time
(label-keyed keeper merge, seed_/sync_/dml_ proxy copies, alias nodes,
merge_target/table split) — all reconstruction machinery that the
never-patch rule opposes.

- **Full design**: `wiki/SOLUTION_DESIGN.md` § J12-10 (entities,
  consumer changes, what does NOT change, migration stages 1-4 each
  gated by the Jaccard benchmark, risks, verification targets).
- **Supersedes as further work**: backlog items #7 (MERGE_TARGET
  keeper merge), #8/#9 (floating fields/parenting), #12 (dml_dml_
  proxy chaining) — the physical layer dissolves them by construction;
  they are NOT in the current batch, they await this design.
- **Not in the current batch** (J12-8/J12-9 + small items); multi-round
  refactor, staged and gated. The Jaccard gate is the safety net.

### J12-11 · L1 memory reuse of analysis caches — deferred by ruling (user ruling 2026-08-11)

**Decision**: keep the existing FILE reuse of `analysis_*.json`
(intermediate extraction files read from disk per request) — do NOT
implement memory reuse at this stage. Rationale (user's judgment,
agreed): the measured ceiling is ~27 ms per L1 request on the
heaviest workspace (99 scripts / 5.4 MB); typical workspaces are
~44 KB (sub-ms); this is not user-facing at the current stage, and
memory reuse adds real source complexity (per-workspace caches,
signature invalidation — the exact class of stale-cache bug this
project has been bitten by before). The J12-10 physical layer will
restructure the enrichment path anyway.

**Condition to fix (recorded trigger)**: implement memory reuse ONLY
when a real, measurable performance issue appears that traces to the
analysis-cache re-read — e.g. L1 request latency dominated by the
re-read (hundreds of scripts × slow volume storage, or concurrent
load). The design is already recorded: memoize `analysis_cache_map`
per `ws_id` keyed on cache-dir file-set/mtime (`l1_builder.py:460-468`);
same pattern for `graph_*.json` as an LRU of hot scripts (L2 path);
each invalidated by file-set signature. Freshness + restart-cleanup
follow the J12-8 purge philosophy.

**Measured evidence (2026-08-11, live container)**: 312 analysis
files / 7.4 MB across 169 workspaces; avg file 23.6 KB, max 345 KB;
per-file read+parse 0.087 ms; biggest workspace 99 files / 5.4 MB /
27.5 ms for the full set. (For comparison: 750 graph files / 169.6 MB
/ avg 226 KB — ~1 ms per L2 request; schemas files negligible.)

### J12-12 · Benchmark scoring: Jaccard → recall/precision pair, A=B semantics (user ruling 2026-08-11)

**Decision**: replace the Jaccard score (`ni / (na + nb - ni)` at
`test_jaccard_benchmark.py:165-167`) with the two-sided equality pair:
recall = `|A∩B| / |B|` ("did we lose any canonical item?") and
precision = `|A∩B| / |A|` ("did we emit any junk?"). **A = B ⟺
recall = precision = 1.0** — the score is "near 1" exactly when the
response equals the canonical set (user's proposal: score near 1 iff
A=B, instead of intersection/union). One-sided measures are the right
tool because B is authoritative ground truth, not a fuzzy peer set.

**GUARD (user ruling 2026-08-11): "A = B" is genuine SET EQUALITY —
mutual membership, never |A| = |B|.** Equality is the AND of both
directions: recall = 1.0 ⟺ B ⊆ A, precision = 1.0 ⟺ A ⊆ B (both
= 1.0 ⟺ A = B). Never collapse to a cardinality check: A = {x},
B = {y} have equal sizes but recall = precision = 0; A = canonical
minus one plus one junk node has |A| = |B| but recall = precision =
8/9. The implementation must compare membership, not sizes.

**Why it is better than Jaccard** (all verified against the live
code):
1. **Separates the two failure modes.** Jaccard conflates "lost a
   canonical item" and "emitted an extra non-canonical item" into one
   number. Example: sup nodes today have 1 documented extra
   (9 canonical + rrcdm phantom). Losing one canonical node too:
   Jaccard 0.9 → 0.8 (ambiguous); pair recall 1.0 → 0.889, precision
   0.9 → 0.889 (both directions visible).
2. **Makes today's floors honest.** The old floor comment was already
   a precision story ("sup nodes stay 0.9 while the rrcdm node carries
   the extra non-canonical DML phantom data_dt"). Re-derived floors,
   identical pass/fail today:
   - bdm: recall 1.0/1.0/1.0, precision 1.0/1.0/1.0 (N/E/H)
   - sup: recall 1.0/1.0/1.0, precision **0.9**/1.0/1.0 (N/E/H)
   Recall floor 1.0 everywhere = "losing a canonical item is never
   OK" — a rule Jaccard could not express. Precision moves to 1.0
   when the R11-2 Sync-2 dedup lands (already documented).
3. **Kills the 4-decimal tolerance item entirely.** Steps are exactly
   1/|A| and 1/|B| — ≥ 0.11 for nodes (|B|=9), ~1/300 for edges —
   far above the ±0.00005 rounding band; no masking, `round(j,6)` no
   longer needed (rounding becomes cosmetic, kept for display).

**Scope (batch item, replaces the "Jaccard 4-decimal tolerance"
entry)**: `test_jaccard_benchmark.py` — counts unchanged; scoring +
FLOORS restructured per direction (R/P), report prints both, one
assertion per direction; `jaccard_canonical.py` — conventions note
(scores: recall/precision); bug-list entry + floor comment updated.
Test + doc only — zero engine risk; verify same pass/fail today
(sup precision nodes 0.9 ≥ 0.9 floor) + full suite green.

### J12-13 · Benchmark evaluation defect — the fixture is circular (root cause established 2026-08-11, user investigation)

**Question answered**: "Why is there such a wrong fixture?" — the
canonical fixture was compiled FROM THE ENGINE, never from the doc's
requirement sections. Four compounding steps, each innocent alone,
together circular:

1. **The doc itself is engine-anchored.** Header
   (tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md:4-6): "All facts below
   were verified by **running the live extraction** (v3.3.145,
   2026-08-07) and by reading the SQL." The reference records what the
   engine does; only §4.2 LAYER-2 (line 134: `sup ─► rrcdm (read L223 →
   INSERT L211)`) and §4.3 MISSING (items 3/4) record the ideal.
2. **The fixture was compiled from §8.5 — the engine-mirror table —
   then "self-verified".** Docstring (test_jaccard_benchmark.py:6-9):
   "compiled from … §8.4/§8.5 and **self-verified against the served
   output** on 2026-08-10". §8.5 is the only machine-readable table and
   was "**probe-pinned** 2026-08-10" — pinned BY probing the engine.
   The requirement sections are prose marked "all verified absent by
   probe — the graph defects" → rows the engine can't emit read as
   "defects to fix later", never as expected answers. MISSING items 3/4
   (output@0→sup DML edge; sup@160→sup@223 write→read link) never
   became fixture rows.
3. **Even the present rows encode the engine's shape, not the doc's
   chain.** Rows 15/16 = the DML-routed form (`⟐output@0 → sup@160`,
   `⟐output@0 → rrcdm@211`); the LAYER-2 chain `sup ─► rrcdm (read
   L223)` has NO row; the write→read link has NO row; row 18's read
   (`data_dt@225 → sup@223`) exists only for the sup seed because only
   the sup closure contains both endpoints (the bdm closure excludes
   `sup@223` — Issue-3 gap — mirrored into the fixture).
4. **Round-12 convergence finished the job.** Every repair ("iterate
   until matched == all rows", "repair the doc with evidence") resolved
   each unmatched row toward the engine with engine-probe evidence
   (rows 10/C4 merged, 12/16/17/B1 re-pinned to DML-routed form, row 11
   removed, X1-X5 canonized). Convergence was real — against a
   yardstick already bent to the thing it measures.

**The circularity**: B ← compiled from §8.5 ← probe-pinned against the
engine ← validates A (the engine). The gate compares the engine with
itself; the "self-verified against the served output" step is the red
flag, not the confirmation. The doc internally contradicts itself on
exactly the middle segment — §4.2/§4.3 (chain exists, items 3/4
missing) vs §8.5 ("the closure is complete — not a subset") — and the
fixture compiler followed the doc's structure: requirements demoted to
"MISSING", engine output promoted to "ground truth table". Green
pass/fail never pushed anyone to read both sections.

**Repair (already recorded, see J12-13 §4 in wiki/SOLUTION_DESIGN.md)**:
re-derive the bdm rows from the REQUIREMENT sections — the write→read
link `sup@160 → sup@223` and the read at L223 become required rows;
the gate stays RED until Issues 2 and 3 land. That is exactly the
R19.3 path-level assertions: doc LAYER-2 list as evidence, fixture
finally measuring what the doc demands instead of what the engine
emits.

**USER RULING 2026-08-11 — "strictly use the ground truth in the
benchmark"**: B must be derived from the doc's REQUIREMENT sections
(§4.2 LAYER-2 chain, §4.3 MISSING list), never from the engine's
emitted form. Concrete change set (test+doc only, zero engine code):
(1) row 15 type TABLE_FLOW → DML (MISSING item 3 — the output→sup
write leg must be DML); (2) NEW row `sup@160 → sup@223` (both seeds,
anchor 223 — MISSING item 4 write→read link, LAYER-2 line 134);
(3) NEW row `data_dt@225 → sup@223` REF for the bdm seed (row 18 is
sup-only today). KEPT as design-correct: DML-routed hops 12/16/17/
B1/C2/C3 (DML-routing design, R19.6b), row-11 removal (self-read is
the L199 LEFT JOIN, SQL-verified), X1/X2/X4/X5 + S/B/C/E canonized
flows. GATE: add the R19.3 path-level assertion — per seed the
complete source→target chain must route THROUGH the reader instance
(`… → output1 → sup@160 → sup@223 → output2 → rrcdm@211`); the DML
WRITE_READ bypass alone fails. CONSEQUENCE (intended): the gate flips
RED on the bdm edge set until Issues 2/3 land; floors re-derived when
the fixes land.

### Issue 1 · L2 edge click → viewport refit (frontend, FIXED 2026-08-11 — Wave 1D)

**Symptom** (user report 2026-08-11): clicking an edge in L2 shows the flow
reason, but the L2 graph viewport automatically re-fits to a new scale,
making it hard to see which edge was clicked.

**Root cause — full verified chain** (read-only analysis, no code changed):
1. Edge click → `handleEdgeClick` → `setSelectedEdge`
   (DataFlowApp.jsx:381-382). `graphData` state reference is UNCHANGED →
   the cytoscape instance is NOT recreated (that obvious suspect is ruled
   out; the effect deps are `[graphData, containerRef]`,
   useCytoscapeGraph.js:147).
2. EdgeReasonPanel changes HEIGHT on click: empty state
   `.edge-reason-panel` = `height: 92px` (fixed, app.css:347-357);
   with the R11-3 `mech` payload (now on EVERY edge, v3.3.149) it becomes
   `.edge-reason-with-evidence` = `height: auto; max-height: 260px`
   (app.css:386) → grows ~30–170px per click (shrinks back on background
   tap via `clearEdgeSelection`).
3. `.panel-inline-l2` is a flex column (app.css:742-750). resizable.css
   loads AFTER app.css (DataFlowApp.jsx:15) and wins the cascade:
   `.inline-l2-graph` = `flex: 1 1 0%; min-height: 60px; overflow: hidden`
   (resizable.css:106-110; overrides app.css's `height: 400px;
   flex-shrink: 0`) → the graph area shrinks by exactly the panel's growth.
4. The ResizeObserver on `.graph-canvas` (DataFlowGraph.jsx:73-93) fires
   on ANY size change → 200 ms debounce → `fit(pad)` → cytoscape `fit()`
   reframes the whole graph → zoom/pan reset → the clicked edge's screen
   position is lost.

The auto-fit was designed for genuine panel/window resizing (Bug 4
adaptive padding) but has NO guard distinguishing user resize from
internal sibling-induced reflow. The reason panel is the only internal
reflow source (the no-match/parse-error banners are absolutely
positioned — no reflow).

**Fix (user ruling 2026-08-11): constant height pre-drag + drag-to-resize
handle — Option B + user control; supersedes A and C**:
- The panel has a **constant height in every state** (empty / simple /
  with-evidence) UNTIL the user drags: the height is state
  `reasonPanelHeight` (like `sqlPanelHeight`), default ~150–180px, min
  60, generous max (the graph's own `min-height: 60px` is the flex
  backstop). Content-driven height changes are impossible → edge click
  never changes the panel height → no flex reflow → the RO never fires
  on click → no viewport refit. After a drag the height is user-set —
  still constant across clicks (invariant: height changes only when the
  user drags).
- **Drag handle**: `useResizable({direction: 'vertical', ...})` — the
  same hook the SQL panel uses; handle bar on the panel's TOP edge
  (between SQL panel and reason panel). Dragging squeezes the GRAPH
  (the flex-1 item that gives up space) → live resize + the debounced
  RO auto-fit during the drag — identical to today's SQL-panel handle
  behavior (desired). The remaining RO firings are all genuine user
  resizes → **Fix A (fit-on-drag-end guard) no longer needed**.
- **CSS**: base `.edge-reason-panel` height = the state value; delete
  `height: auto; max-height: 260px` from `.edge-reason-with-evidence`;
  keep `overflow-y: auto` → long evidence scrolls internally. Empty
  state renders the same default height → first click: zero change.
- **Semantics change**: R10-#18's "reason panel grows with the
  code-evidence block" becomes "grows by user drag" (update that
  comment in the fix). State not persisted (R23 clean start,
  consistent with the SQL panel).

**IMPLEMENTED 2026-08-11 (Wave 1D, frontend)** — Option B + user control exactly as ruled:
constant `reasonPanelHeight` state (default ~150-180px) in every state; drag handle on
the panel's top edge via the same `useResizable` hook as the SQL panel; `height: auto;
max-height: 260px` deleted from `.edge-reason-with-evidence` (overflow-y: auto keeps
long evidence scrollable internally); R10-#18 comment updated to "grows by user drag".
Invariant verified in code: height changes ONLY on user drag → edge click never changes
panel height → no flex reflow → the ResizeObserver fit never fires on click → no viewport
refit. Code comments in DataFlowApp.jsx carry the "Issue 1 (fix 2026-08-11)" marker.
State intentionally not persisted (R23 clean start).

### Issue 2 · "3 parallel lines, 1 inverse" — the inverse edge is the write leg, mis-styled as a chain (backend, FIXED 2026-08-11 — Wave 1B, Fix A)

**User question** (2026-08-11): "In L2, the edge direction should be in the
data flow direction. When there are three parallel lines between the same
two tables, one edge is inverse to the other two. Why? Does it make sense?"

**Answer: it makes sense — both patterns' "inverse" edges are real and
correctly directed; the sup pattern additionally exposes a genuine payload
inconsistency (the write leg renders as a chain instead of a write), which
is exactly why it *reads* as a wrong-direction flow line.**

#### Pattern B (bdm_acc_loan_info_sup ↔ ⟐ output) — the self-read + self-write INSERT OVERWRITE

Three parallel edges (verified live, benchmark build path, seed
bdm_acc_loan_info/data_dt):

| edge | type | kind | meaning |
|------|------|------|---------|
| `sup.data_dt → output` | REF | read | sup read as `p2` (previous-day partition, `p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` @L159) |
| `sup.data_dt → output` | TABLE_FLOW `_value` | write | P17 — the searched field's VALUE column feeding the INSERT result set |
| `output → sup` | TABLE_FLOW | **chain** | the WRITE leg — the SELECT's output VT feeds the INSERT OVERWRITE target |

The statement (L150-208) is `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup …
SELECT … FROM loan_final p1 LEFT JOIN bdm_acc_loan_info_sup p2` — sup is
BOTH the write target (today's partition) AND the read source (yesterday's
partition via p2). The "inverse" edge IS the genuine write leg: data really
does flow `output → sup`. Semantically 100% correct.

**Why it renders as a chain (the inconsistency, full verified chain)**:
1. `dependency_graph.py` Phase 1c (:132-157): per-source-column DML edges
   into each DML target. `⟐ output` has NO `source_columns` (probed:
   n_src_cols=0 in both TOP0 and TOP1) → never in `src_vars`.
   - TOP0 (sup, 55 vars, 15 with source_columns): the src_vars branch
     fires → DML field edges (`p1.internal_key → sup`, …) → **no
     `DML output → sup` edge exists**.
   - TOP1 (rrcdm, 13 vars, **0** with source_columns): src_vars empty →
     the 1c fallback (:153-157) picks ctx_anchor = the `⟐ output` VT →
     **`DML output → rrcdm` IS created**.
2. Phase 1c-extra2 (:172-179) always adds `TABLE_FLOW output → target` for
   every DML target → raw `TABLE_FLOW output → sup` (TOP0) AND
   `TABLE_FLOW output → rrcdm` (TOP1) both exist.
3. L2 `_simplify_dml_edges` (l2_builder.py:1009-1021) rewrites **raw DML**
   edges → `output → target` stamped `_dml_origin=True` (id `_dml_out`)
   → `_flow_kind` = 'write' (highlight_strategies.py:51-55, §8.7 rule 3).
   - rrcdm: the raw DML edge triggers the rewrite → `l2e_…_dml_out`
     (write, hl=211) — the surviving 1c-extra2 TABLE_FLOW twin is
     suppressed by the same machinery (no chain twin in the output).
   - sup: no raw DML edge exists → the 1c-extra2 TABLE_FLOW survives
     unstamped (`l2e_8bc2dd7b554e`, kind=chain, hl=160) → **§8.7 rule 3
     violation: a DML target's write leg renders green-solid like a read
     instead of blue-double like a write** — the root of the user's
     "wrong direction" reading.

**Fix options** — **RULING 2026-08-11: Fix A chosen** (user: "Let us use A
solution"):
- **A (DG-side — DECIDED, builds on extraction-time info)**: Phase 1c
  emits `DML output → target` whenever the statement has exactly one
  output VT AND the fallback branch did not already create it (i.e. the
  src_vars branch fired). Every DML target then gets the DML edge → the
  L2 rewrite stamps it uniformly → the write leg renders 'write'.
- **B (narrow, REJECTED)**: stamp `_dml_origin=True` in
  `_simplify_dml_edges` on surviving unstamped output→target TABLE_FLOW.
  Display-layer patch for an extraction-layer defect — the raw graph
  keeps saying TABLE_FLOW for sup while DML for rrcdm; every future
  raw-graph consumer re-hits the asymmetry (never-patch principle).
- Pattern A (below) needs NO fix — direction is by design.

**Fix A — validated end-to-end by simulation 2026-08-11** (adapter-level
monkeypatch adding the DML edge at the Phase-1c position, fresh ws ids to
bypass the graph cache; seed bdm_acc_loan_info/data_dt, filtered L2):

| edge (output→) | BASE (today) | FIX_A (simulated) |
|---|---|---|
| `→ sup` | flow_kind='chain' id `l2e_8bc2dd7b554e` | **flow_kind='write'** id `l2e_3b8e8e62b668_dml_out` |
| `→ rrcdm` | flow_kind='write' (unchanged) | flow_kind='write' (unchanged) |

Mechanics verified: (1) the filter keeps BOTH the DML edge and the
1c-extra2 TABLE_FLOW twin (same endpoints, both in the closure); (2)
`_simplify_dml_edges` rule 3 rewrites the DML edge to the stamped
`_dml_out` form; (3) `_dedup_edges` keeps the FIRST occurrence
(l2_builder.py:1072-1082) → **the fix must add the DML edge in Phase 1c,
BEFORE 1c-extra2, or the unstamped twin wins**. Probe pitfalls recorded:
appending the edge at deps end loses the dedup race; re-using a ws id
serves the cached graph (fresh ids mandatory).

**Cleaner formulation for batch time**: instead of adding a second edge
in the src_vars branch, flip 1c-extra2 itself (:172-179) to emit
`DML` instead of `TABLE_FLOW` for the output-VT→DML-target edge — the
edge IS by definition the write leg; the src_vars/fallback DML edges
already cover the duplicates and `_add_edge` dedup absorbs overlap.
Same end state, one line, no ordering dependency.

**Pattern B Jaccard note** (verified 2026-08-11): the canonical rows
match by (anchor line, type prefix, endpoints) — Fix A changes NONE of
those keys (anchor 160, type TABLE_FLOW both before/after; only the
derived flow_kind flips) → **the benchmark cannot see this fix**. The
kind flip must be pinned by the R19.3/R20 path-level assertions
(J12-13 §4), not by the existing rows. Sup nodes floor stays 0.9
(R11-2 phantom, parked per the benchmark docstring).

#### Pattern A (bdm_acc_loan_info ↔ p1@29 / p1@84) — the SCHEMA containment edge

Three parallel edges between the physical bdm node and the alias node
p1@29: `ALIAS bdm → p1@29` (chain — physical → alias), `REF
bdm.data_dt → p1@29` (read), and `SCHEMA p1@29 → bdm.data_dt`
(structure, hl=43 — `structure — ‖p1@L29 → p1.data_dt@L43‖`). The inverse
one is the SCHEMA edge: an alias-membership/containment edge whose
direction is owner → member **by design** (table → its field), not data
flow. The member's field node renders on the PHYSICAL table's rectangle
(field dedup key `(parent_table_id, label, stmt_idx)` — alias nodes carry
no own field copies), so the arrow visually points "backwards" from the
alias into the physical table. The ground truth is endpoint-blind for
SCHEMA (jaccard_canonical.py `anchor_rel`, S1/S3 rows) — direction never
mattered to the benchmark. Semantically correct; visual-only confusion.
No fix proposed; a future display tweak (e.g. distinct arrowhead for
structure edges) could clarify.

**IMPLEMENTED 2026-08-11 (Wave 1B, backend) — Fix A via the cleaner formulation**:
Phase 1c-extra2 (dependency_graph.py:172-179) now emits `DML` instead of `TABLE_FLOW`
for the output-VT→DML-target edge — the edge IS the write leg by definition; the
src_vars/fallback DML edges cover the duplicates and `_add_edge` dedup absorbs overlap
(no ordering dependency). **Verified LIVE 2026-08-11 via probe through the real build
path** (fresh workspace, filtered L2, seed bdm_acc_loan_info/data_dt):
`l2e_3b8e8e62b668_dml_out: output → bdm_acc_loan_info_sup | TABLE_FLOW kind=write hl=160
reason="write (write leg)"` and `l2e_73632d4f7c7a_dml_out: output →
rrcdm_job_log_exec_par | TABLE_FLOW kind=write hl=211` — both write legs render as
blue-double writes; the old unstamped chain twin (l2e_8bc2dd7b554e) is gone. Gate-neutral
as predicted (anchor 160/211 + type TABLE_FLOW + endpoints unchanged; only the derived
flow_kind flips) — the kind flip is pinned by the R19.3/R20 path assertions; gate green
(702 passed).


### Issue 3 · L2 missing the bdm → rrcdm chain: bare FROM refs get no source_tables — the sup read leg exists only as a non-walkable SUBSET bridge (backend, FIXED 2026-08-11 — Wave 1B, Fix A)

**User question** (2026-08-11): "How does the data flow from
bdm_acc_loan_info to rrcdm_job_log_exec_par? The L2 does not show this."
Follow-up ruling asked: is the ground truth wrong?

**Verdict: the ground truth is NOT wrong — the engine display is.**
The script genuinely flows to BOTH tables, and the canonical already
expects it: bdm closure rows 15 (`output@0 → sup@160`) and 16
(`output@0 → rrcdm@211`); sup closure rows 16 (`output@0 → rrcdm@211`),
18 (`data_dt@225 → sup@223` REF — the statement-2 read) and B1
(`sup@223 → output@0` SUBSET bridge). True chain:
`bdm → rollover/loan_final CTEs → output1 → sup (INSERT OVERWRITE write
@L160) → [statement 2 reads sup @L223] → output2 → rrcdm (INSERT @L211)`.

**Root cause (byte-level verified)**:
1. `_register_table` (variable_extractor_v2.py:1722-1725) registers the
   BASE table var for a bare `FROM`/`JOIN` reference (no alias) WITHOUT
   `source_tables` (defaults []); the alias var (:1757-1761, which carries
   `source_tables=[name]`) is only created when an alias exists. Statement
   2's `FROM bdm_acc_loan_info_sup` (L223) is bare → the TOP1 sup var has
   `source_tables=[]` (probed) while TOP0's aliases p1/p2/p3 are populated.
2. Phase 1a (dependency_graph.py:100-121) gates on `if not
   v.source_tables: continue` (:117); Phase 1c-extra (:161-170) gates the
   same way (:166) → the bare reference produces NO `sup → output` raw
   edge. The read is represented only by the SUBSET bridge (phase 7/8,
   ungated) and the 1c-cross DML WRITE_READ (`sup(TOP0) → rrcdm` @L211,
   :181-236) — both lost or degraded in the filtered L2: the bridge is
   never-walkable by design (design 14) and renders kind=bridge; the DML
   WRITE_READ is consumed by `_simplify_dml_edges` into `output → rrcdm`
   (write, hl=211).

**Fix A (extractor-side, preferred — builds on extraction-time info)**:
`_register_table` sets `source_tables=[name]` for bare FROM/JOIN refs
(NOT DML targets — avoids spurious target→output edges). Simulated
end-to-end (adapter monkeypatch, 17 bare refs fixed, fresh-workspace
build — graph cache bypassed): the full graph gains exactly
`TABLE_FLOW sup(TOP1)@L223 → ⟐output(TOP1)` (op=FROM, Phase 1a) and
`TABLE_FLOW sup(TOP1) → rrcdm` (op=INSERT, 1c-extra); the SUBSET bridge
B1 is superseded (no SUBSET sup→output in the post-fix raw graph).
Residual gap: the L2 relevance closure (`compute_field_flow` from seed
bdm_acc_loan_info.data_dt) reaches statement 2 only via the cross-
statement DML WRITE_READ shortcut `sup(TOP0) → rrcdm`, which bypasses
the statement-2 read instance → `sup(TOP1)` and `⟐output(TOP1)` stay
outside the closure (probed INCLOSURE=False) → the bdm seed's filtered
L2 still drops the read edge. The closure needs a same-table physical-
identity admission (a TABLE var whose physical label matches an
in-closure table joins the closure), or the DML WRITE_READ should route
through the reader instance — to decide at batch time.

**Jaccard impact**: with Fix A, canonical B1's type changes SUBSET →
TABLE_FLOW (same endpoints, anchor 223 — doc repair with probe evidence
per the repair-the-doc rule); the sup seed's closure gains the walkable
read edge. Re-run the gate; raise floors with measured values.

**MANDATED by R19.3/J12-13 (user ruling 2026-08-11)**: the flow-topology
requirement — every flow edge on a source→target path, no dead-end
branches, no-bypass — is violated exactly at this spot (sup = broken
waypoint, DML WRITE_READ bypasses the reader). The Issue-3 fix is the
first stage of J12-13 (see wiki/SOLUTION_DESIGN.md §J12-13).

**IMPLEMENTED 2026-08-11 (Wave 1B, backend) — Fix A**: `_register_table`
(variable_extractor_v2.py) sets `source_tables=[name]` for bare FROM/JOIN refs (NOT DML
targets). **Verified LIVE 2026-08-11 via probe through the real build path** (fresh
workspace, filtered L2, seed bdm_acc_loan_info/data_dt):
`l2e_b4fc03d22434: bdm_acc_loan_info_sup → output | TABLE_FLOW kind=chain hl=223
reason="chain (read into output)"` — the statement-2 read leg is a walkable TABLE_FLOW
edge in the filtered closure (row 22 of the canonical), no longer only a non-walkable
SUBSET bridge. Gate green (702 passed) with the fix in place — the canonical is
consistent with the post-fix payloads.

**Residual (parked, J12-13 territory)**: the closure-reachability question — the bdm
seed's filtered closure reaches statement 2 via the DML WRITE_READ shortcut vs. a
same-table physical-identity admission — is a flow-topology refinement for the J12-13
round, not an issue-3 defect; the read leg itself renders.

### J12-15 · DML write legs misattach to the FIRST statement's ⟐ output — single-global-trunk rewrite (found via user live-test 2026-08-11)

**Symptom (user question on the live service)**: in the L2 view (search `bdm_acc_loan_info.data_dt`, script `BDM_ACC_LOAN_INFO_SUP_M.sql`), the second statement's output table (`output@L211`, `l2_tbl_236587aa4c`) shows exactly ONE edge (`bdm_acc_loan_info_sup → output @223`) and looks like a dead end, while the first statement's output (`output@L160`, `l2_tbl_7b217fb63a`) carries statement 2's write leg `output → rrcdm_job_log_exec_par @211` plus the value edge `data_dt@213 → output`.

**Root cause**: `_simplify_dml_edges` (l2_builder.py:962-1098) picks ONE global trunk — the FIRST `"⟐ output"`-prefixed intermediate_table in `table_nodes` iteration order (TOP0's output, L160) at :991-999 — and rewrites EVERY raw DML edge's source to it (:1039-1049) and every P17 value edge's target to it (:1057-1065). Statement is never consulted. The raw graph is CORRECT (probe: raw `8073ded23edd597b (TOP1 output) → 02c0d0599fa93e53 (rrcdm)` DML op=INSERT, 1c-extra2 dependency_graph.py:181-186; `4a4084293586b1d6 (TOP0 output) → e5c14f0671fd2233 (sup)`); the misattachment is introduced ONLY by the L2 rewrite's single-trunk assumption. Output VTs are NOT keeper-merged (R19.6b un-merge) — the misattachment is not a merge artifact.

**Payload self-inconsistency**: edge `l2e_73632d4f7c7a_dml_out` (source `l2_tbl_7b217fb63a`=output@L160 → rrcdm, hl=211) carries reason `"‖⟐ output@L211 → rrcdm_job_log_exec_par@L211‖"` — the reason names output@L211, the endpoint is output@L160.

**Pre-existing, NOT a stage-3 regression**: filtered payloads byte-identical current vs git HEAD 2963641 (pre-stage-3); full views carry identical `_dml_out`/`_value` edges. Verified by analysis subagent (2026-08-11).

**Impact scope**: every script with ≥2 DML statements whose later statements write different tables — 12/334 sample scripts have ≥2 DML (hive_multi_insert.sql, fin_query4_merge_upsert.sql 5 DML, sqlglot_mega_test.sql 46 DML — at that scale every output after the first dead-ends). Single-DML scripts unaffected. The Jaccard gate is BLIND to it: canonical rows 16/17/22 canonicalize to a single label-matched `⟐output@0` (NORMALIZE_MAP), and the edge's carried labels/lines are correct — only the endpoint id is wrong. R19.3 incidence checks pass (flow semantics survive — rrcdm reachable, flow_target marking verified).

**Severity**: moderate — flow semantics survive but the graph dead-ends output@L211 and renders endpoint/reason inconsistency, misleading for the tool's core debugging purpose.

**Fix direction (stage-4 scope, with the physical model)**: per-edge trunk selection in `_simplify_dml_edges` keyed by the raw DML edge's source statement (context/stmt_idx match → the owning statement's output VT), keeping the `"⟐ output"`-preferred fallback; under the physical model the write event attaches to the per-statement output occurrence (migration map §1.7 — "the synthetic ⟐ output stays as a write-event concept attached to the PhysicalTable's write role"). MUST be folded into the stage-3 snapshot rebaseline decision (do not rebaseline-away the dead-end).

**Evidence**: analysis subagent report 2026-08-11; payloads /tmp/bdm_{filtered,full,head_filtered,full_now}.json; probe scripts /tmp/probe_bdm*.py (container).

**Root-cause refinement (analysis subagent, third pass 2026-08-11) — the historical design clash**: the single-trunk assumption predates per-statement output VTs. The W5 fix at l2_builder.py:986-990 (guard against a subquery VT `⟐ subq1` coming first) *prefers* `"⟐ output"` but still `break`s at the FIRST match — iteration order = extraction order → TOP0's output always wins. Then R19.6b (2026-08-11) deliberately stopped merging output VTs per statement (the physical merge at :393 touches only `table`/`view` vars, never VTs) — the graph now has N per-statement output VTs while the rewrite still picks 1 trunk. **Why the payload is self-contradictory**: `_carry_edge_info` (l2_builder.py:673-712) stamps the raw TOP1 VT's label/line ("⟐ output"@211) onto the edge BEFORE the rewrite; the rewrite at :1042 changes only the `source` id, never the carried `_src_label/_src_line` — so R20 path strings + flow targets stay "correct-looking" while the endpoint id is wrong (also why the label+line-based gate cannot catch it). Fix = trunk selection per raw DML edge keyed by the source statement's context/stmt_idx (the owning output VT), `"⟐ output"`-preferred fallback preserved.

**Related but verified by-design (the user's second question — do NOT fix with this bug)**: the TWO `data_dt` fields under the bdm_acc_loan_info_sup compound are NOT duplicates and NOT part of J12-15. C-9 per-statement field dedup (`_classify_compound_nodes`, l2_builder.py:540-547 — key `(parent_table_id, label, stmt_idx)`): stmt_idx 0's occurrences merge into ONE field (`fld_e2b38f37a7` = keeper of the PARTITION-write var `72a148e54e11caca` @L160 plus the self-join-key var `a29aff53f7a81fa5` @L202, probe-verified); stmt_idx 1's WHERE-filter var `058f9462c6a6f7ed` @L225 is a different statement → its own field (`fld_faa927ddff`). Distinct original_ids and edge sets (write-side 160/199/202 vs read-side 223/225). Pre-existing at HEAD (filtered payloads byte-identical). R22 merges the TABLE occurrences into one compound; C-9 keeps FIELDS per statement — the combination is exactly why two same-labeled fields render in one box. By design; no action.

### J12-16 · DESIGN NOTE → **DECIDED 2026-08-11 (USER RULING: MERGE)** — fold same-named field instances into ONE display field per physical table (C-9 field-level stmt_idx split reversal)

**Finding (analysis subagent, 2026-08-11, follow-up to the user's two live-service questions)**: the two-`data_dt` display split is the ONLY remaining per-statement split at the field level, and it is inconsistent with both the physical model (ONE `PhysicalField (sup, data_dt)` with 3 occurrences — probe-verified: `058f9462c6a6f7ed` TOP1 WHERE @225, `72a148e54e11caca` TOP0 PARTITION @160, `a29aff53f7a81fa5` TOP0 JOIN ON @202) and the Jaccard canonical itself (jaccard_canonical.py:83-85: "field folds: canonical 'p1.data_dt'/'p2.data_dt' → 'data_dt' — the response merges both instances into one bare 'data_dt' field node per table"). The canonical's mental model is ONE `data_dt` per table; the two-node display is the outlier. R22 already merges TABLE occurrences into one compound with both statements' edges incident — the field level is the last per-statement split, an inconsistency rather than a requirement.

**Why it's safe (agent's evidence)**:
1. **Nothing is lost per-edge.** All per-edge precision (highlight_line 160/199/202 vs 223/225, reason, flow_kind) rides the edges via W5 carried info (`_carry_edge_info`, l2_builder.py:673-712), never derived from field nodes. The split buys only node-level provenance that the edges already carry.
2. **The gate is agnostic to the split.** Node realization = "normalized label equal AND line in the response node's incident-edge highlight_line set" (jaccard_canonical.py:94-98) — both forms satisfy it (today two fields normalize to `data_dt`; merged, one field carries all six incident lines). Edge rows are line-keyed and unchanged. `dml_phantom_field_dups` is rrcdm-scoped — untouched. STILL: any implementation must be verified by a benchmark run — the gate is the gate.
3. **No inverse-pair risk.** With one field the edge set is REF/JOIN/value-write → output@L160, REF → p2@199, REF/FILTER → sup — no field-level write/read inverse pair appears (R19.6b rationale applies to output VTs, not fields).
4. **Change is small and display-only**: drop `stmt_idx` from the C-9 dedup key (l2_builder.py:540-541 column branch, :588-589 computed branch); the existing merge machinery (`merged_original_ids` + `_build_id_map`) covers it.

**Caveats (binding)**:
- **Keep it separate from J12-15.** Merging sup's fields does NOT fix the output-VT misattachment (VT-level routing), and the J12-15 fix depends on per-statement output identity. **Do NOT merge the output VTs themselves** — R19.6b un-merges them deliberately so write/read leg pairs never render inverse.
- The split is a prior design decision (C-9, design decision 16). Reversing it requires a USER RULING — recorded here as a design note, not a defect; no action taken.
- If adopted: implement as a display-only projection change with a benchmark re-run to confirm gate neutrality; J12-15 stays independent; do NOT fold into Stage 4's keeper-merge deletion (S4 brief explicitly excludes the C-9 field dedup key).
- **USER RULING GRANTED 2026-08-11 (AskUserQuestion, user picked "Merge (Recommended)")**: fold same-named field instances into ONE display field per physical table — drop `stmt_idx` from the C-9 field dedup key (both sites: the column branch and the computed branch, l2_builder.py `_classify_compound_nodes`). Display-only; verified by a benchmark run before landing (the gate is the gate); J12-15 stays independent; output VTs stay un-merged (R19.6b). Note for the record: an earlier draft mislabeled this "user ruling: physically one field → display must show ONE data_dt" — that was an agent mis-framing BEFORE the ruling existed; THIS entry is the genuine ruling (user's explicit answer). **Implementation order**: fold into S4's stage-4 as its final step (S4 is already rewriting the merge machinery in l2_builder.py), then Jaccard gate + full suite verification; J12-17(d) settles on option 1 (global (parent,label) uniqueness with no per-statement exception).

### J12-17 · Benchmark blind spot — why the gate does not report J12-15 (benchmark weakness, 2026-08-11, analysis; fix queued)

**Question (analysis subagent, self-raised while investigating the user's live-test findings J12-15/J12-16)**: "Why does the benchmark not report such errors? Is there any weakness in the benchmark?" — NOT a user question; the agent's own investigation question, recorded as an analysis finding. (Related real user concern from an earlier round, 2026-08-10 — "Why you stop in yesterday's improve Jaccard benchmark to convergence? If you stopped, we should not miss any edges. Is there any defect in the evaluation?" — same spirit: the gate must catch defects; not this question.) **Priority assessment (analysis, not user-marked): HIGH for the post-stage-4 integration — the gate's blindness to J12-15-class defects (misattached endpoints with correct labels/lines) must be closed so the J12-15 fix is pinned by the gate.** Fix directions queued pending the batch.

**Answer: yes — five weaknesses, all verified in the gate code; J12-15 is structurally invisible to the current matching model.**

1. **Label-only endpoint identity for virtual tables** (jaccard_canonical.py:31-33, 83-98; NORMALIZE_MAP folds "⟐output"→"output", canonical "output@0" is ONE node): the canonical predates R19.6b's per-statement output un-merge — it has no instance identity for same-labeled VTs. The defect lives exactly at that unmodeled granularity (which output VT carries the write leg). Two response nodes with the same normalized label both "realize" one canonical node (node_realized, test_jaccard_benchmark.py:359-367) — multiplicity is never asserted.
2. **Edge matching is by (normalized label, anchor line)** (find_entry_edge, jaccard_canonical.py:184+): the misattached edge `output@L160 → rrcdm` carries the correct labels, hl=211 and flow_kind='write' — only its endpoint id is wrong, and ids are never compared (opaque-hash resilience became blindness).
3. **The one reachability check is connectivity-only and passes via a wrong path** (test_jaccard_benchmark.py:349-352 — `_reachable(rl["target"], w2["source"])` BFS over ANY edge type): served graph has output@L211 →(SCHEMA)→ fld_93b6c10731 →(value-edge, itself misattached to output@L160)→ output@L160 →(write leg)→ rrcdm — reachable, so the check passes although the INTENDED chain (output@L211 → rrcdm) does not exist. The check verifies connectivity, never the semantic identity of the path.
4. **The "no dead-end flow branches" half of R19.3 is not enumerated**: only the 4 named chain hops + flow_kind + incidence + one reachability call (R19_3_CHAIN, test_jaccard_benchmark.py:265-357). output@L211's single flow in-edge with no flow out-edge violates R19.3's first sentence without tripping any check.
5. **The field-uniqueness guard is scoped to proxy id prefixes** (dml_/seed_/sync_, test_jaccard_benchmark.py:368-395): sup's two real `data_dt` fields (fld_*) are outside its scope — general (parent,label) multiplicity is unasserted, so J12-16's two-field display is also invisible (there by design, but the gate cannot distinguish intended per-statement splits from genuine dups).

**Fix directions (queued, benchmark scope)**: (a) assert write-leg endpoint identity — the served payload already carries `context`/`line_start` on node data (output@L211 = TOP1/L211 vs output@L160 = TOP0/L160); canonical write-leg rows must require their source node's statement context to match the row's statement; (b) replace `_reachable` with a flow-only, flow-target-terminated path check (no SCHEMA/SUBSET hops, no value-edge detours — the R19.3 path property actually asserted); (c) enumerate dead-end flow nodes (every flow edge on a source→target path); (d) extend the uniqueness invariant from proxy prefixes to all field nodes under one (parent,label) — with the C-9 per-statement exception made explicit so J12-16 merges it away deliberately.

### J12-18 · DML-rerouted edges display the raw DML target in the ‖…‖ hop instead of the final ⟐ output endpoint (found via user live-test 2026-08-12; display bug — bug list only, no source change)

**Symptom (user question on the live service, 2026-08-12)**: L2 view, search `bdm_acc_loan_info_sup.data_dt` on `BDM_ACC_LOAN_INFO_SUP_M.sql` (workspace a80c8ae6564b / view b2955efd8293). The user sees TWO edges drawn from the `data_dt` field (parent = the `bdm_acc_loan_info_sup` compound @L160) into `⟐ output@L160` — one green (REF `l2e_702e3221e217`) and one blue (TABLE_FLOW write-value `l2e_2fc75d668fe6_value`) — but BOTH display the ‖…‖-wrapped own segment `data_dt@L160 → bdm_acc_loan_info_sup@L160`. The hop names the DML table (the field's OWN parent compound) as the target, while the drawn edge's endpoint is `⟐ output@L160`. User's words: "two times highlight for data_dt@L160 → bdm_acc_loan_info_sup@L160, but none for bdm_acc_loan_info_sup@L160 → ⟐ output@L160" — the read-into-output identity (… → ⟐ output@L160) never appears; instead the same wrong hop appears twice on two distinct edges.

**Root cause**: `_simplify_dml_edges` (l2_builder.py) re-targets edges whose target is a DML target onto the statement's ⟐ output VT, but never refreshes the carried target labels (`_tgt_label`/`_tgt_line` are stamped ONCE at `_carry_edge_info`, l2_builder.py:693-694, from the RAW DML target):
- rule-2 redirect (l2_builder.py:1148) `e["target"] = _trunk_for(e)` — fires for the REF (data_dt → bdm becomes data_dt → ⟐ output);
- value-edge creation (l2_builder.py:1174) `value_edge["target"] = _trunk_for(e)` — same for the write-value edge.
- `_attach_flow_payload` (l2_builder.py:1505-1506) builds the own segment from the stale carried labels; `_build_reason` (highlight_strategies.py:217-218) renders it as the ‖…‖-wrapped hop.
- The design already tracks the reroute: the final-endpoint flags `_src_output`/`_tgt_output` (l2_builder.py:1502-1503) and `_path_role` (highlight_strategies.py:155-156, 180-182) use them for the "read into output" role — but the own-segment renderer does not. The reason string therefore mixes the FINAL edge's role ("read into output") with the RAW edge's hop (target = bdm) — internally inconsistent.
- Side effect: `_downstream_walk`'s junction dedup (l2_builder.py:1382) compares `hops[0]` against the carried (label, line) — with the stale target the dedup never fires, so the continuation `⟐ output@L160 → bdm_acc_loan_info_sup@L160` is appended: full reason `read (read into output) — ‖data_dt@L160 → bdm_acc_loan_info_sup@L160‖ → ⟐ output@L160 → bdm_acc_loan_info_sup@L160` — a 4-hop "path" over a graph that has NO data_dt→bdm edge (bdm appears twice; the drawn edge is data_dt → ⟐ output).

**Verified evidence** (live payload /tmp/sup_level2.json):
- `l2e_702e3221e217` REF: src `fld_0a0f39ce6c` (data_dt, parent `l2_tbl_abc24a6c58` = bdm compound) → tgt `l2_tbl_b5c71bd14b` (⟐ output), hl=160, reason `read (read into output) — ‖data_dt@L160 → bdm_acc_loan_info_sup@L160‖ → ⟐ output@L160 → bdm_acc_loan_info_sup@L160`.
- `l2e_2fc75d668fe6_value` (write value): same endpoints, hl=160, reason `write (write value) — ‖data_dt@L160 → bdm_acc_loan_info_sup@L160‖ → ⟐ output@L160 → bdm_acc_loan_info_sup@L160`.
- Write leg `l2e_3b936fd33db9_dml_out` (⟐ output → bdm, hl=160) is CORRECT — its carried labels match the final endpoints (the raw DML edge's target was already bdm).
- Non-rerouted edges display correctly: JOIN `l2e_2d3768f25394` `‖p2.data_dt@L202 → ⟐ output@L160‖` (its carried target was already the output VT — never rerouted); TOP1 reads `l2e_61a5fc09e5c1`/`l2e_f25eae646f9a` `‖data_dt@L225 → bdm_acc_loan_info_sup@L223‖` (never rerouted). Confirms the trigger is the reroute, not the payload builder.
- Field node `fld_0a0f39ce6c` has `parent: l2_tbl_abc24a6c58` — the data_dt field renders INSIDE the bdm box, so the two edges visually originate "from bdm_acc_loan_info_sup@L160", matching the user's description (one blue TABLE_FLOW #2980B9, one green REF #27AE60).

**Impact scope**: every L2 filtered graph whose searched seed's DML partition/read columns feed the ⟐ output: the rerouted read-into-output and write-value edges display a hop whose target is the DML table (the field's own parent), the "→ ⟐ output@L160" identity never appears, and the read-into-output flow reads as a loop (`data_dt → bdm → output → bdm`). Display-only: `highlight_line`/`flow_kind` are unaffected (they derive from the carried lines, which are correct). Single-DML statements affected too (statement 1's INSERT here); it is not limited to multi-DML scripts.

**Relationship to J12-15/J12-17**: J12-15 was the endpoint-ID sibling (which output VT carries the write leg — fixed). This is the display-level sibling in the same reroute machinery: an endpoint-level rewrite that leaves the carried payload stale. J12-17's gate weaknesses (2)/(3) describe exactly this class — edge matching by (normalized label, anchor line) and the connectivity-only reachability check can never see a carried-label-vs-final-endpoint mismatch — so this defect is gate-invisible too; J12-17(a)/(b) fix directions cover it.

**Fix direction (queued, no source change made)**: when `_simplify_dml_edges` re-targets an edge onto the ⟐ output VT (rule-2 redirect l2_builder.py:1148; value-edge creation :1174), refresh the carried `_tgt_label`/`_tgt_line` to the output VT's label/line — the `_tgt_output` flag already marks the case; alternatively render the own segment from the final endpoints when `_src_output`/`_tgt_output` are set. This also restores `_downstream_walk`'s junction dedup (l2_builder.py:1382), collapsing the redundant `⟐ output → bdm` continuation into a clean `data_dt → ⟐ output → bdm`. Verify with the Jaccard gate (expected gate-neutral — labels/lines are correct — but the gate is the gate) + payload byte-compare before landing.


### J12-19 · Edges from a field node to its own table compound are invisible — the statement-2 read `data_dt@L225 → bdm_acc_loan_info_sup@L223` cannot be seen or clicked (found via user live-test 2026-08-12; display bug — bug list only, no source change)

**Symptom (user question on the live service, 2026-08-12)**: L2 view, search `bdm_acc_loan_info_sup.data_dt` on `BDM_ACC_LOAN_INFO_SUP_M.sql`. The user cannot find the edge `data_dt@L225 → bdm_acc_loan_info_sup@L223` (statement 2's read: `FROM bdm_acc_loan_info_sup` @L223 / `WHERE data_dt = '$(load_date)'` @L225) anywhere in the graph. Only the table-level chain edge `bdm_acc_loan_info_sup@L223 → ⟐ output@L211` (l2e_abef50a3b39b, TABLE_FLOW hl=223) is visible.

**Verified — the edges EXIST in the served payload** (workspace bf05664ef564 / view 08d5a551fd21, live service 192.168.0.66:8000, payload /tmp/sup_level2b.json):
- `l2e_61a5fc09e5c1` REF: `fld_0a0f39ce6c` → `l2_tbl_abc24a6c58`, hl=223, reason `read — ‖data_dt@L225 → bdm_acc_loan_info_sup@L223‖`
- `l2e_f25eae646f9a` FILTER: `fld_0a0f39ce6c` → `l2_tbl_abc24a6c58`, hl=225, reason `field flow (filter step) — ‖data_dt@L225 → bdm_acc_loan_info_sup@L223‖`

**Root cause (rendering, not data)**: the edge's source is the `data_dt` FIELD node with `parent: l2_tbl_abc24a6c58` — i.e. the edge connects a field to its OWN containing table box. Fields are positioned INSIDE the table rectangle (layoutCore.js `positionTableFields` — `table.pos + frozen offset`), and the table node paints an OPAQUE background (`graphStyles.js` COMPOUND_STYLES `'background-color': '#4A90D9'` on `node[type="source_table"]` etc.). No `z-index` anywhere in graphStyles.js — Cytoscape's default draws edges BELOW nodes, so the table rectangle is painted over the entire edge segment (field → table border lies wholly inside the box). The edge is therefore both invisible and un-clickable (the box intercepts pointer events). `useCytoscapeGraph.js:81` strips field parents (`stripFieldParents`) before Cytoscape sees them, so there is no compound structure that could re-layer the edge above the box.

**Impact scope**: every L2 edge whose target is the source field's own table compound renders invisible — in this graph exactly the two `data_dt → bdm_acc_loan_info_sup` edges (REF @L223 + FILTER @L225). General form: field→own-table read/filter edges (self-referential reads like the WHERE filter on the table's own column) are lost from the visual graph while the payload and the SQL highlight (edge click) are correct. Data is NOT wrong — display only.

**Why it is not J12-18**: J12-18 is the stale carried-target hop text on ⟐ output-rerouted edges (the L160 REF/value pair); this is a distinct rendering defect for field→own-parent edges (the L223/L225 REF/FILTER pair — these are NOT rerouted, their labels are correct).

**Fix direction (queued, no source change made)**: rendering-level — either (a) draw such edges above the table box (z-index on the edge / routing the edge outside the box with a small detour), or (b) render the endpoint at the table border only when source/target are the same compound's fields... The minimal display-only fix consistent with the design: give field→own-parent edges a higher z-index OR route them with a visible detour; alternatively the layout could position the field read marker outside the box. Verify visually + payload byte-compare (payload untouched by any render-only fix).


### J12-20 · Closure-admitted non-target fields render as EDGELESS islands — `_promote_field_edges` drops their own-table REF/FILTER edges (charge_department on bdm_acc_loan_info, Digitallending seed) (found via user live-test 2026-08-12; display bug — bug list only, no source change)

**Symptom (user question on the live service, 2026-08-12)**: L2 view of `BDM_ACC_LOAN_INFO_Digitallending.sql` after searching `bdm_acc_loan_info.data_dt` — the graph displays a `charge_department` field on the `bdm_acc_loan_info@L99` compound node. The user believes the rule is "only displaying the queried field" and asks why this field appears. Verified: the field renders with ZERO incident edges — an isolated island inside the table box.

**The rule actually implemented (v3.3.140)**: NOT "only the queried field node". `filter_by_field_flow`/`compute_field_flow` (lineage.py:515) display the queried field's STRICT FLOW CLOSURE — seed + reachable field-like vars (FIELD_LAND propagation, FILTER/JOIN zone, DML/TABLE_FLOW chains, identity admissions). `charge_department` enters the `data_dt` closure via W4 (lineage.py:717-718 `admit = _seed_zone(nid) or _seed_zone(nb)`): it is a co-filter of the SAME WHERE clause as the seed (L560 `data_dt = '$(load_date)'` / L561 `charge_department = 'WPB_CDT_Digitallending'`), and its FILTER edge's table endpoint (bdm@L559) lies in the seed zone (reached by the seed's own REF read). Probe-pinned: closure = exactly 9 raw ids, `charge_department@L561` among them.

**Root cause of the edgeless render (phase-traced)**: `_promote_field_edges` (l2_builder.py:800-849) drops the field's incident edges: both its REF@L559 and FILTER@L561 edges are `field → own-parent table`; promotion maps the field to its parent (charge_department is NOT in `target_field_ids` — the P2 exemption at 838-841 covers only search-TARGET seed fields), so src becomes == tgt → `continue` (line 842-843) — the edge never reaches the payload. Verified by phase trace: edges present after `_build_edge_list` (12), `_simplify_dml_edges` (13), `_combine_edges` (11) → GONE after `_promote_field_edges` (9). The filtered RAW graph kept both edges (both endpoints in closure, lineage.py:909-912) — only the L2 edge assembly drops them.

**Status: admission DOCUMENTED + benchmark-accepted, rendering NOT**. Doc §8.5 (GROUND_TRUTH_BDM_ACC_LOAN_INFO_Digitallending.md:581-582): "fields `charge_department` (on bdm, edgeless — the documented extra...)"; the pl seed carries the identical documented extra (@265, test_jaccard_benchmark.py:193-194, 209-210). The gate's node metric counts REALIZED canonical entries (compute_seed, test_jaccard_benchmark.py:623-638): an edgeless extra does not move precision while recall is full — dl floors stay 1.0000/1.0000. BUT the render is a genuine display inconsistency: the field's real flow (REF@L559 + FILTER@L561) is computed, survives the raw filter, and then vanishes from the payload — the user sees a field with no flow and no way to click into L559/L561.

**Distinct from J12-19**: J12-19's edges reach the payload but are painted under the table's opaque box (z-order); J12-20's edges are REMOVED from the payload by the promotion-to-self-loop phase. If the fix for J12-20 keeps the edges (extend the P2 retention to closure-admitted fields), they would then hit the J12-19 invisibility — the two fixes must land together for field↔own-table flow to become visible.

**Fix direction (queued, no source change made)**: (a) extend `_promote_field_edges`'s field-level retention from `target_field_ids` to ALL closure-admitted fields (keep `field → own table` edges as-is), landing together with the J12-19 render fix; OR (b) tighten the walker so non-target filter-zone siblings of the same WHERE clause do not enter the closure (gate-safe both ways — removing the extra leaves recall 8/8, precision 8/7 ≥ 1.0). Verify with the Jaccard gate + payload byte-compare + visual check.

### J12-21 · Issue-3 bare-physical-identity rule has NO context scoping — a same-table read inside an unrelated CTE cascades the whole CTE branch into the field-flow closure (t@L62 for ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE, Digitallending) (found via user live-test 2026-08-12; closure over-admission — bug list only, no source change)

**Symptom (user question on the live service, 2026-08-12)**: L2 view of `BDM_ACC_LOAN_INFO_Digitallending.sql` after searching `ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE` displays a `t@L62` node (the derived-table compound `⟐ t` of the `temp_kmbh_gl` CTE's inner subquery, L61-75). The user checks L62: `SELECT p1.acnw AS lending_ref` — the subquery reads only `p1.acnw` + `SSALSFP.*`, nothing related to BNQXYE (BNQXYE occurs exactly ONCE in the script, at L288, in the MAIN statement). Probe-verified closure for (ODS_CUPD_CLD_ACCTMASTER_NEW, BNQXYE) = 14 raw ids including BOTH `⟐ t@62` AND `⟐ t@82`, the CTE containers `temp_kmbh_gl@58`/`temp_kmbh_ie@78`, and the CTE-internal table instances `ODS_CUPD_CLD_ACCTMASTER_NEW@65/@85` + their aliases `p1@65/@85`. L2 render: 12 nodes / 17 edges, incl. `p1@65 --TABLE_FLOW--> ⟐ t@62` — the node is CONNECTED (unlike the J12-20 edgeless pattern); it is genuinely over-admitted.

**Root cause (traced admission sequence, lineage.py)**: the leak starts at the **Issue-3 bare-physical-identity rule (lineage.py:867-877)** — "a BARE TABLE/VIEW instance (physical identity == its own label) whose physical identity matches an in-closure table joins the closure". The rule scans the ENTIRE script's node map with NO context/statement scoping: once the seed's physical table is in the chain (`chain = {target_table}` + table-like seed identities), EVERY var anywhere with `identity == name == ODS_CUPD_CLD_ACCTMASTER_NEW` joins — including the instances inside the two CTE subqueries (R1: `+ODS@65`, `+ODS@85 <- bare-physical-identity`). Cascade: R2 W3-ALIAS admits `p1@65/p1@85` (`source_tables[0] == target_table`); the container rule (lineage.py:849-855) admits `temp_kmbh_gl@58`/`temp_kmbh_ie@78` from the CTE{...} context segments; R3 W6a chain-identity TABLE_FLOW (lineage.py:803-804, `FROM` op) admits `⟐ t@62`/`⟐ t@82`. The main-statement reads (p1@487 → ⟐ output@99) are legitimate; the entire CTE branch is not.

**Design intent vs. behavior**: the rule was added (ruling 2026-08-11, R19.2 read recognition) for the SUP-M statement-2 reader `bdm_acc_loan_info_sup@223` — a BARE FROM of the in-closure writer's physical table, so its FILTER edge (data_dt@225 → bdm@223, the J12-19 edge) renders. Intended case: peer-statement, ON the field's flow path. Actual behavior: matches nested reads inside unrelated CTE/subquery scopes whose statements never touch the searched field. In the BNQXYE case the CTE branch enters with NO field-level connection to the seed — `t` creates nothing (its fields `lending_ref`/`MXKMBH`/`RN` are not even in the closure; the CTE's own output container is absent, only the subquery output `⟐ t` and the CTE var made it in).

**Why the benchmark can't see it**: none of the 4 benchmark seeds (bdm/sup/pl/dl) searches a table that is ALSO read inside a nested CTE/subquery in its script — the Issue-3 rule fires only in its intended peer-statement case there, so floors stayed 1.0000/1.0000 (809 passed) while this over-admission shipped. User live-testing is the detector for this class.

**Fix direction (queued, no source change made)**: gate the Issue-3 admission with the W6b-style scope test (mirror of lineage.py:790-802): admit the bare instance only when its context is an ancestor-or-equal of a VISITED field var carrying the target field part. Checked against both cases: SUP-M intended `bdm@223` ctx=TOP1 — visited `data_dt` vars with ctx TOP1 (L550/L560) → `fctx == sctx` → admitted ✓ (J12-19 edge still renders); Digitallending `ODS@65` ctx=CTE{temp_kmbh_gl}/subq/t — visited BNQXYE vars only in TOP0 → TOP0 is neither equal nor a descendant → rejected ✓ (whole CTE branch leaves the closure; BNQXYE closure shrinks 14 → 9: seed/INT_OD_AMT/p1@487/ODS@487/p2@491/⟐ output@99). Alternative: post-walk prune of members whose only admission path runs through pure table-level edges (ALIAS/TABLE_FLOW/container) with no incident field-level edge — heavier, also gate-safe. Verify with the Jaccard gate + payload byte-compare + visual check.

### J12-23 · `TABLE_FLOW` edges miscategorized as "structure" — rendered light-blue instead of value-flow green (R30 pre-req; found while designing R30 2026-08-13; display bug — bug list only, no source change)

**Symptom:** In L2, `TABLE_FLOW` edges ("table feeds output") render in the light-blue structure color (`#AED6F1`) instead of their value-flow green. They are visually indistinguishable from SCHEMA/ALIAS/SUBSET containment edges — the most important value-flow edge reads as structure.

**Root cause:** `graph_service.CATEGORY_MAP` maps **four** types to `"structure"`:

```python
"SCHEMA": "structure", "ALIAS": "structure", "SUBSET": "structure", "TABLE_FLOW": "structure",
```

`TABLE_FLOW` is the **primary value-flow edge** (green, width 3, "table feeds output") — not a containment/rename/bridge edge. The frontend styles `edge[category="structure"]` (`graphStyles.js:607`) to light-blue, and there is **no** `edge[category="flow"]` rule to override it, so `TABLE_FLOW` inherits the structure color. The `structureEdges.js` toggle only hides SCHEMA (by edge_type), so the mislabeled `TABLE_FLOW` also evades the structure-toggle's intent.

**Fix (part of R30, when staffed):** recategorize `TABLE_FLOW` out of `"structure"` into a value-flow category (e.g. `"flow"`); leave `SCHEMA/ALIAS/SUBSET` as `"structure"` and give them one uniform gray. See R30 (REQUIREMENTS.md) and J12-23 (SOLUTION_DESIGN.md). No source change made — documentation only.

---

# Code Review Findings — v3.3.153 (2026-08-13)

> **Reviewer:** Codex (read-only, 4 parallel sub-agents) | **Scope:** R29 + R30 delta (`git diff c3c66f0..ec17cd7`)
> **Re-checked 2026-08-13 against HEAD:** 1 High + 10 Medium + ~15 Low, line-checked. Static-analysis based (reviewer did not re-run the full suite). Consolidated into the work list below; **no source change made** — implementation awaits the user's command.

## CR1 · R29 implemented but still documented as "pending / no source change" (High)

> **Priority:** P1 | **Status:** Open | **Type:** Documentation

**Symptom:** `wiki/REQUIREMENTS_TRACEABILITY.md` still marks R29.1–R29.6 and the derived R4.11–4.13 / R5.9 / R18.7 / R18.1.3 / R19.7 rows as 📝 "design, not implemented"; the summary counts "2 — R29 + R30" unimplemented; the R29/J12-22 header reads "implementation pending, no source change". But R29 source landed in v3.3.153 (`lineage.py`, `dataflow_service.py`, `l1_builder.py`, `l2_builder.py`, `routers/dataflow.py`, frontend).

**Fix direction (doc only):** flip R29.1–R29.6 + derived rows to ✅ `v3.3.153`, update the summary to "1 — R30 (docs pending)", bump the traceability version.

## CR2 · `direction` is never validated — invalid values silently become downstream (Medium)

> **Priority:** P1 | **Status:** Open | **Type:** Defect

**Symptom:** every consumer checks only `direction == "upstream"`; any other value (`"UPSTREAM"`, typo, empty) falls through to downstream. Router (`dataflow.py:148,189,263`) does not validate the POST body / query param.

**Fix:** validate against an allowlist (`Literal["upstream","downstream"]` / `Query(pattern=...)`) at the router boundary → 400 on invalid; normalize once.

## CR3 · No-flow search discards `matching_scripts`, breaking direction override (Medium)

> **Priority:** P1 | **Status:** Open | **Type:** Defect

**Symptom:** `_no_flow_result` (`dataflow_service.py:142-148,235-269`) returns `script_ids: []`/`script_count: 0` and drops the real `matching_scripts`. The persisted view has no scripts, so a later `GET /level1|/level2` with the opposite `direction` cannot re-project — exactly the views that need a direction switch most.

**Fix:** pass `matching_scripts` through; persist `script_ids`/`script_count` while keeping the `match_mode="no_flow"` banner + empty directional graph.

## CR4 · Field-search L1 drops `lineage_field_pairs` + field nodes (breaking schema, no version bump) (Medium)

> **Priority:** P2 | **Status:** Open | **Type:** Data contract

**Symptom:** pre-R29 field queries returned the table-level L1 incl. field children + `lineage_field_pairs`; the directional projection returns neither; `flow_empty`/`no_flow` are new states. Breaking response-shape change with no `format_version`/schema marker. (Note: "no field nodes in L1" is intended R29 design — the *unversioned shape change* is the concern.)

**Fix:** keep `"lineage_field_pairs": []` present (+ optionally a schema marker); document the `no_flow` match mode; confirm all shipped clients consume the new shape.

## CR5 · L1 defaults unmatched tables to `source_table` (Medium)

> **Priority:** P2 | **Status:** Open | **Type:** Defect

**Symptom:** `l1_builder.py:385-392` classifies tables from raw `input_tables`/`output_tables`; any name not matching a script IO slot is appended to `source_tables` — alias/canonical divergence mislabels an intermediate/output as source, corrupting the directional display.

**Fix:** derive the role from closure/model edges (walk direction + PhysicalModel write legs) rather than defaulting to source.

## CR6 · Frontend L2 fetch uses stale `parentViewIdRef` (Medium)

> **Priority:** P2 | **Status:** Open | **Type:** Defect

**Symptom:** `DataFlowApp.jsx:246-249` — `parentViewIdRef.current` is set only in `handleSearch`; `handleViewTreeClick` never updates it. After a view switch, `searchView = views.find(...)` + direction lookup resolve the last-searched view → wrong parent + wrong direction on a double-click.

**Fix:** set `parentViewIdRef.current = viewId` in the L1 branch of `handleViewTreeClick`; clear on child navigation.

## CR7 · Direction default contradicts the documented contract (Medium — needs user ruling)

> **Priority:** P2 | **Status:** Open | **Type:** Data contract

**Symptom:** docs say `default upstream` (SOLUTION_DESIGN/REQUIREMENTS), but the backend + client default to `downstream` (`dataflow_service.py:43,410`; `l1_builder.py:437`; `dataflow.py:189,263`; `client.js:90,110`). The UI (`FilterPanel.jsx:43`) compensates by always sending upstream, so the user-facing default is upstream — but a direct API caller or a missed frontend path gets downstream.

**Fix (needs ruling):** (a) change backend/client defaults to `"upstream"` (with legacy-compat), or (b) document "UI default = upstream" vs "API default = downstream" explicitly + add a test asserting the UI always passes it.

## CR8 · Stale ground-truth claims contradict the repaired ground truth (Medium — needs user ruling)

> **Priority:** P2 | **Status:** Open | **Type:** Documentation

**Symptom:** docs still say `rrcdm_job_log_exec_par.data_dt` is "upstream-only, empty downstream" and `lending_ref` chain is `acnw → lending_ref`; the repaired ground truth says the opposite (rrcdm downstream = the writer's-own-leg chain; `lending_ref` starts at `ods_ccb_cb_loan_acctloan.acctnbr`, per `A.acctnbr AS LENDING_REF`). The LENDING_REF doc mixes `acnw`/`acctnbr`.

**Fix (needs ruling on the canonical value):** update bullets to the repaired 2026-08-12 behavior; use `acctnbr` consistently.

## CR9 · Missing router/API-level tests for direction paths (Medium — test gap)

> **Priority:** P2 | **Status:** Open | **Type:** Test gap

**Symptom:** direction is exercised only at service level; no POST `/search` → `GET /level1|/level2` journey asserting direction echo/persistence, `match_mode="no_flow"`, or the upstream L2 "not in the writing flow…" message + role flip.

**Fix:** add a router-level upstream journey + a `no_flow` case.

## CR10 · Direction ground truth + L2 snapshot repinned from served closures (Medium — benchmark circularity)

> **Priority:** P2 | **Status:** Open | **Type:** Benchmark weakness

**Symptom:** several downstream L1 projections + jaccard rows were "repinned to the engine truth"/served closures; the 02_SUP_M snapshot regenerated (5/7 → 13/20). With floors at exactly 1.0000/1.0000, these now largely assert the engine matches its own output — the J12-21 class (silent over/under-admission) would be enshrined as correct. Related: J12-13 (fixture circular), J12-17 (benchmark blind spot).

**Fix:** re-derive canonical rows from SQL/textual evidence where possible; keep a distinct independent assertion for repinned seeds; document the 13/20 rebaseline.

## CR11 · Low-severity hardening + state-sync (consolidated)

> **Priority:** P3 | **Status:** Open | **Type:** Hardening

- `lineage.py:679` — `_stmt_of` does `_top.index("}")` on `CTE{…` without guarding `"}" in _top` → malformed context raises `ValueError` → 500 the L2 build. Guard before slicing.
- `lineage.py:698-708` — upstream seed uses case-sensitive table-name equality while field-part logic lowercases → searched-table casing mismatch can miss seeds. Case-insensitive comparison.
- `lineage.py:1068-1073` — selection round grows `_sel_stmts` but never sets `changed = True` → termination relies on a different progress signal. Mark `changed` when a new statement is recorded.
- `lineage.py:548-584` — `compute_field_flow` docstring still claims downstream is "byte-identical" to pre-R29 (false since `c037885`). Update the docstring.
- `dataflow_service.py:246` — `_no_flow_result` sets `l1_graph["target"] = "table.field"` (literal). Use `f"{table}.{field}"`.
- `l1_builder.py:310` — scripts with missing model/graph are skipped without incrementing `failures` → "could not build" masquerades as "no flow". Count/log.
- `l1_builder.py:461-462` — early `len(script_names) < 1` return stamps `flow_empty: True` unconditionally, contradicting the table-only "never flow empty" contract. `flow_empty: bool(field)`.
- `l2_builder.py:1554-1558` — upstream `_attach_flow_roles` recomputes the closure already produced by the relevance filter (2–3 walks/L2). Compute once + pass through.
- `l2_builder.py:1761-1763` — upstream `search_matched` uses `bool(graph_data.get("nodes"))` as a closure proxy. Retain/check the actual closure set.
- `dataflow.py:263 vs :332` — `get_level1` echoes resolved `direction`, `get_level2` does not. Echo it in L2 or document why not.
- `DataFlowApp.jsx:324-333` — `direction` not reset/synced on L1-view navigation → older views fall back to the last search direction. `setDirection(entry.direction || 'upstream')`.
- `DataFlowApp.jsx:221,227` — `handleSearch` stores the client-supplied direction instead of the backend-echoed `result.direction`. Store `result.direction ?? direction`.
- `FilterPanel.jsx:43,101-107,287-300` — `direction` is a second uncontrolled copy, not in history/pins. Lift state up; store per history/pin entry.
- `test_l1_physical_model.py:429` — test named `..._downstream_empty_...` asserts `flow_empty is False` (opposite of name). Rename to `..._writer_own_leg_...`.
- `SOLUTION_DESIGN.md:1488-1490` — still says L1 is "verified manually … no automated L1 check" despite new `test_r29_*` tests. Reword.
