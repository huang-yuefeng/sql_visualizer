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
"""
GRAPH_CACHE_PREFIX = "graph_3_2_22"
