# J12-10 Wave A — Physical Model Migration Map

> Team A3 deliverable (2026-08-11). Read-only analysis that lets the
> stages 2/3/4 teams work without re-discovery. Companion to
> `wiki/SOLUTION_DESIGN.md` §J12-10 (design) — this document is the
> line-level inventory.
>
> All paths relative to `backend/` unless noted. Line numbers verified by
> grep against the working tree (HEAD acb2dcf, v3.3.150).
> **No source files were changed to produce this map.**

---

## 0. The pipeline shape this map assumes

```
syntax layer (unchanged)         PHYSICAL LAYER (new, stage 1)
variable_extractor_v2.py   ───→  PhysicalTable (name key; roles set:
dependency_graph.py              read/write/merge_target/cte_fed…;
(deps = 16 edge types)           occurrence ids, alias views)
                                 PhysicalField (table+field key; lines;
                                 value sources; uses)
                                 PhysicalEdge (src field → tgt field;
                                 16 types stay; derived once from deps)
                                          │
                                          ▼
                              data flow: compute_field_flow / closure /
                              seed search walk the MODEL (stage 3)
                                          │
                                          ▼
display layer (stages 2-4): pure projection — no merge, no proxies
```

Stage 1 (new module, unused in responses, invariant tests only) is NOT
covered below except where stages 2-4 depend on its content; see
`wiki/SOLUTION_DESIGN.md` §J12-10 §7/§9 for its targets.

---

## 1. Reconstruction-machinery inventory

Every mechanism below is display-time reconstruction of physical
identity. For each: where it is created, where it is consumed, and what
the PhysicalTable/PhysicalField lookup replaces it with.

### 1.1 Label-keyed keeper merge (R22 "one node per physical table")

**Creation — `app/services/l2_builder.py`, `_classify_compound_nodes` (230-577):**

| Site | Line(s) | Role |
|---|---|---|
| `table_nodes_by_label` dict (label → keeper compound) | 247 | the label-keyed identity map |
| `fields_by_key` (parent, label, stmt_idx) → keeper field | 252 | field-level dedup key |
| keeper merge: non-alias `table`/`view` with existing label → `merged_original_ids.append(nid); continue` | 323-327 | the physical-table merge itself |
| keeper registration (`merged_original_ids=[]`, `table_nodes_by_label[label]=node`) | 396-398 | first occurrence wins |
| field dedup (column branch) | 460-467 | same (keeper table, label, stmt) → one field node |
| field dedup (expression/aggregate branch) | 508-515 | same key, computed fields |
| fallback unknown-node branch (creates field WITHOUT dedup, label + " ·") | 519-535 | rescue path (see 1.5) |

**Consumption — `_build_id_map` (604-624) and its consumers:**

| Site | Line(s) | Role |
|---|---|---|
| `_build_id_map` | 604-624 | builds original-nid → keeper-id map from `merged_original_ids` |
| `_build_edge_list` endpoint re-point | 696-697 | every raw edge endpoint mapped to the keeper |
| `_map_search_target_ids` | 594-595 | target/direct ids mapped to keepers |
| `_survive_join_edges` id_map lookup + label-prefix fallback | 860-883 | JOIN survival resolution incl. name-first-match fallback |
| `_simplify_dml_edges` dml_targets/sources/pairs via id_map | 965-966 | DML routing (see 1.7) |
| `_attach_flow_roles` source/target keeper lookup | 1656, 1660 | flow roles on keepers |
| `_assemble_output` strips `merged_original_ids` from the response | 1681-1682 | internal bookkeeping never leaks |
| orchestrator | 1752, 1757, 1761 | call order: classify → id_map → map_search_target_ids |

**Replacement:** `PhysicalTable` IS the keeper — one entity per physical
name by construction. `merged_original_ids` = the table's occurrence-id
set (design §3: "nothing lost"). `_build_id_map` collapses to
`occurrence_id → PhysicalTable.id`; `_map_search_target_ids` disappears
(no merged-away ghosts exist); `_assemble_output`'s strip stays only if
the occurrence list is not part of the display contract.

**Consumers that must keep working on the model:** `_build_edge_list`
(669-737), `_survive_join_edges` (811-913), `_simplify_dml_edges`
(916-1053), `_attach_flow_roles` (1639-1671), `_attach_flow_payload`
(1525-1636, R11-3 `_resolve_compound` at 1616-1627).

### 1.2 Seed matching (J12-9 one-predicate → PhysicalField lookup)

**Current location — `_compute_target_and_direct_ids`, `l2_builder.py:161-227`;**
the J12-9 exact-match ruling is already applied and lives at **193-197**:

```python
if name.rsplit(".", 1)[-1] == field:          # label suffix rule
    target_node_ids.add(nd.get("id"))
for sc in nd.get("source_columns", []):        # source_columns suffix rule
    if sc.rsplit(".", 1)[-1] == field:
        target_node_ids.add(nd.get("id"))
```

- The 5 J12-9 match paths (exact-full / exact-field / suffix-after-dot /
  dead `target_full in sc` substring / `_target_field_sc` helper) are
  already decomposed into this ONE predicate (comment block 175-192).
  **Do not re-derive them — they are gone.**
- Same predicate family inside the walker seeds:
  `compute_field_flow` seed loop, `lineage.py:607-625` (field part ==
  target_field AND (owner == target_table OR PARTITION with
  `source_tables[0] == target_table`)).
- The legacy table-level seed (SCHEMA + Bug-39 DML search) lives in
  `compute_field_lineage`, `lineage.py:142-220` — L1/legacy only, not in
  scope for stages 2/3.

**Replacement:** `PhysicalField` dict key `(table, field)` lookup — the
seed is one `physical_fields[(search_table, search_field)]` access;
`source_columns` and label parsing die. J12-9 "kept semantics — do NOT
narrow": field-only labels (`data_dt`) and alias-qualified labels
(`p1.data_dt`) must keep resolving to the search's field — under the
model both are *references to the same PhysicalField* (alias views +
owner attribution at extraction), so the narrowing that would regress
the gate is impossible by construction (alias-copy seed dependence:
`tools/BUG_ANALYSIS_AND_SUGGESTIONS.md` J12-9, "Kept semantics").

### 1.3 Proxy synthesis (one field instance shown on several parents — by COPYING)

All proxies are `dict(fn)` copies with a synthetic id and `field_group: "direct"`.

| Proxy | Created at | What it copies | Consumed by | Replacement |
|---|---|---|---|---|
| P1 seed copy `seed_{fn[id]}_{keeper_tbl_id[:8]}` | l2_builder.py:546-575 (`_classify_compound_nodes` B3/P1 pass; id at 571) | an `is_target` field that landed on an alias of the searched table, copied onto the searched table's own compound when label absent | display only; `is_target` marks make it a closure entry for `_attach_flow_payload` entries (1555), promotion-exempt in `_promote_field_edges` (774-780) | alias view → PhysicalTable; the seed field is ONE PhysicalField referenced by both the table and the alias view — reference, never copy |
| Sync 1 alias→canonical `sync_{af[id]}_canon` | l2_builder.py:1142-1156 (`_sync_alias_and_dml_fields`, proxy id at 1153) | alias fields onto the canonical table (alias invariant); stmt_idx-aware exists-check 1146-1150 | display only | PhysicalField under the physical table; alias view lists the same fields (design §4 "Aliases become views") |
| Sync 2 DML phantom `dml_{fn[id]}_{tgt_tid[:8]}` | l2_builder.py:1161-1183 (proxy id at 1180) | source-side fields onto each DML target compound, one field per (target, label) (R11-2 exists-check 1174-1177) | display only; **pinned by tests** (see §4.2) | the target PhysicalTable's field set comes from its write role (write columns are extraction facts — dependency_graph Phase 1c); dml_ phantoms die |
| whole function | l2_builder.py:1069-1183 | called at 1785, after `_attach_flow_payload` | | function deleted entirely |

**Proxy-consumption coupling to remove together:** `_promote_field_edges`
(759-808) exempts `is_target` fields from field→table promotion (P2) —
under the model the display decides promotion by physical role, not by
copy marks. `_attach_flow_payload` entries = `is_target` field ids
(1555) and the seed-zone adjacency (1556-1560) — after proxies die, the
closure entries come from the seed's PhysicalField directly.

### 1.4 merge_target/table split (#7)

**Where:** `_classify_compound_nodes`, l2_builder.py:
- table-like branch admits `merge_target` as a compound parent: 308-309;
- **but the label-keyed keeper merge at 323 fires only for `vt in
  ("table", "view")`** — a MERGE_TARGET var never merges into the
  TABLE var of the same physical table (or vice versa), so the same
  physical table read in one statement and MERGE-targeted in another
  renders as TWO compound nodes.
- tbl_type assignment for a merge_target falls through to
  `intermediate_table` (332-339).

**Replacement:** impossible by construction — `PhysicalTable` keyed by
physical name; `merge_target` is a role in the table's role set
(design §6: `gps_accounts` = {read, merge_target}). The display shows
one node with edges for both roles.

**Stage-1 verification targets that pin this:** `samples/financial/
fin_query4_merge_upsert.sql` (gps_accounts exactly once, roles
{read, merge_target}, `balance` one PhysicalField with write+read
occurrences) and `samples/mock_sql_test/06_merge_update.sql`
(`customer_summary` once; `target` alias view → `customer_summary`) —
both files exist and are bind-mounted at `/app/samples`
(docker-compose.yml:19). Both are OUTSIDE the Jaccard rows today (zero
MERGE coverage in the benchmark — flagged in design §8).

### 1.5 Floating-field rescue (#8/#9)

**Parenting paths that rescue fields with no parent at display time:**

| Site | Line(s) | Mechanism |
|---|---|---|
| expression/aggregate fallback: "no source table — attached to first table node" (warning) | l2_builder.py:480-484 | first-table fallback |
| unknown-node fallback: same + " ·" label suffix | l2_builder.py:519-535 | first-table fallback, no dedup |
| `_survive_join_edges` name-first-match fallback for filtered-out field endpoints | l2_builder.py:864-883 | label-prefix resolution to a compound |
| Sync 1 "pick the first alias instance that holds fields AND whose own source table is the canonical" | l2_builder.py:1123-1141 | scope-disambiguation of alias instances |

Also (L1, stage 4 scope): L1 V3.2.6 field propagation (fields inherited
by downstream tables with zero fields), `l1_builder.py:710-789`.

**Replacement:** a PhysicalField always has a parent by construction
(its PhysicalTable) — design §4: "#8/#9 dissolved". `source_tables`
attribution is extraction-time (I2, `variable_extractor_v2.py` —
`_register_column` sets `var.source_tables = [_resolve_alias(...)]`),
so the model needs no fallback at all.

### 1.6 Alias nodes as first-class compound nodes (Bug 28)

**Creation — `_classify_compound_nodes`:**

| Site | Line(s) | Role |
|---|---|---|
| alias detection `is_alias = label in alias_map and alias_map[label] != label` | 310-312 | alias vs physical table |
| `alias_table` type | 330-331 | display type |
| alias identity key `(alias_parent_id, label, alias_line)` + `p1@29` display labels | 348-401 (key at 378, display label at 360-361) | one alias node per (physical parent, label, code line) |
| alias dedup via `alias_nodes_by_key` | 379-382 | same-key instances merge |
| alias_map read from cache / node-scan fallback | 260-272 | Bug 48 fallback reconstruction |
| **first-writer-wins override** of the label-keyed alias_map | 274-291 | B3/P1: one alias label naming different physical tables across scopes |
| Sync 1 scope disambiguation | 1123-1141 | see 1.5 |
| `_sync_alias_and_dml_fields` iterates `alias_map.items()` | 1110 | alias→canonical sync |

**Production-side source of alias info (unchanged, extraction-time):**
`dependency_graph.py` Phase 2 ALIAS (334-340) — one edge per exact
`alias_of` var id (I4); `variable_extractor_v2.py` `_register_table`
alias registration + `alias_of` (1695-1784, alias branch ~1753-1780);
`graph_service.py` P2/P5 alias_map pre-build (138-143).

**Replacement:** alias = *view* (`alias → physical table` mapping,
design §4) — still renderable as context boxes, no longer data nodes;
the ALIAS edge family stays for display but field identity flows
through the physical table. The label-keyed `alias_map`
(last-writer-wins at graph_service.py:143) and its first-writer-wins
override (274-291) are exactly the "invisible label-keyed
approximation" the design bans — the model stores explicit
alias→table edges (already present as `alias_of`).

### 1.7 DML routing / write-leg rewrite (⟐ output trunk)

`_simplify_dml_edges`, l2_builder.py:916-1053:

| Site | Line(s) | Role |
|---|---|---|
| intermediate ("⟐ output") selection, string-prefix match `table_name.startswith("⟐ output")` | 943-951 | the write trunk |
| dml_targets / dml_sources / dml_pairs harvested from FULL-graph DML edges | 958-972 | routing inputs (Bug 46: unfiltered) |
| suppress TABLE_FLOW bypass | 980-983 | source→⟐→target chain replaces direct |
| redirect non-DML bypass to ⟐ | 985-992 | TRANSFORM/AGGREGATE/… |
| DML edge → `{id}_dml_out` TABLE_FLOW, `_dml_origin=True` | 994-1004 | the write leg |
| `{id}_value` value-edge split (P17, seed target fields) | 1005-1020 | keeps the value appearance traceable |
| Bug 46 Pattern 2: redundant bypass drop / redirect | 1025-1051 | dedup collision guard |

**Payload coupling:** `_attach_flow_payload` flow targets =
`_dml_origin` edges (1565-1566), write-line map (1571-1583), `⟐ output`
id set (1584-1587); `_downstream_walk` bracket rule consumes
`write_line_by_target` (1253-1341); `highlight_strategies.py`
`_dml_origin`/`_value_edge` → write-leg roles (146, 100-113 in tests).

**Replacement (design §4):** the synthetic ⟐ output stays as a
*write-event concept* (its result set) **attached to the
PhysicalTable's write role** — rendering unchanged; dml_targets/pairs
become the write-role's edges, not a scan of full-graph edges; the
string-prefix `"⟐ output"` sentinel matching dies (also used at
l2_builder.py:346 B5 label sanitation, 949, 1586). `_dml_out`/`_value`
edge-id suffixes survive only if edge ids keep their raw derivation.

### 1.8 Payload machinery (carried info, closure/downstream walks) — consumers of the model's output, not reconstructions

These are NOT reconstruction (they consume extraction-time facts
attached at build time), but they pin the edge/display contract stages
2/3 must preserve:

| Site | Line(s) | Consumes |
|---|---|---|
| `_carry_edge_info` (per-edge `_src_line/_tgt_line/_src_label/_src_vt/_src_tables/_op/...`) | l2_builder.py:627-666 | raw node/edge extraction fields; rides every edge |
| `_closure_walk` (R20 upstream BFS over FINAL L2 edges, carried labels/lines) | 1186-1250 | final edges + `is_target` closure entries |
| `_downstream_walk` (R20 downstream BFS to `_dml_origin` flow targets, bracket rule) | 1253-1341 | final flow edges + write-line map |
| `_attach_flow_payload` (orchestrates walks + strategy) | 1525-1636 | carried info → highlight_line/flow_kind/reason |
| `_carry_node_lines` (compound line_start/line_end from keeper var; `_stmt_anchor_lines_from_nodes` RE-derives statement anchors 1357-1376) | 1387-1412 | pre-filter node index — **a derivation the physical model should own** (statement anchors are extraction facts) |
| R11-3 mech: `_ref_site_vars` scan + `_build_mechanism` | 1415-1427, 1477-1522 | pre-filter var index + compound def-ranges |

**R26.3 (2026-08-11) — the per-edge `mech` payload is REMOVED.** R26
deleted the frontend renderer (EdgeReasonPanel renders kind + anchor +
reason only) and this integration turn retires the dormant backend
emitter under the no-dormant-machinery rule: `_build_mechanism`,
`_mech_sentence`, `_mech_fallback_clause`, `_ref_site_vars`,
`_field_part`, `_REF_SITE_TABLE_TYPES` and the mech block inside
`_attach_flow_payload` (incl. the `_resolve_compound` closure and the
`node_index` parameter) are deleted; the level2 response and the graph
cache no longer carry the per-edge `mech` key. `_carry_node_lines`
(compound line_start/line_end/defined_in) and the R25 payload
(highlight_line/flow_kind/reason) are UNCHANGED. Graph-cache prefix
bumped 3_2_23 → 3_2_24 (cache_keys.py, dated entry). **Snapshot
rebaseline (2026-08-11, L2_SNAPSHOT_UPDATE=1):** all 12
`backend/tests/snapshots/l2_snapshot_*.sql.json` files — the ONLY diff
is 1295 `"mech"` occurrences removed from edge objects; no node/edge
construction, ordering or seed selection changed (verified by
`git diff` against the pre-rebaseline snapshots).

**Under the model:** walks read `PhysicalEdge`s (source→target paths
are model-level; no occurrence-level fixpoint needed — see §2 note on
the 100-round cap at 813-819); lines come from PhysicalField's
line info (design §3); `_carry_edge_info` stays as the projection of
PhysicalEdge → display edge.

### 1.9 dml_dml_ proxy chaining (#12) — historical, verify before assuming it exists

- **Not present in the current tree.** Grep `dml_dml_` hits only docs
  (`tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:4076,4173-4174`;
  `wiki/SOLUTION_DESIGN.md` J12-10 §1/§4; `wiki/REQUIREMENTS_TRACEABILITY.md`
  references). No commit in the current branch history ever contains it
  in `backend/app` source.
- Its *current manifestation* is the Sync-2 dml_ phantom proxies
  (1.3) — when a dml_ phantom's parent is itself a DML target, chains
  of copies used to form; today the R11-2 (target,label) exists-check
  (1174-1177) and the `dml_` dup guards keep it at one generation.
- **Stage 3 must not search for "the dml_dml_ code"** — the item is
  dissolved by deleting Sync 2; the old chains cannot exist once
  proxies die.

---

## 2. Walker contract — what the walkers need from the model

`compute_field_flow` (lineage.py:556-820) and `filter_by_field_flow`
(823-848) are the ONLY flow walkers (L2; legacy
`compute_field_lineage`/`filter_relevant` 60-402 stay for L1 until
stage 4). `flow_targets` (984-1024), `flow_source_id` (1027-1042),
`classify_flow_roles` (897-944) are their role helpers. The L2
payload walks (`_closure_walk`/`_downstream_walk`, l2_builder.py:
1186-1341) walk the FINAL display edges — they keep working unchanged
as long as the display edges carry the carried info (§1.8).

### 2.1 What the walker reads today (per occurrence node/edge)

Per node (`graph_service.py` build_graph_data carries them, 177-209):
`id, label, variable_type, defined_in, is_output, source_tables,
source_columns, context, stmt_idx, line_start, line_end, table_name,
field_name, sql_expression, node_type`. Per edge (229-245):
`edge_type/relationship, operation, containment`.

### 2.2 Zone sets (exact current lines)

| Set | Members | Line |
|---|---|---|
| `FIELD_LIKE` | column, cte_column, literal, aggregate, expression, case, transform, window | lineage.py:418-419 |
| `FIELD_LAND` | REF, TRANSFORM, AGGREGATE, WINDOW, COMPUTED | lineage.py:425 |
| `NEVER` | TABLE_FLOW, SUBQUERY, SET_OP, CORRELATED, INDIRECT, SUBSET, SCHEMA | lineage.py:430 |
| `NON_FLOW_EDGE_TYPES` (R19.5 roles) | ALIAS, SCHEMA, SUBSET | lineage.py:880 |
| `FIELD_LIKE_TYPES` (display-side twin, seed matcher + payload) | same 8 members | highlight_strategies.py:36-44 |

### 2.3 The rules restated as predicates over PhysicalEdge + PhysicalTable

Let `v ∈ FIELD_LIKE` mean `variable_type(v) ∈ FIELD_LIKE`,
`field(v)` = last dotted segment of the label (lineage.py:446-448
`_field_part`), `owner(v)` = the 3-step owner resolution
(`_resolve_owner_holder`, lineage.py:491-525: (1) source_tables[0]
table-like var in same/ancestor context; (2) else qualifier prefix of
label or sql_expression; (3) else the unique same-context table-like
var, ⟐ excluded; `_owner_of` 528-541 maps holder → physical name),
`identity(v)` = `source_tables[0]` else `table_name`/`label`
(651-657), `chain` = {target_table} ∪ identities of admitted
table-like vars (662-676).

| # | Current rule (line) | Predicate over the model | Physical-model meaning |
|---|---|---|---|
| W1 | seeds: field-like vars with `field(v)==target_field` and (`owner(v)==target_table` or `defined_in==PARTITION` with `source_tables[0]==target_table`) (607-625) | `PhysicalField pf : pf.key == (target_table, target_field)` (PARTITION writes: PhysicalField with write-role occurrence `defined_in=PARTITION`) | one dict lookup; PARTITION rule becomes "write-role occurrence of the searched field" |
| W2 | FIELD_LAND edges walked both directions; REF with `operation=="READ"` walked ONLY field→holder (forward), except a reverse read of a var whose field part == target_field (Issue-3) (709-714) | `admit(e, dir) := e.type ∈ FIELD_LAND ∧ ¬(e.read ∧ dir=reverse ∧ field(tgt)≠target_field)` | `read` flag rides the PhysicalEdge; the exception is "the searched field's own read" — an identity fact, not a label scan |
| W3 | ALIAS admitted iff `source_tables[0] == target_table` (715-718) | `admit(e) := e.type=ALIAS ∧ src(e).view_target == target_table` | alias→table mapping is a model edge; the current predicate fails for cross-scope alias labels (p1→loan_final at TOP0) — the model resolves by physical identity |
| W4 | FILTER/JOIN admitted iff either endpoint ∈ seed-zone (719-720; zone = memoized FIELD_LAND BFS from seeds, 632-648) | `admit(e) := e.type ∈ {FILTER,JOIN} ∧ (src(e) ∈ zone ∨ tgt(e) ∈ zone)` | zone = PhysicalField value-graph reachability — same rule, no memo machinery |
| W5 | DML forward-only; backward only for field-like vars carrying the target field part (the value column `'$(load_date)' AS data_dt@213`, P17) (721-734) | `admit(e,dir) := e.type=DML ∧ (dir=forward ∨ (v∈FIELD_LIKE ∧ field(v)=target_field))` | write edges from the model's write role; value appearances are occurrences of the searched PhysicalField |
| W6 | TABLE_FLOW forward-only; (a) table-like source with identity ∈ chain; (b) VT whose context is ancestor-or-equal of a visited field var with target field part (735-754) | `admit(e,dir) := e.type=TABLE_FLOW ∧ dir=forward ∧ (identity(src)∈chain ∨ VT-ancestor rule)` | chain = physical identities of admitted tables; the VT-context test (context-string prefix matching) becomes the model's containment/CTE-fed role |
| W7 | NEVER + unknown types: no admission (755-756) | `admit := False` for everything else | SCHEMA/SUBQUERY/SET_OP/etc. are structural — never value flow |
| W8 | owner-holder admission: every admitted field-like var admits its holder (owner table) + the holder's physical table (768-782) | by construction: a PhysicalField's table is its parent | disappears |
| W9 | container rule: context segments `CTE{X}` admit the CTE var (784-791) | `cte_fed` role / containment edges on the model | model edge, not context-string parsing |
| W10 | same-table bare reader: table/view var with `identity==label ∈ chain` admits (Issue-3, 803-812) | `read` role of the PhysicalTable: reader instances are occurrences of the same PhysicalTable | disappears — one physical node is both writer and reader instance |
| W11 | containment exclusion: `_is_containment(ed)` (dict-key + attr forms, 433-443) applied at adjacency build (590-591) and filter output (843) | `¬e.containment` — PhysicalEdge carries it (I5, dependency_graph Phase 4b 388-406) | identical predicate, model-sourced |
| W12 | fixpoint: expansion + identity rounds alternate until stable, capped at 100 rounds (683-819; cap warning 816-819) | single walk over the model DAG | no fixpoint — monotonicity is structural |
| W13 | `filter_by_field_flow` output: nodes in closure, edges with both ends in closure ∧ ¬containment (836-843) | same, over model closure | identical projection |
| W14 | roles: `flow_source_id` = label-scan for table/view with label==target_table (1027-1042); `flow_targets` = DML write targets whose write leg `output→T` has both ends in closure (984-1024, `_dml_write_targets` 947-964, `_is_write_leg` 967-981); `classify_flow_roles` = net in/out over flow edges (897-944) | `PhysicalTable` with `flow_source` / `write` role; write leg = model write-role edge | label scan dies; role counting stays but reads model roles |

### 2.4 What the L2 payload walks consume (they stay display-side)

`_closure_walk` (l2_builder.py:1186-1250): final L2 edges' carried
`_src_label/_src_line/_tgt_label/_tgt_line` + `is_target` field ids
(closure entries from 1555) + adjacency built from final edges
(1556-1560). `_downstream_walk` (1253-1341): final flow edges
(`flow_adjacency`, SCHEMA/SUBSET excluded, 1576-1579), flow targets =
`_dml_origin ∧ ¬_value_edge` targets (1565-1566), `tgt_key_to_target`/
`write_line_by_target` from write legs (1571-1583), `⟐ output` id set
(1584-1587). Under the model these become walks over
`PhysicalEdge`s projected to the display edges — the carried fields are
still attached per edge, so `highlight_strategies.single_line`
(highlight_strategies.py:36-44 registry, payload derivation from
carried info only) is untouched by stages 2/3.

---

## 3. Stage checklist (stages 2/3/4)

### Stage 2 — L2 consumes the model for node construction; ids/labels byte-identical

**Files touched:**
- NEW `backend/app/extractor/physical_model.py` (or `services/` — decide
  at execution; it must be built from the analysis result, so
  `extractor/` is the natural home) — model build + lookup API.
- `l2_builder.py` — `_classify_compound_nodes` (230-577) becomes a
  projection of the model; `_compute_target_and_direct_ids` (161-227)
  may read the model for the seed (but output must stay byte-identical,
  so the predicate path may remain until stage 3).
- NEW `backend/tests/test_physical_model.py` — stage-1 invariants
  (design §9): `fin_query4_merge_upsert.sql` gps_accounts once /
  roles {read, merge_target} / `balance` one PhysicalField;
  `06_merge_update.sql` customer_summary once / target alias view;
  flagship `BDM_ACC_LOAN_INFO_SUP_M.sql` model ≡ current merged
  display graph (byte-level).

**Machinery deleted:** none (stage 2 is additive; the merge/proxy
machinery stays behind the projection so ids/labels stay byte-identical).

**Gate/snapshot harness must show:** Jaccard GREEN **unchanged**
(`docker exec gps-sql-backend python3 -m pytest tests/ -v`; the gate is
`tests/test_jaccard_benchmark.py`, floors bdm 1.0/1.0/1.0, sup
0.9/1.0/1.0 per MEMORY — re-measure before/after; `tools/run_benchmark.sh`
is the old ground-truth script — the live gate is the pytest one).
Frontend vitest unchanged.

### Stage 3 — walkers + seed search consume the model; proxies removed; ids may change

**Files touched:**
- `lineage.py` — `compute_field_flow` (556-820) rewritten over the
  model per §2.3; `filter_by_field_flow` (823-848), `flow_targets`
  (984-1024), `flow_source_id` (1027-1042), `classify_flow_roles`
  (897-944), `_dml_write_targets` (947-964), `_is_write_leg` (967-981)
  follow; zone sets (418-430) fold into the model's predicates (keep
  the constants — the payload and tests reference them).
- `l2_builder.py` — DELETE: P1 seed copies (546-575),
  `_sync_alias_and_dml_fields` (1069-1183) incl. sync_ and dml_
  proxies, `_map_search_target_ids` (580-601) if the merge is gone,
  `_build_id_map` (604-624) shrinks to occurrence→PhysicalTable.id.
  `_classify_compound_nodes` field dedup (460-467, 508-515) follows
  the model (one PhysicalField per (table,field) → one display field).
- `graph_service.py` — only if the model needs cache serialization
  (see §4.1).
- Tests: `test_jaccard_benchmark.py` — replace the `dml_`-prefix
  phantom-dup guard (368-388; wired 425, 446) with a PhysicalField
  uniqueness invariant; re-anchor any label/line pins that moved;
  `test_mech_payload.py` R11-2 class (58-77) becomes a model test.
- `VERSION` bump + CLAUDE.md + `cache_keys.py` if shape changed (§4.1).

**Machinery deleted:** all of §1.3 (three proxy families + sync
function), §1.2's occurrence-level seed matching, §1.5's expression/
unknown fallbacks if the model parenting holds (480-484, 519-535).

**Gate/snapshot harness must show:** Jaccard GREEN at **re-anchored
floors** (design §7 stage 3: "ids may change → documented diff,
re-anchor"); full suite green; highlights byte-exact
`[[18,18],[43,43],[158,158],[160,160]]` preserved (v3.3.140 verified
target). Frontend vitest re-run (session id-based state, §4.3).

### Stage 3 — EXECUTION (Team S3, 2026-08-11) — documented diff

**Done.** Walkers + seed search consume the physical model; the three
proxy families are deleted; `GRAPH_CACHE_PREFIX` bumped to
`graph_3_2_22` (cache_keys.py). Working tree vs git HEAD (2963641,
after Team L1's Stage 4a — no file overlap). Snapshot rebaseline
(L2_SNAPSHOT_UPDATE=1) covers EXACTLY the diff below — 5 of 13 files
change, 8 stay byte-identical.

**Call sites (model built at extraction/cache time, passed down):**

| Site | Change |
|---|---|
| `dataflow_service.py` `get_level2_graph` | hit path: `build_physical_model(graph_data)` fallback when the analysis-cache model is missing; miss path: build from `result` after `_atomic_write_text`; the relevance-filter call passes `physical_model=` (3 edits) |
| `lineage.py` `compute_field_flow` | walks `pm.edges` (PhysicalEdge adjacency, occurrence-level source_id/target_id; I5 containment excluded), seeds via `pm.fields[(target_keys, field)].occurrence_ids` ∩ FIELD_LIKE (W1), `pm.occurrence`/`pm.entity_of_id` for owner/identity/chain lookups; `physical_model` REQUIRED (TypeError when None) |
| `lineage.py` `filter_by_field_flow` | forwards the model to `compute_field_flow` |
| `lineage.py` `flow_targets` / `flow_source_id` | write-leg walk over `pm.edges` (DML edges, target-endpoint table keys); seed table via `pm.occurrences` occurrence index — no display-node label scanning |
| `l2_builder.py` `_compute_target_and_direct_ids` | model-union seed: `{occ for (tkey,fname),fld in pm.fields if fname==field} ∩ FIELD_LIKE_TYPES` PLUS the J12-9 label predicate (`label.rsplit(".",1)[-1] == field`) PLUS the `source_columns` rsplit predicate — union purely ADDITIVE (J12-9 kept semantics; model=None falls back to the two predicates only) |
| `l2_builder.py` `_classify_compound_nodes` / `_build_id_map` / `_attach_flow_payload` | consume `physical_model` for entity/occurrence lookups (stage-2 signature, unchanged) |
| `l2_builder.py` `_simplify_dml_edges` | returns only `new_edges` (the dml_pairs collection it fed to the deleted sync phase is gone) |

**Machinery deleted (never-patch rule — no dormant code):**

- `_sync_alias_and_dml_fields` (l2_builder) — the sync_/dml_ proxy
  synthesis: `sync_{vid}_{keeper[:8]}` copies and `dml_{fn[id]}_{tgt_tid[:8]}`
  phantom fields, and the `dml_pairs` collection in `_simplify_dml_edges`
  that fed them.
- P1 seed copies `seed_{id}_{keeper[:8]}` (l2_builder) — the seed field
  instance is now the model entity; it renders on the searched table's
  compound and on the alias/CTE/target compounds that carry the same
  PhysicalField occurrences.
- `lineage.py` owner resolution heuristics (`_owner_of` →
  `_resolve_owner_holder`, `_find_labeled`) — same-context-or-ancestor
  holder-VAR label scans replaced by model entity attribution.

**Walker seed-semantics change (the ONE root cause of every snapshot
diff):** the old walker resolved a seed candidate's owner by scanning
for a same-context holder VAR labeled `source_tables[0]`; that fails for
cross-context references (alias reads), CTE-self references,
CTE-output containers, and unqualified aggregates with empty
source_tables — old seeds were EMPTY there → search_matched False. The
model-backed W1 seeds from extraction-time entity attribution
(`pm.fields[(target_keys, field)].occurrence_ids`), so those searches
now match (display/search consistency — the field IS shown under the
searched table). This is the intended model-truth diff.

**Documented snapshot diff (probe-verified, old-pipeline replay at
git HEAD; fixture seeds in parentheses):**

| Snapshot | Diff |
|---|---|
| 00 BDM_ACC_LOAN_INFO_SUP_M.sql | FULL VIEW 228→211 nodes (−17 proxies: 13 `dml_fld_*_l2_tbl_6` + 4 `sync_fld_*_canon`); seed ('bdm_acc_loan_info','lending_ref') → ('rollover_loan_info','lending_ref') — old seed EMPTY (owner=None), new 9-node/14-edge closure; fixture-seed filtered view byte-identical under PYTHONHASHSEED=0 |
| 01 01.sql | seed unchanged ('customer_total_return','ctr_customer_sk'); fixture-seed filtered view +2 nodes/+3 edges — new W1 seeds BOTH occurrences (WHERE ref + CTE-output def) → closure gains the CTE body production sr_customer_sk → ctr_customer_sk |
| 02 02.sql | seed ('web_sales','sold_date_sk') → ('wscs','sales_price') — old seed EMPTY, new 21-node/34-edge closure (fixture seed = first candidate whose filtered build matches) |
| 05 05.sql | seed ('⟐ union0','return_amt') → ('ssr','sales') — old seed EMPTY, new 21-node/28-edge closure |
| 08 08.sql | seed ('⟐ V1/subq/A2/union0','ca_zip') → ('⟐ output','SUMss_net_profit') — old seed EMPTY, new 4-node/4-edge closure (unqualified aggregate now entity-attributed) |
| 03/04/06/07/09/10/11 | byte-identical (no change) |

**J12-15 preserved (coordinator directive):** `_simplify_dml_edges`
still picks ONE global trunk — the first "⟐ output" intermediate in
table_nodes order — and rewrites every raw DML edge's source to it, so
statement 2's write leg `output → rrcdm@211` still hangs off
output@L160 and output@L211 dead-ends in multi-DML scripts (12/334
samples; BUG_ANALYSIS J12-15). The rebaseline below does NOT change
this — the 00 full-view diff is only the 17 proxy nodes; the dead-end
edges stay. Fix = per-statement trunk selection, stage-4 scope
(§1.7). If the walker/closure changes had incidentally fixed it, that
would be reported as an intentional fix — it did not.

**Edge-order note (not a regression):** the 00 filtered view's raw-edge
order rotates with PYTHONHASHSEED (extractor iterates a raw-edge set);
the OLD pipeline rotates identically — verified by replaying old
lineage.py + l2_builder.py under both seeds. The harness runs
PYTHONHASHSEED=0 where new == old order byte-identically.

**Cache prefix:** `GRAPH_CACHE_PREFIX = "graph_3_2_22"` (was
3_2_21) — L2 payload shape changed (proxy ids gone from served
output); extractor_version NOT bumped (extraction is unchanged).

**Tests added/updated (model-backed pins):**
- `test_physical_model_equivalence.py` — `display_pipeline` passes the
  model to matcher/walker; `_simplify_dml_edges` single-return; sync
  helper DELETED; `test_keeper_field_labels_in_model_universe` +
  `test_no_proxy_nodes_in_display_output` (no seed_/sync_/dml_ ids in
  table/field/edge ids).
- `test_walker_gaps_e3.py` — the 2 synthetic PARTITION-scoping tests
  build the model from graph-data form and pass it to
  `compute_field_flow` (graph-data form builds edges via the
  source/target → source_id/target_id normalization).
- `test_flow_roles.py` — `_raw_graph` returns `(graph, model)`;
  `flow_targets`/`flow_source_id` call sites pass `physical_model=`.
- `test_dataflow/test_l2_table_dedup.py` — matcher call passes the
  fixture's `physical_model`.
- `test_l1_l2_integration.py` — CW4 phase-split mirror kept: the
  relevance-filter/matcher/simplify/flow-role phases take the model
  (same phases, same order — byte-identical graph).
- `test_jaccard_benchmark.py` — the `dml_`-prefix phantom-dup guard
  extended to the stronger stage-3 invariant: ANY seed_/sync_/dml_
  proxy field id in the served output is a violation (R11-2 shape
  kept for dml_ dups). Gate GREEN with UNCHANGED floors (bdm
  N=1.0/1.2 E=1.0/1.0 H=1.0/1.0; sup N=1.0/1.125 E=1.0/1.0
  H=1.0/1.0) — the Jaccard fixture is NOT rebaselined.

**Contract note (from Team L1's Stage 4a commit message):**
`build_physical_model`'s graph-data {'nodes','edges'} form — the
source/target → source_id/target_id normalization makes Pass 3 build
edges from graph-form edges too (verified: REF p1→e1 builds a model
edge; L1 no longer uses that form).

### Stage 4 — l1_builder + graph_service adopt; delete keeper-merge/proxy machinery; alias views

**Files touched:**
- `graph_service.py` — P4 table_fields (262-285) + P4-ext DML fields
  (287-310) + P5 alias sync (312-334) + alias_map pre-build (138-143)
  + raw-graph parent assignment (252-260) all become model lookups.
- `l1_builder.py` — `_absorb_p4` (804-812), lineage pair extraction
  (855-879), multi-hop expansion (881-911) read the model;
  `compute_field_lineage` (lineage.py:60-324) may be retired or kept
  as a compat shim — L1 filter entry points: `_build_l1_graph`
  (l1_builder.py:252), `_filter_l1_by_lineage` (dataflow_service.py:
  191), `get_level2_graph` filter call (dataflow_service.py:447-450).
- `l2_builder.py` — DELETE: label-keyed keeper merge (323-327,
  396-398), `merged_original_ids` plumbing (326, 381, 397, 400, 464,
  466, 512, 514), `_build_id_map` (604-624) and all id_map consumers
  (696-697, 860-883, 965-966, 1656/1660), alias compound dedup
  (348-401) → alias views, alias_map reconstruction (260-291),
  `_carry_node_lines`/`_stmt_anchor_lines_from_nodes` derivation
  (1357-1412) if statement anchors ride the model.
- Alias views: render alias contexts as boxes referencing
  PhysicalTable (frontend + graph_service shape — display labels
  `p1@29` stay stable per design §5 "node/edge display labels kept
  stable").

**Machinery deleted:** the entire §1.1/§1.3/§1.5/§1.6 inventory except
the DML routing rewrite (§1.7, which design §4 keeps as the write-event
display). `dependency_graph.py` stays UNCHANGED (extraction still emits
per-occurrence deps — the model consumes them).

**Gate/snapshot harness must show:** Jaccard GREEN at final anchors;
full suite green; frontend vitest green (L1 ids change — persisted L1
graphs in views.json are display caches only, see §4.3).

### Stage 4 — EXECUTION (Team S4, 2026-08-11) — documented diff

**Done.** graph_service + l2_builder adopt the physical model for
table_fields/alias_map/parents and compound classification; the
keeper-merge/proxy machinery is deleted; J12-15's per-statement DML
trunk is implemented; `GRAPH_CACHE_PREFIX` bumped to `graph_3_2_23`.
Working tree vs git HEAD (034eaa2). Snapshot rebaseline
(L2_SNAPSHOT_UPDATE=1) covers EXACTLY the diffs below — the J12-15
write-leg fix on the flagship filtered view is the FIX (documented
here), everything else is the alias-truth diff.

**Call sites (model built at extraction/cache time, passed down):**

| Site | Change |
|---|---|
| `graph_service.py` `build_graph_data` | builds `physical_model = build_physical_model(analysis)` once at top; `alias_map` = projection of the model's alias views (label → canonical entity name, last-writer-wins — replaces the table/view/cte source_tables scan at 138-143); `table_fields` = `{entity.name: sorted(entity.fields)}` for entities with fields, PLUS an alias-label key per alias view carrying the canonical fields (replaces P4 SCHEMA scan + P4-ext DML scan + P5 ALIAS sync at 262-334 — all covered: INSERT columns carry source_tables=[target] so they land on model fields; SCHEMA-edge columns are parented field occurrences); parent assignment (252-260) resolved via the model's occurrence index (`_occ_table_name` owner resolution) instead of the literal-prefix first-match |
| `l2_builder.py` `_classify_compound_nodes` | is_alias = `nid in physical_model.alias_by_var_id` (alias_of truth — the phase-0 alias_map read + node-scan first-writer-wins rebuild are DELETED); alias_parent_id via the model's canonical key → keeper_by_entity (name-scan fallback when the canonical is not yet classified); returns `(table_nodes, field_nodes, alias_map, occ_to_id)` — other_nodes dropped (dead — never populated), occ_to_id replaces `_build_id_map`; every merged-away nid (keeper merge, alias dedup, field dedup) records `occ_to_id[nid] = keeper/field id` instead of `merged_original_ids` |
| `l2_builder.py` `_carry_node_lines` | reads `physical_model.occurrences` (context/variable_type/line_start/line_end/defined_in for every var — the same universe as the full-graph node index, same order → byte-identical statement anchors and spans); `_stmt_anchor_lines_from_nodes` DELETED |
| `l2_builder.py` `_build_id_map` | DELETED — the classification returns occ_to_id; the orchestrator and every phase consume it under the same `id_map` name (endpoint re-pointing semantics unchanged) |
| `l2_builder.py` `_simplify_dml_edges` | gains `physical_model=None`; per-statement trunk selection (J12-15, §1.7) — see below |
| `l2_builder.py` `_assemble_output` | `_clean` deleted (no `merged_original_ids` key exists anymore) |
| `l2_builder.py` `_build_l2_graph` | orchestrator passes `physical_model` to `_simplify_dml_edges`; `_carry_node_lines(table_nodes, physical_model)`; `id_map = occ_to_id` |

**Machinery deleted (never-patch rule — no dormant code):**

- `_build_id_map` (l2_builder) — replaced by the classification's
  occ_to_id (every nid seen during classification maps to its
  compound/field id; merged-away nids map to their keeper).
- `merged_original_ids` plumbing (keeper merge / alias dedup / field
  dedup bookkeeping) — the merge record is now occ_to_id entries.
- Phase-0 alias_map read + Bug-48 fallback + B3/P1 first-writer-wins
  rebuild in `_classify_compound_nodes` — alias detection is the
  model's alias_by_var_id; the parent-resolution fallback map is
  derived from the model's alias views (label → canonical name).
- `_stmt_anchor_lines_from_nodes` — statement anchors ride the model's
  occurrence index (byte-identical anchors, verified by the CW4 mirror
  byte-identity test).
- `_assemble_output._clean` — no key to strip.

**Alias rendering diff (model truth, probe-verified):** display alias
compounds in the flagship FULL view: 16 → 14. `p2@40` (fc375370e2,
vt=subquery, alias_of=None) and `p2@116` (76385e5f13, vt=subquery,
alias_of=None) are derived-subquery aliases — the model keeps them as
their own (name, context) entities (subquery-kind vars are never
aliases of another table) — the display now renders them as
intermediate_table `p2` (was alias_table `p2@40` / `p2@116`).
`p2@199` (JOIN alias of bdm_acc_loan_info_sup, I4 alias_of set) stays
an alias compound. The two changed nodes appear only in the full view
(not in the filtered views) and in no Jaccard fixture → gate-safe. L1
already renders only model alias views as aliases (stage 4a) — L2 now
matches L1. multi_ctx (`test_l2_table_dedup`): p/s/r/a are all
table-type label-rule aliases, all in model.alias_by_var_id — full
parity, no diff.

**J12-15 fix (per-statement DML trunk, §1.7, coordinator-mandated
stage-4 scope):** `_simplify_dml_edges` selects the trunk PER raw DML
edge instead of one global first-⟐ output: for every raw DML edge the
model's `entity_of_id` of the source var is checked — when it is the
`('⟐ output', TOPn)` entity (output VTs are (name, context)-keyed
virtual entities, EXACTLY ONE occurrence each — the raw edge's source
var), the statement's output-VT compound (by original_id) becomes
`stmt_trunk[TOPn]`. Edges whose statement's output VT is absent from
the graph keep the global "⟐ output"-preferred fallback (the legacy
first-intermediate loop). The compound→statement map (`ctx_by_id`:
table compounds' own carried context; field compounds' keeper
occurrence context) selects the trunk per edge: rule 3's dml_out
source, the value edge's target, rule 2's redirect target and pattern
2's rewrite source all use `_trunk_for(e)`. Rule 1/2/pattern-2 guards
change from `!= intermediate_id` to `not in output_ids` (the set of
ALL ⟐ output compound ids) — otherwise the FIXED statement-1 trunk
would be suppressed by rule 1 or re-routed by pattern 2.

Probe-verified flagship (filtered view, `bdm_acc_loan_info.data_dt`):

| Edge | Before | After |
|---|---|---|
| `l2e_73632d4f7c7a_dml_out` (output → rrcdm write leg) | source `l2_tbl_7b217fb63a` (output@L160, TOP0) | source `l2_tbl_236587aa4c` (output@211, TOP1) |
| `l2e_61a65f76a367_value` (data_dt@213 value edge) | target `l2_tbl_7b217fb63a` | target `l2_tbl_236587aa4c` |
| output@L160 (`l2_tbl_7b217fb63a`) | carried the rrcdm write leg + value edge (wrong) | clean — statement-0 (sup) edges only |
| output@211 (`l2_tbl_236587aa4c`) | only read-into-output + SCHEMA (dead-end) | + the rrcdm write leg + value edge |

Edge IDs / highlight_lines / reasons unchanged where endpoints did not
move (ids are computed pre-rewrite from the mapped endpoints — the
write leg's id/hl stay `73632d4f7c7a_dml_out`/211, only the source
changes). R20 reason strings stay truthful (the closure/downstream
walks operate on the FINAL edges — the rrcdm continuation now starts
at output@211). The raw WRITE_READ DML edge (sup@L160 → sup@L223)
maps to a self-loop after keeper mapping and drops in
`_build_edge_list` — unchanged.

**Verified snapshot diff (2026-08-11, rebaselined):** 00
BDM_ACC_LOAN_INFO_SUP_M.sql — the full byte-diff of the rebaseline
(seed `rollover_loan_info.lending_ref`; every other node/edge, all
node fields except the two below, all edge endpoints/lines, and the
seed selection are byte-identical):
- filtered AND full views: `l2e_73632d4f7c7a_dml_out` source
  `l2_tbl_7b217fb63a` → `l2_tbl_236587aa4c` (the J12-15 per-statement
  trunk). The value edge `l2e_61a65f76a367` does NOT appear in this
  snapshot's graphs (absent under this seed in both views) — its
  target change is pinned by `test_l2_stage4.py` instead.
- reason strings (truthful continuation): `l2e_73632d4f7c7a_dml_out`
  now carries `bdm_acc_loan_info_sup@L223` (the raw edge's source
  var) before the `‖⟐ output@L211 → rrcdm_job_log_exec_par@L211‖`
  write leg; `l2e_b4fc03d22434` (read into output @211) now continues
  `→ rrcdm_job_log_exec_par@L211`. Reason text is not stable across
  the fix — the closure walks run on the FINAL (re-trunked) edges.
- full view only: `l2_tbl_5036613a8c`/`l2_tbl_c2751fbae5`
  (p2@40/p2@116) `alias_table` label `p2@40`/`p2@116` →
  `intermediate_table` label `p2` (compound ids unchanged — they are
  content-derived from the original var ids).

Other snapshots change only where multi-statement DML or
derived-subquery aliases exist; single-statement scripts are
byte-identical (the single statement's trunk IS the global
intermediate).

**Cache prefix:** `GRAPH_CACHE_PREFIX = "graph_3_2_23"` (was
3_2_22) — L2 graph JSON shape changed (`merged_original_ids` gone;
per-statement DML routing is a shape change); extractor_version NOT
bumped (extraction is unchanged).

**Tests added/updated (model-backed pins):**
- `test_l1_l2_integration.py` — CW4 mirror updated for the new phase
  signatures (`_classify_compound_nodes` 4-tuple arity, occ_to_id,
  `_carry_node_lines(table_nodes, physical_model)`,
  `_simplify_dml_edges(..., physical_model)`); `test_alias_map_in_graph_cache`
  + `test_l1_pairs_covered_by_table_fields` keep pinning the graph
  payload keys (alias_map / table_fields) — model-projected now.
- `test_dataflow/test_l2_table_dedup.py` —
  `test_classify_compound_nodes_records_merged_nids` rewritten as
  `test_classify_compound_nodes_records_occ_to_id` (merged-away nids
  resolve through the classification's occ_to_id to the keeper);
  `test_merged_original_ids_never_leak` extended to `occ_to_id` never
  leaking (it never exists on nodes at all).
- `test_physical_model_equivalence.py` — `display_pipeline` consumes
  the classification's occ_to_id and passes the model to
  `_simplify_dml_edges`.
- NEW `test_l2_stage4.py` — pins: per-statement trunk (J12-15 —
  flagship filtered view write-leg source == `l2_tbl_236587aa4c`,
  output@L160 carries no rrcdm edge), no keeper-merge remnants (no
  `merged_original_ids` anywhere in classification or output, no
  `_build_id_map` symbol), model-driven alias rendering (p2@40/p2@116
  intermediate, p2@199 alias, alias labels `p1@29` stable),
  graph_service payload keys (alias_map label keys + table_fields
  alias-label keys).

### J12-16 (2026-08-11, user ruling — binding) — fold same-named field instances into ONE display field

**Ruling:** the C-9 per-statement field dedup key drops `stmt_idx` —
same-named field instances from DIFFERENT top-level statements fold
into ONE display field per physical table. Display-only: payload
labels untouched; the ⟐ output VTs stay un-merged (R19.6b); J12-15
stays independent; gate neutrality verified by a full benchmark run
(see below).

**Engine changes (l2_builder.py):**

1. `_classify_compound_nodes` — both dedup sites (column branch ~:536,
   computed branch ~:588) drop `stmt_idx`: `dedup_key =
   (parent_table_id, field_node["label"])`. The keeper is the FIRST
   occurrence; every merged-away nid still resolves through
   `occ_to_id` to the folded field (per-var entity identity is kept —
   `occ_to_id` still records each merged nid).
2. `_carry_edge_info` — the payload carrier gains `_src_ctx` (the raw
   source var's per-occurrence context). The J12-16 fold collapses
   per-statement FIELD identities, so per-statement edge semantics
   must ride the edges themselves.
3. `_simplify_dml_edges` — rule 2's "bypass" test becomes
   per-statement: `dml_sources_by_stmt[TOPn]` (raw DML edge sources
   bucketed by their occurrence context; unresolved contexts land in
   a `None` bucket consulted from any statement — no model ⇒
   everything lands there, reproducing the global pre-merge
   semantics). A folded field that is a DML source in statement A
   only (the flagship sup data_dt: write column @160 in TOP0, reads
   @223/225 in TOP1) is NOT a bypass in statement B — pre-merge the
   per-statement field split provided that granularity; the fold
   erases it, the per-statement map restores it.
4. `_build_l2_graph` — orchestrator order change: `_simplify_dml_edges`
   now runs BEFORE `_combine_edges` (and the promotion). The folded
   field's per-instance edges (identical mapped endpoints, different
   occurrences) diverge ONLY through rule 2's retarget: the TOP0
   instance (data_dt@160→sup@160) redirects to the statement's ⟐
   output (matches the canonical X2 `data_dt→⟐output REF@160`), the
   TOP1 instance (data_dt@225→sup@223) stays on the read target
   (canonical rows 18/21 `data_dt→sup REF@223`). `_combine_edges` is
   keyed on (source, target, edge_type) — before the retarget the two
   instances are identical there and collapse (first-wins, dropping
   the TOP1/223 form). The mirror in
   `test_l1_l2_integration.py::_display_pipeline` follows the same
   order.
5. Rule 2 recomputes the retargeted edge's id from its NEW endpoints
   (`md5(source+target+edge_type)`, mirroring rule 3's `_dml_out`
   pattern) — the two surviving instances must carry DISTINCT ids
   (the benchmark's per-edge `used` id set consumes ids on first
   match; a shared id would break the second row).

**Side effect of the reorder (full view only, pinned):** the
DML-simplification retarget now fires BEFORE the field promotion, so
the sup write statement's column-read bypass REF (L160, a non-target
field) is redirected through the statement's ⟐ output BEFORE its
field source promotes to sup — it survives as `sup→output REF@160`
instead of being dropped as a sup→sup self-loop. Net-flow role of
bdm_acc_loan_info_sup in the full view: waypoint (3/3) → source
(4/3); `test_flow_roles.py::test_full_view_roles_evidence` re-pinned
with the explanation.

**Probe-verified flagship payload (post-fix):**

- Filtered view (`bdm_acc_loan_info.data_dt`): ONE sup data_dt field
  (`fld_e2b38f37a7`, parent bdm_acc_loan_info_sup) with incidents
  [160, 223, 225]:
  - `l2e_674c282afd9f` data_dt→output REF hl=160 kind=read (the TOP0
    instance retargeted; recomputed id)
  - `l2e_15293f1e56e7` data_dt→bdm_acc_loan_info_sup REF hl=223
    kind=read (the TOP1 instance — was dropped by the combine
    pre-fix)
  - `l2e_9045ad741fa4_value` data_dt→output TABLE_FLOW hl=160
    kind=write (value edge)
  - `l2e_c06ed12e29b5` data_dt→bdm_acc_loan_info_sup FILTER hl=225
    kind=field flow
- Full view: the same field carries incidents [160, 199, 202, 223,
  225] — exactly the ruling's expected set.
- J12-15 intact: `l2e_73632d4f7c7a_dml_out` (output@211→rrcdm, TOP1)
  and `l2e_3b8e8e62b668_dml_out` (output@160→sup, TOP0) write legs
  unchanged; value edge target output@211; no dead-end output VTs.

**Gate neutrality (THE gate, full run):** bdm
N=1.0000/1.2857 E=1.0000/1.0000 H=1.0000/1.0000; sup
N=1.0000/1.2857 E=1.0000/1.0000 H=1.0000/1.0000 — floors met
(bdm 1.0/1.0/1.0, sup 0.9/1.0/1.0) with recall 1.0 on every
feature. The fixture is NOT rebaselined: the fold is display-only
(node realization matches by normalized label + incident-line sets;
the merged field realizes the canonical data_dt@160/225 node with
incidents 160/223/225). Node precision ratios moved 1.2/1.125 →
1.2857/1.2857 (one fewer served node per seed — the fold).

**Snapshot rebaseline (documented BEFORE the rebaseline run):
`L2_SNAPSHOT_UPDATE=1` covers EXACTLY the J12-16 fold:**

- 00 BDM_ACC_LOAN_INFO_SUP_M.sql: filtered byte-identical; full
  211→204 nodes (7 folded field instances gone — including
  `fld_faa927ddff`, the stmt-1 sup data_dt; its keeper
  `fld_e2b38f37a7` survives), 470→471 edges (26 new / 25 gone ids —
  the retargeted-edge id recompute + fold rewires; e.g.
  `l2e_674c282afd9f` data_dt→output REF@160 and the surviving
  `l2e_15293f1e56e7` REF@223 replace the single pre-fix REF form).
- 01.sql (tpcds): filtered 8→7 (1 folded field gone), full 26→23
  (3 gone); edge ids churn where the retarget recomputed ids
  (12→12 / 35→35 counts).
- 02.sql (tpcds): filtered byte-identical; full 83→75 (8 gone),
  74→74 edges (3 new / 3 gone ids).
- 05.sql (tpcds): filtered 15→14 (1 gone), full 154→149 (5 gone),
  edge counts 26→26 / 237→237 with id churn.
- All other snapshot scripts byte-identical (no multi-instance
  same-named fields, no full-view DML-bypass REF in the role
  balance).

**Tests updated (pins to the FIXED payload, none weakened):**
- `test_dataflow/test_b_series_l2.py::test_c9_per_statement_dedup` —
  loan_id appears ONCE under the keeper (was TWICE, TOP0+TOP1); the
  single folded field keeps the FIRST occurrence's identity (ctx
  TOP0); C-9 header docstring updated to the (parent, undecorated
  label) key.
- `test_dataflow/test_l2_table_dedup.py` — comment updated (display
  fold vs per-var entity identity; assertion unchanged).
- `test_flow_roles.py::test_full_view_roles_evidence` —
  bdm_acc_loan_info_sup waypoint → source (the reorder side effect
  above), documented in the docstring.
- `test_l1_l2_integration.py` — CW4 mirror phase order matches the
  orchestrator (simplify before combine).

---

## 4. Risks

### 4.1 Cache shape / versioning

- `GRAPH_CACHE_PREFIX = "graph_3_2_21"` (cache_keys.py:49) — the single
  contract constant. Any graph-JSON shape change (model serialized into
  the graph cache) needs a prefix bump + `format_version` 5.
  `format_version` is checked at l2_builder.py:78-79 (`>= 4` AND
  `extractor_version` match). **Asymmetry:** `dataflow_service.py:
  371-372` checks ONLY `extractor_version`, never `format_version` —
  the prefix bump is what protects it today. If stage 3 changes the
  graph shape, bump the prefix in the SAME round or get_level2_graph
  will serve the old shape.
- If the model is NOT serialized (rebuilt from the analysis cache at L2
  build time), the graph shape is unchanged → no bump; but the
  analysis cache JSON shape changes if the model is built inside
  `run_full_analysis` (adapter.py:64; stamp at adapter.py:147) →
  **bump `EXTRACTOR_VERSION`** (variable_extractor_v2.py:34 =
  "2026-08-10.3") — both cache readers gate on it (l2_builder.py:79,
  113; dataflow_service.py:372, 406; folder_index_service analysis
  reads).
- J12-8 (restart-time cache purge) wipes `graph_*/analysis_*/schemas_*`
  at every container start — it reduces but does NOT remove the need
  for the stamp/bump discipline (dev reload purges too).
- Cache readers that will need the model or a compat shim:
  `_load_or_build_graph` (l2_builder.py:49-143), `get_level2_graph`
  (dataflow_service.py:326-436), `_absorb_p4` (l1_builder.py:804-812).
- **Do not** couple the model to `schemas_{key}.json` —
  `infer_table_schemas` (schema_inference.py) is the R18 validation
  helper, not identity.

### 4.2 Tests pinned to ids/labels/proxy behavior

- `tests/test_jaccard_benchmark.py` — matching is **label +
  incident-line based** (docstring 79-85: served ids are opaque
  `l2_tbl_*` hashes; `_endpoint_ok` uses NORMALIZE_MAP label + line in
  incident-edge highlight set) — resilient to id churn. BUT:
  - `dml_phantom_field_dups` (368-388) pins the `"dml_"` id prefix and
    is wired into `compute_seed` (425) and the problem report (446) —
    the R11-2 regression guard. It must be REPLACED by the
    PhysicalField uniqueness invariant (stage 1 test) and the guard
    deleted at stage 3.
  - `candidates()` sorts response edges by `e["id"]` (determinism) and
    the used-set is "deterministic by edge id" (85) — id churn is fine
    as long as the sort stays deterministic within one response.
  - `*_dml_out` / `*_value` edge-id suffixes appear only in comments
    (39, 330) — the write-leg semantics are pinned by
    `flow_kind='write'` (R19.3), not ids.
  - R19.3 chain incidence checks (`r19_3_chain_problems`) use incident
    highlight lines, not ids.
- `tests/test_mech_payload.py` — `TestR11_2DmlPhantomDedup` (58-77)
  pins the dml_ phantom DISPLAY (one data_dt child under rrcdm;
  no (parent,label) dup among `dml_` ids); `TestR11_3RemainingPayload`
  (R26.3 rewrite of the old R11-3 class) pins compound
  `line_start/line_end/defined_in` (64..159, 160..210) + the R25
  per-edge payload AND guards `"mech" not in d` — the R26.3 removal is
  itself pinned. The old mech-sentence pins (clause JOIN, ref_line 155,
  alias p6) are deleted with the payload.
- `tests/jaccard_canonical.py` — canonical rows use `label@line`
  endpoints (e.g. `l2_tbl_9c126725f4` appears only as a comment, 81) —
  label-keyed, resilient.
- `tests/test_design_compound.py` — structural (no duplicate ids, 193-201).
- `tests/test_l1_l2_integration.py` (7 hits), `test_walker_gaps_e3.py`
  (3) — grep for label/line pins before touching the walker.
- `tests/test_i1_definition_lines.py`, `test_graph_integrity.py` — no
  id pins.

### 4.3 Frontend id/position coupling

- Node/edge ids feed cytoscape element identity DURING a session:
  `selectedEdgeId` → `cy.getElementById(selectedEdgeId)`
  (DataFlowGraph.jsx:114-117); `pickAutoEdge` (DataFlowApp.jsx,
  `utils/pickAutoEdge.js` — filters on `e.id` non-empty, 27, and
  seed-node `line_start/line_end` from node data, 39-44).
- **No server-side id persistence for L2**: views.json children store
  only `view_id`/script names (dataflow.py:205-222); L2 is rebuilt
  fresh per request (get_level2_graph). **But** `_persist_search_view`
  embeds the FULL L1 graph into views.json (dataflow_service.py:
  542-554) — L1 node ids change at stage 4 → persisted views carry a
  stale embedded graph until re-fetched (level1 GET rebuilds fresh,
  dataflow.py:228-247, so impact is a stale cached display, not data
  loss).
- Layout positions are NOT persisted across fetches: `useCytoscapeGraph`
  re-lays out per graph data; field positions are frozen relative
  offsets re-derived on drag (`positionTableFields`,
  useCytoscapeGraph.js:100-115; layoutCore.js). Id changes do not break
  layout, only session element identity + `pickAutoEdge` heuristics.
- Frontend vitest: `pickAutoEdge.test.js` uses opaque ids ('n1','e2')
  — resilient; `DataFlowGraph.test.jsx`/`EdgeReasonPanel.test.jsx` —
  re-run at stage 3 (role-badge label mutation is per-session,
  useCytoscapeGraph.js:114-122).

### 4.4 Semantics traps found during the inventory

1. **J12-9 was ALREADY applied** — do not re-implement the 5 paths; the
   one-predicate lives at l2_builder.py:193-197 and must not regress
   to `name == target_full` (would drop alias-copy seeds, Jaccard
   regress — bug-list J12-9 "Kept semantics").
2. **ALIAS walker rule is identity-broken today** (W3): `source_tables[0]
   == target_table` fails for aliases whose label names a different
   physical table in another scope (p1→loan_final at TOP0) — the
   model's alias-view mapping fixes this by construction; the stage-3
   diff must be documented (canonical rows with p1 endpoints).
3. **The benchmark is label-based** — the design's "ids may change"
   risk is smaller than feared for the gate itself, but the dml_
   pins (4.2) and payload byte-equality (highlights
   `[[18,18],[43,43],[158,158],[160,160]]`) are the real gate.
4. **`_stmt_anchor_lines_from_nodes` (1357-1376) re-derives statement
   anchors from node lines at L2 build time** — reconstruction in the
   never-patch sense; the physical model should carry statement
   anchors (extraction facts) and this derivation dies at stage 4.
5. **`compute_field_flow` 100-round cap (813-819)** — a symptom of the
   occurrence-level fixpoint (W12); the model walk needs no cap.
6. **`⟐ output` string-prefix sentinel matching** at l2_builder.py:346
   (B5 label sanitation), 949 and 1586 — replace with the write-role
   reference; the "⟐ " prefix on table_name is relied on by
   field-parent matching and payload output detection.
7. **`_compute_target_and_direct_ids` also drives `direct_ids`
   (upstream+downstream BFS, 199-227) for `field_group:
   direct/indirect`** — under the model, "direct" = value-graph
   reachability from the seed's PhysicalField; keep the display
   semantics (field_group) byte-identical at stage 2.
8. **`search_matched` contract** (l2_builder.py:1795; dataflow_service
   not-in-flow fallback 462-466): depends on `target_mapped or
   direct_mapped` — the model lookup must produce the same "the
   searched field is not in this script" signal.
9. **Sync 1's alias-instance pick (1123-1141)** silently skips when no
   qualifying instance holds fields — a behavior the alias-view model
   makes deterministic; the canonical-row pins around p1 must be
   re-verified at stage 3.
10. **Legacy walkers stay byte-identical**: `compute_field_lineage`/
    `filter_relevant` are L1 + legacy consumers (sql_highlight_service
    re-export per CLAUDE.md) — stages 2/3 must not touch them (stage 4
    retires them).

---

## Appendix A — inventory counts

| Category (§) | Machinery sites | File:line anchors |
|---|---|---|
| 1.1 keeper merge + id map | 9 sites / 3 functions | l2_builder.py 247, 252, 323-327, 396-398, 460-467, 508-515, 604-624, 594-595, 1681-1682 |
| 1.2 seed matching | 2 (J12-9 predicate; walker seed loop) | l2_builder.py 193-197; lineage.py 607-625 |
| 1.3 proxy synthesis | 3 families + 1 sync function | l2_builder.py 546-575 (seed_), 1142-1156 (sync_), 1161-1183 (dml_), 1069-1183 (function) |
| 1.4 merge_target split | 1 (missing merge branch) | l2_builder.py 308-309 vs 323 |
| 1.5 floating-field rescue | 4 parenting paths (+1 L1) | l2_builder.py 480-484, 519-535, 864-883, 1123-1141; l1_builder.py 710-789 |
| 1.6 alias compounds | 7 sites | l2_builder.py 310-312, 330-331, 348-401, 379-382, 260-272, 274-291, 1110 |
| 1.7 DML routing | 6 mechanisms | l2_builder.py 943-951, 958-972, 980-983, 985-992, 994-1004, 1005-1020, 1025-1051 |
| 1.8 payload machinery | 6 (contract, not reconstruction; R26.3 removed the 2 mech rows) | l2_builder.py 627-666, 1186-1250, 1253-1341, 1525-1636, 1387-1412, 1357-1376 |
| 1.9 dml_dml_ chaining | 0 (historical — grep-verified) | docs only |
| 2 walker contract | 14 rules (W1-W14) | lineage.py 556-848 + helpers |
| 4.2 test pins | 5 files | test_jaccard_benchmark.py 368-388/425/446, test_mech_payload.py 58-77/91-130 (91-130 = R26.3-rewritten class), jaccard_canonical.py, test_l1_l2_integration.py, test_walker_gaps_e3.py |
| 4.3 frontend ids | 3 sites | DataFlowGraph.jsx 114-117, pickAutoEdge.js 27/39-44, dataflow_service.py 542-554 |

---

## Appendix B — L2 snapshot rebaseline log

> Dated entries: every L2_SNAPSHOT_UPDATE=1 rebaseline, with the
> engine-side cause and the exact inventory. Required BEFORE rebaseline
> (binding rule) so snapshot diffs are never silently swallowed.

### 2026-08-11 — S3 occurrence-aware anchors (extractor, v3.3.152)

**Engine cause:** `variable_extractor_v2._statement_anchor` first-matched
the head-token subsequence, so the k-th walk of a textually identical
statement/CTE/subquery body anchored at the FIRST occurrence. The scoped
def-site lookup then collapsed onto the first occurrence's lines ("first
name occurrence beats definition" — the S3 bug family; residual in
tpcds q14/q39 join aliases and, corpus-wide, every repeated
statement/subquery body). Fix: `_anchor_head_last` — the k-th anchor
call for a head searches STRICTLY AFTER the last line already matched
for that head (walks are in stream order per head).

**Verification before rebaseline:** every shifted var line was checked
against the script text — the new line is the var's own occurrence
(definition/subquery body line); the old line was the first occurrence.
Flagship + corpus alias probes: 324 files, 962 alias vars, 0 BAD.

**Inventory (test_l2_snapshot, 6 of 12 files; L2_SNAPSHOT_UPDATE=1):**

| File | Node changes | Edge changes |
|---|---|---|
| 00_BDM_ACC_LOAN_INFO_SUP_M.sql | 1 line_start: ⟐ p2 31→107 (second `LEFT JOIN (SELECT podcg…FROM ods_hub_lsacmsp…)` block, L108-116) | 27 highlight_line/reason: 31/33/35 → 107/109/111 (p2 join block, p_dt) |
| 04_04.sql | 2 line_start: union1 arms 2→25, 2→48; 2 flow_role target→source (catalog_sales@36, web_sales@59) | 65 highlight_line/reason (union arm reads + value copies; aggregate steps year_total@10→@33/@56) |
| 05_05.sql | 1 line_start: 111→117 | 5 highlight_line/reason; filtered view: 1 reason `sales@L113 → sales@L119` (seed closure) |
| 08_08.sql | 2 line_start: 6→410, 8→412 (count(*) subquery block L410-419) | 38→37 edges: REF `cnt@L413 → customer_address@L9` removed (was first-occurrence collapse); replaced by SCHEMA `⟐ …A1@L412 → cnt@L413` + TABLE_FLOW `customer_address@L414 → ⟐ …A1@L412` |
| 09_09.sql | 12 line_start: the 5 repeated `(SELECT count(*)/avg(…)…)` case subqueries — nodes 4/7/11 → 17/30/43/56, 20/33/46/59, 24/37/50/63 | 53 highlight_line/reason |
| 11_11.sql | 1 line_start: union arm 2→25; 1 flow_role target→source | 42 highlight_line/reason |

Node/edge **id sets unchanged** in all 6 files (ids are content-hash
based on structure, not lines) — only line-bearing attributes moved:
`line_start`, `highlight_line`, `reason` (embedded ‖x@L..‖), and the
`flow_role` consequence of the seed-field instance's corrected line.
Filtered (seed) views: only 05's single `reason` string.

**Pin updates:** `test_verification_samples.py` WINDOW-3
(86.sql `results_rollup@14 → rank_within_parent@25`, anchor 15 → 21):
the old pin anchored the rank() inputs' FIRST file appearance
(results_rollup union arm, L15); post-fix they resolve to their own
window occurrences (L21-24, `partition by lochierarchy` at L21) — rule-1
"source field's appearance" now yields 21. Fixture repaired with the
extractor evidence (ground-truth-may-be-wrong rule), not the engine.

---

## D2 field-aware DML admit — snapshot rebaseline (2026-08-12, commit 24a7807)

> **Documented POST-HOC.** The standing rule requires the documented diff
> BEFORE the rebaseline; Team L's rebaseline commit landed without this
> entry (the brief did not restate the rule). The diff below is written
> from the actual commit (24a7807) and the probe evidence, on 2026-08-12,
> to repair the record. The rebaseline itself was verified legitimate:
> full view byte-identical, benchmark gate green, suite 809 passed.

**Verified snapshot diff (2026-08-12, rebaselined):** 00
BDM_ACC_LOAN_INFO_SUP_M.sql, filtered (seed) view only, under the
recorded seed `rollover_loan_info.lending_ref`:

- Nodes 8 → 5, edges 10 → 7. Removed from the filtered view:
  - `l2_tbl_236587aa4c` (`output` ⟐VT @211, TOP1), `l2_tbl_c21b060796`
    (`rrcdm_job_log_exec_par` @211), `l2_tbl_6a8344ffbc`
    (`bdm_acc_loan_info_sup` @160) — the stmt-2 DML write-leg family.
  - Edges `l2e_73632d4f7c7a_dml_out` + `l2e_3b8e8e62b668_dml_out`
    (TABLE_FLOW write legs) and `l2e_b4fc03d22434` (TABLE_FLOW read
    into the stmt-2 output).
- Why: D2 fix (field-aware DML admit, lineage.py `compute_field_flow`).
  stmt 211's `INSERT INTO rrcdm_job_log_exec_par(data_dt, object_domain,
  …, remarks)` writes none of `lending_ref`/`charge_department`, so the
  write leg no longer admits those seeds into the closure; the
  TABLE_FLOW write-leg twin (op='INSERT') uses the same gate. `data_dt`
  IS written by stmt 211, so the `data_dt` seed keeps the rrcdm branch
  (canonical rows 16/17 preserved — benchmark floors unchanged).
- Full view **byte-identical** (204 nodes / 471 edges, all ids, lines,
  reasons, seed selection).
- Probed closures pre/post (sup seeds, served L2): 6/6/7 → 5/5/7
  (charge_department/lending_ref); `data_dt` 7 → 7 (unchanged).
  Walker-level: 7/7/10 → 6/6/10.

---

## PL seed round — snapshot rebaseline (2026-08-12, Team D respawn)

> Documented BEFORE the rebaseline run (standing rule). Probe-verified:
> every content change below was produced by a read-only probe
> (fresh `_run_build` serialization vs the committed snapshot files)
> before `L2_SNAPSHOT_UPDATE=1` was executed.

**Engine causes (two, both this round):**

1. **Script addition (phase-1 deliverable):** the pl seed script
   `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_PL.sql` joined `sql_sample_v1`
   (4 statements: `SET`@18, bare `INSERT`@19 [TOP0],
   `SELECT`@21-251 [TOP1], `INSERT INTO rrcdm_job_log_exec_par`@253-265
   [TOP2]). The harness (`test_l2_snapshot.py::_collect_scripts`) globs
   `sql_sample_v1/*.sql` then `tpcds_qualified/*.sql`, sorted by name,
   capped at `MAX_SCRIPTS=12` — the addition shifts every index and
   pushes `11.sql` off the cap.
2. **J12-17 bare-INSERT trunk fix (engine):** `_simplify_dml_edges`'
   stmt-trunk registration only recognized the entity key `('⟐ output',
   TOPn)`; a bare/VALUES `INSERT` (no SELECT body) names its output VT
   `"⟐ insert"` (extractor), so the PL script's statement-1 write leg had
   no trunk. Fix: the trunk check accepts ANY statement-level output VT
   (entity name `⟐ *`, context exactly `TOP{numeric}`), plus a rule-2
   self-loop guard (a bare INSERT's raw REF-READ `⟐insert→target`
   duplicates the routed write leg — dropped, not retargeted), plus a
   reverse-DML admit in `compute_field_flow` (a statement's own output VT
   joins the closure backward from an admitted DML target only when the
   statement's write leg carries the searched field).

**Verified snapshot inventory (rebaselined 2026-08-12):**

| File | Diff |
|---|---|
| 00_BDM_ACC_LOAN_INFO_PL.sql | **NEW** (no prior file). Seed `('bdm_acc_loan_info','data_dt')`; filtered view 7 nodes / 9 edges (the 9 canonical pl rows: P15/P16/P18/P22 + R1/V1/V2/M1/F1 — incl. the `insert`@19 trunk node and both write legs `hl=19`/`hl=253`, `_dml_out` ids, `flow_kind=write`); full view 302 nodes / 316 edges. Two independent builds byte-identical under PYTHONHASHSEED=0 (determinism probe). |
| 01_BDM_ACC_LOAN_INFO_SUP_M.sql | Renumbered from 00; **content byte-identical** (probe: fresh serialization == committed file — the J12-17 admit never fires for the sup seeds). |
| 02_01.sql … 11_10.sql | Renumbered from 01…10; **content byte-identical** (probe: 10/10 identical — the J12-17 admit never fires for the tpcds seeds). |
| (old) 11_11.sql | Leaves the harness (12-script cap); stale file deleted. |

Node/edge id sets, lines, reasons, seed selection: unchanged everywhere
except the new 00 PL file. The `graph_3_2_23` cache prefix is NOT bumped
(the J12-17 fix only re-routes closure edges for bare/VALUES-INSERT
scripts — served payload shape unchanged).

**Pin updates in the same round:**
- `test_l2_snapshot.py` — unchanged; only the snapshot files renumber.
- `test_dataflow/test_single_script_l1.py` — fixture `single_script_ws`
  zipped the whole `sql_sample_v1` dir (`_make_zip(CASE_DIR)`); with the
  PL script present the workspace is no longer single-script
  (`match_mode='expanded'`, 2 script_ids). Fixture now zips exactly
  `SCRIPT_NAME` — the test's single-script intent is restored.
