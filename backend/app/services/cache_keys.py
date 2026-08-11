"""Shared cache-key constants (C3).

Every graph-cache writer (folder_index_service.index_scripts,
dataflow_service.get_level2_graph) and reader (l2_builder) must use
GRAPH_CACHE_PREFIX so a cache-format change bumps ONE constant instead of
drifting string literals. The middle token is the cache CONTRACT version
(graph_3_2_16_<hash>.json): bump it ONLY when the graph JSON format
changes (that mass-invalidates every graph cache), not per release.

Decision 2026-08-06 (v3.3.133 batch): kept at 3_2_15 — nothing in that
batch changes the graph JSON format (the resolution_stats additive keys
live in the ANALYSIS cache, not the graph cache), so a bump would only
mass-invalidate valid caches.

M14 (2026-08-06 review): bumped to 3_2_16 — an INVALIDATION bump, not a
format bump. index_scripts writes each graph cache DURING the per-script
loop, i.e. BEFORE the S4b cross-script schema-attribution loop, so a
cached graph can serve pre-attribution (stale) analysis. The prefix bump
invalidates every previously cached graph; they rebuild lazily on the
next L2 build and then reflect post-S4b attribution. (Graph JSON format
is unchanged; this is a cache-freshness invalidation, the same
one-constant mechanism.)

C-2 (2026-08-06, C-series round-2): bumped to 3_2_17 — INVALIDATION
bump paired with the index-time deletion (folder_index_service
_invalidate_graph_caches now deletes every graph_3_*_*.json in the
workspace cache dir after the S4b pass, so this constant only names the
files index_scripts itself wrote under the new prefix before the
deletion). The bump still mass-invalidates any graph cache written by
older builds (3_2_15/3_2_16) that the deletion alone cannot know about.

v3.3.140 (2026-08-07): bumped to 3_2_18 — node data now carries
line_start/line_end (format_version 4) and the L2 filter switches to the
strict table.field flow (compute_field_flow). FORMAT bump: the graph JSON
shape changed, so every cached graph is invalid.

v3.3.145 (2026-08-07): bumped to 3_2_19 — INVALIDATION bump paired with
the scope-context parent machinery removal (B3/C5 pickers deleted; L2
attribution is extraction-time source_tables only, I2) and the new
parse_errors key on the graph cache (def-line changes invalidate old
graphs). Graph JSON format_version stays 4.

v3.3.148 (2026-08-10, commit 3590bcc): bumped to 3_2_20 — INVALIDATION
bump for the L2 field-flood fixes (REF/read direction gating in
compute_field_flow, Bug-31 SCHEMA-edge output-field injection removal,
hl=0 def-site fixes; extractor_version 2026-08-10.1). Superseded the
same day by 3_2_21 — the 3_2_20 constant never shipped.

R11-3 (2026-08-10): bumped to 3_2_21 — the L2 response format changed:
per-edge `mech` payload (ref_line/clause/alias/use_lines/sentence) and
compound-node line_start/line_end/defined_in. Old graphs (no mech) would
serve forever without the bump; format_version stays 4 (the walker/
filter inputs are unchanged).

J12-10 stage 3 (2026-08-11): bumped to 3_2_22 — INVALIDATION bump. The
L2 filter and node assembly now derive from the physical model (the
strict walker consumes PhysicalEdges; seed search resolves against
PhysicalField entities; the seed_/sync_/dml_ proxy synthesis is
deleted), and _dep_to_dict now normalizes the graph-data edge form
(source/target → source_id/target_id) so graph-backed models carry
their edges. The graph JSON shape (full_graph) is unchanged, but caches
written before this batch must not feed the new assembly path — mass
invalidate, rebuild lazily. extractor_version is NOT bumped (the
extractor is unchanged).

J12-10 stage 4 (2026-08-11): bumped to 3_2_23 — INVALIDATION bump. The
L2 compound assembly now consumes the physical model: keeper merges and
alias dedup key off the model's alias truth (alias_by_var_id) and
occurrence index instead of the deleted label-keyed keeper merge and
merged_original_ids/_build_id_map bookkeeping; node line anchors come
from the model's occurrences (_carry_node_lines) instead of
_stmt_anchor_lines_from_nodes reconstruction; the DML trunk is chosen
per statement (J12-15 — the write leg of statement n hangs off
statement n's own ⟐ output). Caches written by earlier batches carry
pre-merge compound sets and statement-1-trunked edges — they must not
feed the new assembly path; mass invalidate, rebuild lazily.
extractor_version is NOT bumped (the extractor is unchanged).
[2026-08-11 integration] extractor_version IS bumped to
"2026-08-11.1" for the same release's extractor changes (E5
statement-anchored fallback for line<1 virtual nodes + LATERAL
VIEW / VALUES / UNNEST alias registration) — the analysis caches
written before that code change carry pre-fallback extraction and
would otherwise pass the load-time version check.

[2026-08-12 integration] extractor_version bumped to "2026-08-11.2" —
occurrence-aware statement anchors (E5 round 2, same release) changed
extraction behavior; analysis caches written by 2026-08-11.1 must be
invalidated. The read-side analysis-key contract is now versioned
everywhere: folder_index_service (write), l2_builder + dataflow_service
+ sql_highlight_service (read) all key md5 over
(EXTRACTOR_VERSION, script/rel_path, sql_text).

R26.3 integration (2026-08-11): bumped to 3_2_24 — INVALIDATION bump,
not a format-version change (format_version stays 4). The per-edge
`mech` payload (ref_line/clause/alias/use_lines/sentence) is REMOVED
from the L2 graph JSON shape: R26 deleted the frontend renderer
(EdgeReasonPanel renders kind + anchor + reason only), and this
integration turn retires the dormant backend emitter under the
no-dormant-machinery rule (_build_mechanism/_mech_sentence/
_mech_fallback_clause/_ref_site_vars/_field_part deleted;
_attach_flow_payload drops its node_index parameter). Caches written
by earlier builds carry mech edges and must not serve — mass
invalidate, rebuild lazily. Compound-node line_start/line_end/
defined_in and the R25 per-edge payload (highlight_line/flow_kind/
reason) are unchanged.
"""
GRAPH_CACHE_PREFIX = "graph_3_2_24"
