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

### 1.8 Payload machinery (carried info, closure/downstream walks, mech) — consumers of the model's output, not reconstructions

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
  no (parent,label) dup among `dml_` ids); `TestR11_3MechPayload`
  (91-130) pins compound `line_start/line_end/defined_in` (64..159,
  160..210) and the mech sentence (clause JOIN, ref_line 155, alias p6)
  — these pin the payload contract, which stages 2/3 must preserve
  verbatim (payload is derived from carried extraction info; lines come
  from PhysicalField).
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
   risk is smaller than feared for the gate itself, but the dml_/mech
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
| 1.8 payload machinery | 8 (contract, not reconstruction) | l2_builder.py 627-666, 1186-1250, 1253-1341, 1525-1636, 1387-1412, 1357-1376, 1415-1427, 1477-1522 |
| 1.9 dml_dml_ chaining | 0 (historical — grep-verified) | docs only |
| 2 walker contract | 14 rules (W1-W14) | lineage.py 556-848 + helpers |
| 4.2 test pins | 5 files | test_jaccard_benchmark.py 368-388/425/446, test_mech_payload.py 58-77/91-130, jaccard_canonical.py, test_l1_l2_integration.py, test_walker_gaps_e3.py |
| 4.3 frontend ids | 3 sites | DataFlowGraph.jsx 114-117, pickAutoEdge.js 27/39-44, dataflow_service.py 542-554 |
