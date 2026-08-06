"""Shared cache-key constants (C3).

Every graph-cache writer (folder_index_service.index_scripts,
dataflow_service.get_level2_graph) and reader (l2_builder) must use
GRAPH_CACHE_PREFIX so a cache-format change bumps ONE constant instead of
drifting string literals. The middle token is the cache CONTRACT version
(graph_3_2_15_<hash>.json): bump it ONLY when the graph JSON format
changes (that mass-invalidates every graph cache), not per release.

Decision 2026-08-06 (v3.3.133 batch): kept at 3_2_15 — nothing in this
batch changes the graph JSON format (the resolution_stats additive keys
live in the ANALYSIS cache, not the graph cache), so a bump would only
mass-invalidate valid caches.
"""
GRAPH_CACHE_PREFIX = "graph_3_2_15"
