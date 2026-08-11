# J12-10 Stage 2 — L2 Node Construction Consumer Contract

> Team A2 deliverable (2026-08-11). The exact spec of WHAT L2 node
> construction consumes today and MUST reproduce when the physical model
> (stage 1) becomes its source at stage 2: per-node fields and their
> derivations, the id derivation rule, field-parent mapping, and
> ordering — so Team A1's model contract can be checked against it and
> the stage-2 team can implement the projection directly.
>
> Companions: `wiki/SOLUTION_DESIGN.md` §J12-10 (design) and
> `tools/PHYSICAL_MODEL_MIGRATION_MAP.md` (Team A3 — the line-level
> inventory of the reconstruction machinery this contract replaces).
> This document is the NORMATIVE spec; A3's map is the inventory.
>
> **Byte-identity gate:** `backend/tests/test_l2_snapshot.py` (committed
> snapshots under `backend/tests/snapshots/`, 13 tests). Stage 2 is done
> when the gate is GREEN WITHOUT REBASELINE: the projection over the
> model emits ids/labels byte-identical to today.

---

## 0. Scope

Stage 2 = "L2 consumes the model for node construction only — ids/labels
byte-identical" (design §7). In scope here (all `backend/app/services/
l2_builder.py`):

| Function | Lines | Role in node construction |
|---|---|---|
| `_classify_compound_nodes` | 230-577 | all compound node creation (tables, fields, proxies) |
| `_carry_node_lines` | 1387-1412 | table nodes gain `line_start`/`line_end`/`defined_in` |
| `_build_id_map` | 604-624 | original-id → keeper-id map (the bridge the EDGE phases consume) |
| `_map_search_target_ids` | 580-601 | re-marks `is_target`/`field_group` on keepers |
| `_sync_alias_and_dml_fields` | 1069-1183 | alias/dml field proxies (Sync 1/Sync 2) |
| `_assemble_output` | 1674-1703 | final node list + order |

EDGES are NOT in stage-2 scope: `_build_edge_list` (669-737) and phases
5-9 (`_combine_edges` … `_dedup_edges`) plus `_attach_flow_payload`
(1525-1636) keep consuming the current full-graph edge list unchanged.
They read the compound ids through `_build_id_map` (696-697, 860-883,
965-966, 1656/1660) — so the projection must emit `_build_id_map`
byte-identically (§5) or every edge breaks.

---

## 1. Inputs the projection consumes (per occurrence)

The current node construction consumes the FULL-graph node list — built
by `graph_service.build_graph_data` from the analysis — i.e. the
occurrence layer. The physical model must expose, per occurrence, the
following (or provably equivalent derivations):

| Field | Source today | Consumed by |
|---|---|---|
| `id` | var id — `md5(f"{script_name}:{name}"[, _{suffix}])`[:16], extractor `_make_id` | compound id derivation, dedup keys, id_map |
| `label` | var name (raw, e.g. `p1.data_dt`, `⟐ subq1`) | display labels, alias detection, seed matching (`rsplit(".",1)[-1]`), `_field_part` |
| `variable_type` | 15-member VariableType enum | branch selection (table-like / column / computed / fallback), type mapping, FIELD_LIKE membership |
| `source_tables` | extraction attribution (I2: exact per field) | field-parent resolution (chain 1), alias-map rebuild, Sync 1 canonical check |
| `source_columns` | extraction | `_compute_target_and_direct_ids` seed matching (suffix rule) |
| `defined_in` | extraction ("FROM", "JOIN ON", "PARTITION", …) | `_carry_node_lines` stamp; seed/partition checks in the walkers |
| `is_output` | extraction | `output_table` typing |
| `context` | extraction scope string (`TOP0`, `CTE{loan_final}`, `subq1`, `TOP0:join:p2`) | compound `context` stamp; `_stmt_idx_of` input; `_stmt_anchor_lines_from_nodes` input |
| `stmt_idx` | derived — `_stmt_idx_of(context)`: `TOP<digits>` prefix → int, else None | field dedup key `(parent, label, stmt_idx)`; Sync exists-checks |
| `line_start` / `line_end` | extraction (I1: single-line `[L,L]`) | alias `@line` display labels, `_carry_node_lines`, anchor derivation, seed re-parent |
| `table_name` / `field_name` / `sql_expression` / `node_type` / `shape` / `color` / `size` | graph_service pre-resolution / styling | NOT consumed by node construction (edges/walkers read `table_name`/`field_name`; `sql_expression` feeds the cache line_map recompute) — the projection may drop them from node construction |

**Graph-level `alias_map`:** the cache carries label→canonical, but
`_classify_compound_nodes` REBUILDS it first-writer-wins from the node
list itself (274-291): for every node with `variable_type ∈ {table,
view, cte, subquery, virtual_table, merge_target, union_branch}` and
exactly one `source_tables` entry, `alias_map[label] = source_tables[0]`
(first occurrence wins). The effective input is therefore the node
list, not the cache field — the model must reproduce this derivation
(or expose the same first-writer-wins mapping).

**Ordering:** classification iterates the FILTERED graph's node list in
list order; `_carry_node_lines`/`_stmt_anchor_lines_from_nodes` iterate
the FULL (pre-filter) node list in list order. Both orders are
deterministic today (extraction order) and are part of the byte-identity
contract (§3).

---

## 2. Node id derivation (unchanged by stage 2)

Every compound id is derived from an ORIGINAL occurrence id (nid), never
from the physical name directly:

| Node | Rule | Where |
|---|---|---|
| table compound | `l2_tbl_<md5(nid)[:10]>` | 329 |
| field compound | `fld_<md5(nid)[:10]>` | 434, 489, 524 |
| P1 seed copy | `seed_<field_id>_<keeper_tbl_id[:8]>` | 571 |
| Sync 1 alias copy | `sync_<field_id>_canon` | 1153 |
| Sync 2 DML phantom | `dml_<field_id>_<target_tbl_id[:8]>` | 1180 |
| edge (reference) | `l2e_<md5(src+tgt+edge_type)[:12]>`, `{id}_dml_out`, `{id}_value`, `l2e_join_survive_<src>_<tgt>` | 725, 1004, 1014, 901 |

`nid` for a KEEPER = the first (keeper) occurrence's id — so a merge
does NOT re-derive the keeper id; the merged-away ids only feed
`merged_original_ids`/id_map. Under the physical model the keeper's id
must still be derived from the SAME first occurrence id (or the model
must carry that id for the PhysicalTable it corresponds to) — id
stability is the whole point of the gate.

---

## 3. Table compound nodes — classification spec

For each node in the filtered graph (list order, `seen_ids` skips
duplicates):

### 3.1 Type mapping (exact conditions, in this order)

| Condition | type | Display label |
|---|---|---|
| `is_alias` (label ∈ alias_map AND alias_map[label] != label) | `alias_table` | `label` with `⟐ ` prefix stripped, `@<line_start>` appended when line_start > 0 (`p1@29`) |
| `variable_type == "cte"` | `cte_table` | `⟐ `-stripped label |
| `is_output` AND vt ∉ {table, view} | `output_table` | `⟐ `-stripped label |
| vt ∈ {table, view} AND NOT is_output | `source_table` | `⟐ `-stripped label |
| everything else (incl. output table/view vars) | `intermediate_table` | `⟐ `-stripped label |

`table_name` is ALWAYS the RAW label (never the display label) — field
parent matching, the `⟐ output` string-prefix routing (943-951, 1586)
and Sync-1 canonical lookup key on it.

### 3.2 Keeper semantics (the merge identity)

| Node kind | Identity key | Merge behavior |
|---|---|---|
| physical table/view (non-alias) | LABEL (first occurrence = keeper) | later same-label occurrences: `keeper["merged_original_ids"].append(nid); continue` (323-327) — one node per physical table |
| alias | `(alias_parent_id, label, alias_line)` — parent = the compound of `source_tables[0]` (resolved through alias_map when not yet classified; None when unresolvable) | same-key duplicates merge into the keeper (379-382) |
| cte / subquery / virtual_table / merge_target / union_branch | occurrence id (per-context) | no merge — each occurrence is its own compound |

`merged_original_ids` is recorded on every table compound (list; empty
for the keeper) — it is builder-internal bookkeeping, stripped from the
response at assembly (1681-1682), and feeds `_build_id_map` only.

### 3.3 Table node output fields (exact set)

`id, label, type, table_name, variable_type, original_id, context` +
(`line_start, line_end, defined_in` from `_carry_node_lines`, §6) +
one of (`flow_source` | `flow_target` | `flow_role`) from
`_attach_flow_roles` (1639-1671): `flow_source`/`flow_target` on the
filtered view, `flow_role` (R19.5 net-flow, computed from the FINAL
edges over `variable_type == "table"` compounds only) on the full view.
NO `is_target` on table nodes — `is_target` is a field-node-only flag.

---

## 4. Field nodes — classification spec

### 4.1 Branch selection + label derivation

| Branch | Condition | label | parent resolution |
|---|---|---|---|
| column | vt ∈ {column, cte_column} OR `label.count(".") == 1` | `label.split(".")[-1]` if dotted else label | chain 1 (below) |
| computed | vt ∈ {expression, aggregate, window, case, transform, literal} | `label[:36]` | chain 2 (below) |
| fallback | any other vt | `label[:36] + " ·"` | first table compound (if any); NO dedup, NO `merged_original_ids` |

Chain 1 (column): `source_tables[0]` → first table compound whose
`table_name == source_tables[0]` OR whose key `tid == source_tables[0]`;
else `alias_map[source_tables[0]]` → first compound with that
`table_name`. Unresolved → the field is appended WITHOUT a `parent` key
(floating field — present in today's output, 177 instances across the
12 snapshot scripts).

Chain 2 (computed): first table compound whose `table_name ∈
source_tables` or `tid ∈ source_tables`; else the FIRST table compound
(fallback attach, warning logged).

### 4.2 Dedup key

`(parent_id, label, stmt_idx)` — per-statement dedup (C-9): same-named
fields under one parent in DIFFERENT top-level statements are distinct
nodes; `stmt_idx` is None for CTE-body scopes. Later duplicates merge
into the keeper (`merged_original_ids.append(nid)`); the keeper's
`field_group`/`is_target` are re-marked after mapping (§7). Fields
without a parent skip dedup entirely.

### 4.3 Field node output fields (exact set)

`id, label, type="field", variable_type="field", orig_type, is_target,
field_group, original_id` + (`parent` when resolved). `orig_type` =
`variable_type[:12]` (fallback branch: `(vt or "unknown")[:12]`).
`field_group` = "direct" if the original id ∈ `direct_ids` (upstream+
downstream BFS from the targets, 199-227) else "indirect".
`is_target` = original id ∈ `target_node_ids` (one-predicate suffix
match on label AND `source_columns`, 193-197).

### 4.4 P1 seed copy (B3/P1, 546-575)

For `is_target` fields whose parent compound is an `alias_table` whose
canonical (`alias_map[table_name]`) == the searched table: when the
searched table's own compound lacks the label, COPY the field onto it
as `seed_<fid>_<keeper_tbl_id[:8]>`, `parent` = searched-table keeper,
`field_group` = "direct" (the original stays on the alias). The model
replaces the copy with a shared reference at stage 3 — at stage 2 the
display still emits the copy node.

---

## 5. `_build_id_map` (the merge map)

`original_id → compound_id` for every table compound (its
`merged_original_ids` too), every field node (ditto), every other node.
Consumed byte-identically by: `_build_edge_list` endpoint re-point
(696-697), `_map_search_target_ids` (594-595), `_survive_join_edges`
(860-883), `_simplify_dml_edges` dml_targets/sources/pairs (965-966),
`_attach_flow_roles` (1656/1660). Under the model this becomes
`occurrence_id → PhysicalTable/PhysicalField.id` — the stage-2
projection must emit the same map (i.e. the model must keep occurrence
ids; design §3 "nothing lost").

---

## 6. `_carry_node_lines` (table spans)

For each table compound: look up the KEEPER's `original_id` in the FULL
(pre-filter) node index; stamp `line_start` (raw), `defined_in` (raw);
`line_end` = the keeper's raw `line_end`, but when `line_start > 0` and
`line_end <= line_start`, the next statement anchor − 1 (0 → max
`line_start` over the full node index). Statement anchors are
RE-DERIVED from the full node index (`_stmt_anchor_lines_from_nodes`,
1357-1376): per `TOP<idx>` context the minimum non-CTE `line_start`
(CTE vars excluded). This is a reconstruction the physical model should
own at stage 3 (statement anchors are extraction facts); at stage 2 the
derivation stays as-is.

---

## 7. `_map_search_target_ids` + `search_matched`

`target_node_ids`/`direct_ids` are mapped through id_map to keeper ids;
field nodes re-marked in place (`is_target=True`, `field_group="direct"`).
`search_matched` = `bool(target_mapped or direct_mapped)` (1795) — the
not-in-flow signal the API falls back on. The model lookup must produce
the same signal for the same (table, field) seed — the J12-9
one-predicate (label suffix OR `source_columns` suffix, 193-197) must
NOT regress to exact-full-name matching (alias-copy seeds depend on it).

---

## 8. `_sync_alias_and_dml_fields` (proxies — stage 2 output must keep them)

Sync 1 (alias → canonical, 1110-1156): iterate the rebuilt
first-writer-wins alias_map; for each `(label → canonical)` pair pick
the FIRST alias compound instance (table_nodes iteration order) that
holds fields AND whose own original var's `source_tables[0] ==
canonical` (scope-disambiguated); copy each of its fields to the
canonical compound as `sync_<fid>_canon` (exists-check on
(parent, label, original stmt_idx)). No qualifying instance → skip.

Sync 2 (DML phantoms, 1161-1183): `dml_pairs` = `(src_new, tgt_new)`
from FULL-graph DML edges through id_map (958-972 — note: unfiltered
graph, Bug 46); for each pair, fields parented at `src_fid` (or with
id == src_fid) are copied to the target compound as
`dml_<fid>_<tgt_tid[:8]>` (exists-check on (parent, label) only —
R11-2: one DML target gets ONE field per label).

Proxy append order defines the field-list tail: `[classified fields] +
[seed_ proxies] + [sync_ proxies] + [dml_ proxies]` — the response node
order (§9) depends on it.

---

## 9. Output ordering (byte-identity)

`_assemble_output` (1674-1703): `[{"data": tn} for tn in
table_nodes.values()]` (insertion order of first occurrence in the
filtered graph) + `[{"data": fn} for fn in field_nodes]` (classification
order + proxy append order §8). `merged_original_ids` stripped;
edge dicts stripped of `_`-prefixed carriers. The serialized response
additionally carries `script_name, total_nodes` (full-graph node
count), `filtered_nodes` (compound node count), `total_edges`,
`target` (`f"{table}.{field}"`), `search_matched`.

The stage-2 projection must preserve this order: iterate occurrences in
the same order, create compounds in the same order, append proxies in
the same phase order. Any order change = snapshot diff.

---

## 10. Normative: what the physical model must provide at stage 2

For the stage-2 projection to produce byte-identical output, the model
must expose, per script (all deterministically, in the current
occurrence order):

1. **Occurrence data** for every node that contributes to L2 output:
   `id, label, variable_type, source_tables, source_columns,
   defined_in, is_output, context, stmt_idx, line_start, line_end` —
   or a documented derivation that yields the same values (e.g.
   `stmt_idx` from context).
2. **Physical-table identity** that reproduces the label-keyed keeper
   selection exactly: one keeper per physical name, keeper = first
   occurrence, `merged_original_ids` = the remaining occurrence ids —
   and the per-context compounds for cte/subquery/VT/merge_target/
   union_branch occurrences (they do NOT merge; 1.4 in A3's map is a
   stage-4 change, not stage 2).
3. **Alias identity** reproducing `(parent_compound_id, label,
   alias_line)` per alias occurrence, plus the first-writer-wins
   alias_map derivation (§1).
4. **Statement anchors** (per-`TOP<idx>` first-token line, CTE-excluded)
   for `_carry_node_lines` — or keep the current re-derivation at
   stage 2.
5. **Seed resolution** reproducing `_compute_target_and_direct_ids`
   (one-predicate target match + direct_ids BFS) → `is_target`/
   `field_group`/`search_matched` byte-identity.
6. **dml_pairs** (or write-leg information) reproducing Sync 2's
   phantom set — the DML write role of the model at stage 3, projected
   to the same `(src_fid, tgt_tid)` pairs at stage 2.

The model may REPLACE the derivation source; it may not change the
output. Stage 3's id/label churn (proxies dying, alias views) is a
documented re-anchor — stage 2 has none.

---

## 11. Gate runbook + determinism note

```
# gate (must be 13 passed, no rebaseline during stage 2)
docker exec -w /app/backend gps-sql-backend python3 -m pytest tests/test_l2_snapshot.py -q

# rebaseline ONLY intentional output changes
L2_SNAPSHOT_UPDATE=1 docker exec -w /app/backend gps-sql-backend python3 -m pytest tests/test_l2_snapshot.py -q

# full suite (728 passed / 5 skipped as of 2026-08-11)
docker exec -w /app/backend gps-sql-backend python3 -m pytest tests/ -q
```

**Determinism pin:** the current pipeline's ANALYSIS dependency list is
emitted in PYTHONHASHSEED-dependent order (same edge set, different
order — first divergence at index 32 in `tpcds_qualified/04.sql`,
AGGREGATE edges; verified across seeds 0-3). The L2 FULL view inherits
content instability via first-wins dedup and closure-walk choices
(BDM across seeds: 4 edges differ in id set, 30 edges same id with
different reason content). The harness therefore runs every build in a
SUBPROCESS with `PYTHONHASHSEED=0` (canonical bytes; see the harness
docstring) — a harness-level pin, NOT a product change. Stage 2 keeps
the harness as-is. The underlying instability is a separate finding for
the bug list (fix direction: canonical sort of the dependency list in
`build_dependency_graph` — then the subprocess pin can be dropped).
