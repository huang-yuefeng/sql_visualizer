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
"""
GRAPH_CACHE_PREFIX = "graph_3_2_17"
