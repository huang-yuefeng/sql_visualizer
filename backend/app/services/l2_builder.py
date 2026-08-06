"""L2 Graph Builder — per-script detail graph construction.

Extracted from dataflow_service.py per ARCHITECTURE_REVIEW S3.
Builds L2 detail view: tables + fields + all 16 edge types for a single script.
"""
import json
import hashlib
import logging
from pathlib import Path

_log = logging.getLogger("sql_visualizer.dataflow")

from app.services.workspace_service import get_workspace_dir
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import (
    build_graph_data,
    get_edge_style as _get_edge_style,
    get_category as _get_category,
    EDGE_TYPE_STYLE,
    CATEGORY_MAP,
)
from app.extractor.schema_inference import infer_table_schemas
from app.extractor.lineage import filter_relevant
from app.services.sql_range_finder import partition_edge_ranges
from app.services.sql_range_finder import find_sql_range
from app.services.cache_keys import GRAPH_CACHE_PREFIX

# ── L2 helper functions ──────────────────────────────────────────────

def _target_field_sc(sc: str, target_field: str) -> bool:
    """Check if a source_column string matches the target field name.

    Equivalent of the former dataflow_service.target_field_sc (H2): the
    definition can't be imported from dataflow_service (circular import),
    so it lives here, next to its only caller.

    B2/CW9: exact field-part semantics — only the part after the last dot
    counts, so a target field can never match the alias/table part of a
    qualified column (the old word-boundary regex matched "item" inside
    "item.i_brand", mis-attributing the table name as the field).
    """
    return sc.rsplit(".", 1)[-1] == target_field


def _compute_highlight_ranges(graph_data: dict, highlight_ids: set,
                               sql_text: str) -> list:
    """Compute line ranges to highlight based on node line_map."""
    # D1: recompute the line map from the graph's own node expressions —
    # the stored line_map was computed at index/analysis time and may
    # predate comment-line skipping (stale caches would keep mapping table
    # variables onto header comment lines). The node sql_expressions are
    # verbatim copies of the analysis variables', so the result is
    # identical to a fresh analysis.
    line_map = _recompute_line_map(
        [{"id": nd.get("data", nd).get("id", ""),
          "sql_expression": nd.get("data", nd).get("sql_expression", "")}
         for nd in graph_data.get("nodes", [])], sql_text)
    ranges = []
    for nid in highlight_ids:
        if nid in line_map:
            start, end = line_map[nid]
            # D2: (0,0) is the "no line matched" placeholder — highlighting
            # line 0 would paint the editor's gutter. Never emit it.
            if start < 1:
                continue
            ranges.append([start, end])
    if not ranges:
        return []

    # Merge overlapping/adjacent ranges
    ranges.sort()
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r[0] <= last[1] + 1:
            merged[-1][1] = max(last[1], r[1])
        else:
            merged.append(r)
    return merged


def _recompute_line_map(var_likes: list, sql_text: str) -> dict:
    """D1: recompute line_map from cached variable/node dicts.

    Cached line_maps were written before comment-line skipping existed in
    map_variables_to_lines — their table variables point at header comment
    lines. Recompute here so cached workspaces (analysis + graph caches)
    benefit identically to fresh analyses, without a cache-version bump.
    """
    from app.extractor.sql_line_mapper import map_variables_to_lines
    return map_variables_to_lines(var_likes, sql_text)


# ── L2 phase functions (CW4: split from the _build_l2_graph monolith) ──
# Each phase receives its inputs explicitly and returns its outputs; the
# orchestrator (_build_l2_graph) passes shared state between phases. No
# processing order or edge/node construction semantics changed — the phase
# split is structural only (byte-identical output).

def _load_or_build_graph(ws_id: str, script_name: str, sql_text: str):
    """Phase 1 (CW4): read the graph cache, or run full analysis and write caches.

    Returns (full_graph, table_schemas). On a cache hit, table_schemas is
    loaded from the schemas cache (Bug 25); on a build it is inferred.
    """
    from app.services.logger import stage_graph

    ws_dir = get_workspace_dir(ws_id)
    cache_dir = ws_dir / "cache"
    cache_key = hashlib.md5((script_name + sql_text).encode()).hexdigest()[:12]

    # Try cached graph (v3.2.15 — includes edge filter fix)
    # C3: cache prefix is the shared contract constant (cache_keys.py) — the
    # middle token is the cache CONTRACT version, bump it only on format change.
    graph_cache_path = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
    if graph_cache_path.exists():
        full_graph = json.loads(graph_cache_path.read_text())
        # D1: cached graphs carry a line_map computed before comment-line
        # skipping existed — recompute from the cached node expressions so
        # stale caches behave like fresh analyses.
        full_graph["line_map"] = _recompute_line_map(
            [{"id": n["data"].get("id", ""),
              "sql_expression": n["data"].get("sql_expression", "")}
             for n in full_graph.get("nodes", [])], sql_text)
        # CW7: normalize edge_type on cache read (cache stores "relationship")
        for _e in full_graph.get("edges", []):
            _ed = _e.get("data", _e)
            _ed.setdefault("edge_type", _ed.get("relationship", "REF"))
        # Item 4: cache format versioning — warn on stale caches
        if full_graph.get("format_version") != 3:
            _log.warning("L2 cache %s has format_version=%r (expected 3) — stale graph cache",
                         graph_cache_path.name, full_graph.get("format_version"))
        stage_graph(len(full_graph.get('nodes',[])), len(full_graph.get('edges',[])), ws_id=ws_id)
        # Bug 25: load cached table_schemas on cache hit
        _table_schemas = None
        if schemas_cache_path.exists():
            _table_schemas = json.loads(schemas_cache_path.read_text())
    else:
        # C-2(b): prefer the analysis cache when present — build the graph
        # from the cached analysis dict (same key contract as
        # folder_index_service: md5(script_name + sql_text)[:12]) instead of
        # re-running the full extraction pipeline.
        analysis_cache_path = cache_dir / f"analysis_{cache_key}.json"
        result = None
        if analysis_cache_path.exists():
            result = json.loads(analysis_cache_path.read_text())
            # D1: analysis caches predate comment-line skipping too — the
            # stored line_map is stale; recompute before build_graph_data
            # copies it into the graph.
            result["line_map"] = _recompute_line_map(
                result.get("variables", []), sql_text)
        if result is None:
            result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        full_graph = build_graph_data(result)
        # Cache for future use
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Item 4: cache format version — bump when graph schema changes
        full_graph["format_version"] = 3
        graph_cache_path.write_text(json.dumps(full_graph, default=str))
        # R18: build table_schemas for lineage seed validation
        _table_schemas = infer_table_schemas(
            result.get("variables", []), result.get("dependencies", []))
        # Bug 25: cache table_schemas alongside graph
        schemas_cache_path.write_text(json.dumps(_table_schemas, default=str))
    return full_graph, _table_schemas


def _apply_relevance_filter(full_graph: dict, table: str, field: str,
                            table_schemas: dict | None,
                            relevance_filter: bool = True) -> dict:
    """Phase 2 (CW4): apply the R18 relevance filter, or return the full graph."""
    if relevance_filter:
        return filter_relevant(full_graph, table, field, table_schemas=table_schemas)
    return full_graph


def _compute_target_and_direct_ids(nodes: list, edges: list,
                                   table: str, field: str) -> tuple:
    """Phase 3a (CW4): identify target node ids and compute the upstream/
    downstream BFS sets used for direct/indirect field classification.

    Returns (target_node_ids, direct_ids).
    """
    target_full = f"{table}.{field}"

    # Identify target node IDs (for is_target and direct/indirect)
    target_node_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        name = nd.get("label", "")
        vt = nd.get("variable_type", "")
        if vt in ("column", "cte_column", "expression", "aggregate",
                   "window", "case", "transform"):
            # Match: exact full name, exact field name, or suffix after "."
            matched = False
            if name == target_full or name == field:
                matched = True
            elif "." in name:
                suffix = name.rsplit(".", 1)[-1]
                if suffix == field:
                    matched = True
            if matched:
                target_node_ids.add(nd.get("id"))
            # Also check source_columns (H2: _target_field_sc was previously
            # undefined — NameError the moment source_columns went live)
            src_cols = nd.get("source_columns", [])
            for sc in src_cols:
                if target_full in sc:
                    target_node_ids.add(nd.get("id"))
                elif _target_field_sc(sc, field):
                    target_node_ids.add(nd.get("id"))

    # Compute upstream/downstream sets for direct/indirect classification
    fwd_adj = {}
    rev_adj = {}
    for e in edges:
        ed = e.get("data", e)
        src, tgt = ed.get("source"), ed.get("target")
        fwd_adj.setdefault(src, []).append(tgt)
        rev_adj.setdefault(tgt, []).append(src)

    # BFS from targets
    direct_ids = set(target_node_ids)
    if target_node_ids:
        # Upstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for src in rev_adj.get(cur, []):
                if src not in direct_ids:
                    direct_ids.add(src)
                    queue.append(src)
        # Downstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for tgt in fwd_adj.get(cur, []):
                if tgt not in direct_ids:
                    direct_ids.add(tgt)
                    queue.append(tgt)
    return target_node_ids, direct_ids


def _scope_distance(field_ctx: str, cand_ctx: str):
    """B3/P1: how close a candidate node's scope context is to a field's.

    0 when the contexts are equal; a positive difference when the
    candidate's context is a proper prefix of the field's (the candidate is
    an enclosing scope — the smaller the diff, the closer); None when the
    contexts are unrelated. The field can only belong to a scope that
    CONTAINS it, so deeper-than-field candidates never match.
    """
    if not field_ctx or not cand_ctx:
        return None
    if field_ctx == cand_ctx:
        return 0
    if field_ctx.startswith(cand_ctx + "/") or \
       field_ctx.startswith(cand_ctx + ":"):
        return len(field_ctx) - len(cand_ctx)
    return None


def _pick_scope_candidate(field_ctx: str, candidates: list):
    """B3/P1: among same-named compound-node candidates, pick the one whose
    scope context is nearest the field's context (exact first, then
    enclosing scopes by distance); ties/fallback keep the previous
    first-match behavior."""
    best = None
    best_dist = None
    for cand in candidates:
        d = _scope_distance(field_ctx, cand.get("context", ""))
        if d is None:
            continue
        if best_dist is None or d < best_dist:
            best = cand
            best_dist = d
    if best is not None:
        return best
    return candidates[0] if candidates else None


def _resolve_scope_parent(nd: dict, table_nodes: dict):
    """B3: scope/derived-alias parent resolution for unattributed fields.

    A field that carries no source_tables and no qualifying label prefix
    still belongs to the alias/derived-table scope that DEFINES it — the
    extractor records that scope in the field's `context`
    ("CTE{loan_final}", "TOP0:join:p2", "CTE{rollover_loan_info}/subq1", …).
    Match order (first hit wins):
      1. the SUBQUERY/derived-table compound node whose context is nearest
         the field's context (B3/P1: exact equality, then enclosing scopes
         by distance — the old exact-only rule could never fire for fields
         nested deeper than the subquery node's own context),
      2. the CTE compound node named by a "CTE{name}" scope prefix,
      3. the enclosing scope: walk context segments up ("…/subq1:join:p2" →
         "…/subq1" → "CTE{…}") and repeat 1–2.
    Returns the compound table id, or None when no scope matches.
    """
    ctx = (nd.get("context") or "").strip()
    if not ctx:
        return None
    segments = ctx.split("/")
    for cut in range(len(segments), 0, -1):
        scope_ctx = "/".join(segments[:cut])
        # 1. nearest-context derived-table / subquery match
        candidates = [tn for tn in table_nodes.values()
                      if tn.get("variable_type") == "subquery"]
        best = _pick_scope_candidate(scope_ctx, candidates)
        if best is not None and _scope_distance(scope_ctx, best.get("context", "")) is not None:
            return best["id"]
        # 2. CTE owner — "CTE{name}" scope: the CTE compound node carries
        #    the STATEMENT context, so match by the CTE's table name.
        if scope_ctx.startswith("CTE{"):
            end = scope_ctx.find("}")
            cte_name = scope_ctx[4:end] if end > 4 else ""
            for tid, tn in table_nodes.items():
                if tn.get("variable_type") == "cte" and \
                   tn.get("table_name") == cte_name:
                    return tn["id"]
    return None


def _classify_compound_nodes(nodes: list, full_graph: dict, script_name: str,
                             target_node_ids: set, direct_ids: set,
                             search_table: str | None = None) -> tuple:
    """Phase 3b (CW4): build the compound node structure — table parents and
    field children (plus alias_map read from the graph cache).

    B3/P1: `search_table` names the searched base table (None for phase
    calls that don't carry a search context). is_target seed fields that
    landed on an alias of that table are re-parented onto the table's own
    compound node when it has no same-named field yet — the seed shows on
    the searched table instead of a random alias instance.

    Returns (table_nodes, field_nodes, other_nodes, alias_map).
    """
    # ── Build compound node structure ──
    # Group field-level nodes by their parent table/CTE
    table_nodes = {}       # id -> table compound node
    table_nodes_by_label = {}  # table label -> keeper compound node (issue a)
    fields_by_key = {}     # (parent_id, field label) -> keeper field node (issue a)
    field_nodes = []       # field children
    other_nodes = []       # expression, aggregate, etc. (non-compound)
    seen_ids = set()

    # ── Phase 0: Build alias map before classifying nodes ──
    # Bug 48: Read alias_map from graph cache (pre-built by extractor + folder_index_service).
    # Falls back to node+edge scan if cache doesn't have alias_map (old test data).
    alias_map = full_graph.get("alias_map", {})
    if not alias_map:
        # Fallback: reconstruct from nodes for backwards compatibility
        _log.warning("L2 fallback: no alias_map in cache for %s — reconstructing from nodes (stale cache?)",
                     script_name)
        for n in nodes:
            nd = n.get("data", n)
            vt = nd.get("variable_type", "")
            src_tables = nd.get("source_tables", [])
            label = nd.get("label", "")
            if vt in ("table", "view", "cte", "subquery", "virtual_table",
                       "merge_target", "union_branch") and src_tables and len(src_tables) == 1:
                alias_map[label] = src_tables[0]

    # B3/P1: the cached alias map is label-keyed with last-writer-wins —
    # when one alias label names different physical tables across scopes
    # (p1 aliases bdm_acc_loan_info in the CTE scopes but loan_final at
    # TOP0), the collapsed entry points the alias at the wrong table for
    # the dominant usage. Rebuild first-writer-wins from the FULL graph's
    # table variables and override the cached map.
    node_alias_map = {}
    for n in full_graph.get("nodes", []):
        nd = n.get("data", n)
        vt = nd.get("variable_type", "")
        src_tables = nd.get("source_tables", [])
        label = nd.get("label", "")
        if (vt in ("table", "view", "cte", "subquery", "virtual_table",
                   "merge_target", "union_branch") and src_tables
                and len(src_tables) == 1):
            node_alias_map.setdefault(label, src_tables[0])
    if node_alias_map:
        alias_map = node_alias_map

    # Classify each node
    for n in nodes:
        nd = n.get("data", n)
        nid = nd.get("id", "")
        label = nd.get("label", "")
        vt = nd.get("variable_type", "")
        src_tables = nd.get("source_tables", [])
        defined_in = (nd.get("defined_in") or "").upper()
        is_output_node = nd.get("is_output", False)

        if nid in seen_ids:
            continue
        seen_ids.add(nid)

        # ── Table-like nodes → compound parents ──
        if vt in ("table", "view", "cte", "subquery", "virtual_table",
                   "merge_target", "union_branch"):
            # Bug 28: Keep aliases as visible compound nodes
            # Aliases carry fields and show the data flow explicitly:
            #   canonical_table --ALIAS--> alias (with fields) --DML--> target_table
            is_alias = (label in alias_map and alias_map[label] != label)
            # Issue a: one physical table must appear as exactly ONE L2
            # table node. The extractor emits one TABLE variable per scope,
            # so the same table read/written by N contexts produced N nodes.
            # Non-alias table/view nodes are keyed by their label (the
            # physical table name) instead of the context nid — the first
            # occurrence is the keeper, later contexts merge into it (their
            # nids are recorded on the keeper so _build_id_map re-points
            # every edge to it). Aliases/subqueries/CTEs keep per-context
            # semantics (Bug 28 visible aliases; distinct subquery scopes).
            if vt in ("table", "view") and not is_alias:
                keeper = table_nodes_by_label.get(label)
                if keeper is not None:
                    keeper["merged_original_ids"].append(nid)
                    continue

            tbl_id = f"l2_tbl_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            if is_alias:
                tbl_type = "alias_table"
            elif vt == "cte":
                tbl_type = "cte_table"
            elif is_output_node and vt not in ("table", "view"):
                tbl_type = "output_table"
            elif vt in ("table", "view") and not is_output_node:
                tbl_type = "source_table"
            else:
                tbl_type = "intermediate_table"

            # B5: the DISPLAY label drops the internal "⟐ " marker (never
            # rendered in the UI), while `table_name` keeps the raw name —
            # field-parent matching and the query-output routing pins rely
            # on the exact "⟐ output" sentinel, so only the label is
            # sanitized.
            display_label = label[2:] if label.startswith("⟐ ") else label

            table_nodes[nid] = {
                "id": tbl_id,
                "label": display_label,
                "type": tbl_type,
                "table_name": label,
                "variable_type": vt,
                "original_id": nid,
                # B3: the extraction context is carried onto the compound
                # node so scope-based parent fallback can match subquery
                # nodes by context.
                "context": nd.get("context", ""),
            }
            if vt in ("table", "view") and not is_alias:
                table_nodes[nid]["merged_original_ids"] = []
                table_nodes_by_label[label] = table_nodes[nid]
            continue

        # ── Column-like nodes → field children ──
        if vt in ("column", "cte_column") or label.count(".") == 1:
            # Find parent table from source_tables or name prefix
            parent_table_id = None
            if src_tables and len(src_tables) == 1:
                # Bug 28: Match source table name directly (aliases are now visible nodes)
                # Try exact match first, then try canonical name if this is an alias
                # NOTE: the same-name first-match below is INTENTIONAL —
                # scope-aware picking here would split same-named fields
                # across alias instances (each p2 scope re-owning the JOIN
                # keys), changing field counts the search results pin
                # (lending_ref 12-field result). Seed placement is handled
                # by the B3/P1 seed re-parent pass instead.
                src_name = src_tables[0]
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == src_name or tid == src_tables[0]:
                        parent_table_id = tn["id"]
                        break
                if not parent_table_id:
                    resolved = alias_map.get(src_tables[0], src_tables[0])
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == resolved:
                            parent_table_id = tn["id"]
                            break
            if not parent_table_id and "." in label:
                prefix = label.split(".")[0]
                # Bug 28: Try prefix directly (aliases are now visible nodes)
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == prefix:
                        parent_table_id = tn["id"]
                        break
                if not parent_table_id:
                    resolved_prefix = alias_map.get(prefix, prefix)
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == resolved_prefix:
                            parent_table_id = tn["id"]
                            break
            if not parent_table_id:
                # B3: scope-based fallback — a field with no table
                # attribution and no qualifying prefix still belongs to the
                # alias/derived-table scope that DEFINES it (the CTE or
                # subquery owning its context), falling back to the
                # enclosing scope.
                parent_table_id = _resolve_scope_parent(nd, table_nodes)

            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            # Show orig type as a hint but use "field" for shape
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            # B4: the field label is undecorated (no " ↻" stamp) — the dedup
            # key below uses this exact label, so same-named computed fields
            # under one parent merge instead of twinning.
            field_node = {
                "id": field_id,
                "label": (label.split(".")[-1] if "." in label else label),
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
                # Issue a: same (keeper table, field name) → one field node.
                # Contexts merged into a keeper table all re-parent here, so
                # the same physical field from two contexts would otherwise
                # duplicate; later duplicates' edges re-point to the first
                # via merged_original_ids in _build_id_map.
                # C-9: the key is scoped by the field's STATEMENT index too —
                # same-named vars from DIFFERENT top-level statements are
                # distinct fields (per-statement dedup). stmt_idx is absent
                # for CTE-body scopes → None (graceful fallback: still
                # distinct from statement-scoped fields).
                dedup_key = (parent_table_id, field_node["label"],
                             nd.get("stmt_idx"))
                dup = fields_by_key.get(dedup_key)
                if dup is not None:
                    dup["merged_original_ids"].append(nid)
                    continue
                field_node["merged_original_ids"] = []
                fields_by_key[dedup_key] = field_node
            field_nodes.append(field_node)
            continue

        # ── Expression/aggregate/window/computed nodes → field children ──
        if vt in ("expression", "aggregate", "window", "case", "transform", "literal"):
            # Find parent table from source_tables or fallback to any existing table
            parent_table_id = None
            if src_tables:
                for tid, tn in table_nodes.items():
                    if tn["table_name"] in src_tables or tid in src_tables:
                        parent_table_id = tn["id"]
                        break
            if not parent_table_id:
                # B3: scope-based fallback (same contract as the column
                # branch) before the old attach-to-first-table fallback.
                parent_table_id = _resolve_scope_parent(nd, table_nodes)
            if not parent_table_id and table_nodes:
                # Fallback: attach to first table node
                _log.warning("L2 fallback: %s (%s) has no source table — attached to first table node '%s'",
                             label, vt, list(table_nodes.values())[0]["table_name"])
                parent_table_id = list(table_nodes.values())[0]["id"]

            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            # B4: undecorated computed-field label (the " ↻" twin marker was
            # removed — dedup keys are label-based and must not collide with
            # decoration).
            field_node = {
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label),
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
                # Issue a: same dedup semantics as the column branch — one
                # computed field per (keeper table, label). C-9: scoped by
                # the statement index (per-statement dedup).
                dedup_key = (parent_table_id, field_node["label"],
                             nd.get("stmt_idx"))
                dup = fields_by_key.get(dedup_key)
                if dup is not None:
                    dup["merged_original_ids"].append(nid)
                    continue
                field_node["merged_original_ids"] = []
                fields_by_key[dedup_key] = field_node
            field_nodes.append(field_node)
            continue

        # Fallback: attach unknown node as field child to first available table
        if table_nodes:
            _log.warning("L2 fallback: unknown node '%s' (vt=%s) has no parent — attached to first table node '%s'",
                         label, vt if vt else "unknown", list(table_nodes.values())[0]["table_name"])
            parent_table_id = list(table_nodes.values())[0]["id"]
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            field_nodes.append({
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label) + " ·",
                "type": "field",
                "variable_type": "field",
                "orig_type": (vt if vt else "unknown")[:12],
                "is_target": (nid in target_node_ids),
                "field_group": "indirect",
                "original_id": nid,
                "parent": parent_table_id,
            })

    # B3/P1: seed re-parent — an is_target seed field that landed on an
    # ALIAS of the searched table moves onto the searched table's own
    # compound node when that node carries no same-named field yet (moving,
    # never copying — the alias instance keeps its other fields). Without
    # this the seed shows on the first same-name alias instance while the
    # base table node stays field-less. When the keeper already owns the
    # label (e.g. the alias field duplicates a bare-FROM read), the seed
    # stays on the alias to avoid duplication.
    if search_table:
        keeper_tbl_id = None
        for tn in table_nodes.values():
            if tn.get("table_name") == search_table and tn.get("type") in (
                    "source_table", "intermediate_table", "output_table"):
                keeper_tbl_id = tn["id"]
                break
        if keeper_tbl_id:
            table_by_new_id = {tn["id"]: tn for tn in table_nodes.values()}
            keeper_labels = {f.get("label") for f in field_nodes
                             if f.get("parent") == keeper_tbl_id}
            for fn in field_nodes:
                if not fn.get("is_target"):
                    continue
                parent_tn = table_by_new_id.get(fn.get("parent"))
                if not parent_tn or parent_tn.get("type") != "alias_table":
                    continue
                if alias_map.get(parent_tn.get("table_name", "")) != search_table:
                    continue
                if fn.get("label") in keeper_labels:
                    continue
                fn["parent"] = keeper_tbl_id
                keeper_labels.add(fn.get("label"))

    return table_nodes, field_nodes, other_nodes, alias_map


def _map_search_target_ids(field_nodes: list, table_nodes: dict,
                           target_node_ids: set, direct_ids: set,
                           id_map: dict) -> tuple:
    """Phase 3c (issue a): resolve search-target/direct ids through id_map.

    _compute_target_and_direct_ids yields ORIGINAL graph nids; after the
    table/field dedup those may belong to merged-away contexts. Mapping
    every id through id_map resolves them to the merged keeper (single
    table node / deduped field node), so the highlight never lands on a
    ghost nid. Field nodes are re-marked in place: a target field that
    arrived via a merged-away context still lights up on the keeper.

    Returns (target_mapped, direct_mapped).
    """
    target_mapped = {id_map.get(i, i) for i in target_node_ids}
    direct_mapped = {id_map.get(i, i) for i in direct_ids}
    for fn in field_nodes:
        if fn["id"] in target_mapped:
            fn["is_target"] = True
        if fn["id"] in direct_mapped:
            fn["field_group"] = "direct"
    return target_mapped, direct_mapped


def _build_id_map(table_nodes: dict, field_nodes: list, other_nodes: list) -> dict:
    """Map original IDs to new compound IDs (shared by the edge phases).

    Issue a: every nid merged into a keeper (recorded on the keeper's
    merged_original_ids) maps to the keeper's new id, so _build_edge_list
    re-points all edges that touched a merged context to the single
    surviving table/field node. Self-loops created by the merge are
    dropped downstream in _build_edge_list.
    """
    id_map = {}
    for tn in table_nodes.values():
        id_map[tn["original_id"]] = tn["id"]
        for mnid in tn.get("merged_original_ids", []):
            id_map[mnid] = tn["id"]
    for fn in field_nodes:
        id_map[fn["original_id"]] = fn["id"]
        for mnid in fn.get("merged_original_ids", []):
            id_map[mnid] = fn["id"]
    for on in other_nodes:
        id_map[on["original_id"]] = on["id"]
    return id_map


def _build_edge_list(edges: list, nodes: list, id_map: dict,
                     sql_text: str) -> tuple:
    """Phase 4 (CW4): build the raw edge list with categories and sql_range.

    Range enrichment happens inline here because it is interleaved with
    construction: compound edge types are split per-type (Bug 3) with their
    own range, and the combine pass below selects the shortest range. A
    separate post-pass would reorder that processing.

    Returns (new_edges, node_labels).
    """
    new_edges = []
    lines = sql_text.split("\n") if sql_text else []

    # Build label lookup from nodes for richer edge metadata
    node_labels = {}
    for n in nodes:
        nd = n.get("data", n)
        node_labels[nd.get("id", "")] = nd.get("label", "")

    for e in edges:
        ed = e.get("data", e)
        src_orig = ed.get("source", "")
        tgt_orig = ed.get("target", "")
        rel = ed.get("relationship", "") or ed.get("edge_type", "")
        edge_type = rel if rel else "REF"

        src_new = id_map.get(src_orig, src_orig)
        tgt_new = id_map.get(tgt_orig, tgt_orig)

        if src_new == tgt_new:
            continue  # skip self-loops from ID mapping

        category = _get_category(edge_type)
        style = _get_edge_style(edge_type)

        # Enrich with source/target labels for better SQL matching
        src_label = node_labels.get(src_orig, "")
        tgt_label = node_labels.get(tgt_orig, "")
        enriched = dict(ed)
        enriched["source_label"] = src_label
        enriched["target_label"] = tgt_label
        enriched["edge_type"] = edge_type   # 🔧 Bug 4 fix: edge_type was missing from enriched

        # P1: Try to find a line number for the target label in SQL
        # line_num propagation: only for edge types that benefit from label search
        # Keyword-matching types (FILTER, JOIN, DML, etc.) find lines via KeywordLocator
        # not label search, so skip override to avoid corrupting their line detection.
        keyword_match_types = {'FILTER', 'WHERE', 'HAVING', 'JOIN', 'GROUP_BY', 'ORDER_BY',
                              'DML', 'CTE', 'CREATE', 'ALTER', 'DROP', 'SCHEMA', 'AGGREGATE',
                              'WINDOW', 'TRANSFORM', 'CASE', 'COMPUTED', 'SUBQUERY',
                              'SUBSET', 'ALIAS', 'INDIRECT', 'REF', 'CORRELATED', 'TABLE_FLOW'}
        if tgt_label and lines and edge_type not in keyword_match_types:
            tgt_clean = tgt_label.split('.')[-1].strip().lower()
            if len(tgt_clean) > 2 and tgt_clean not in ('select','from','where','insert','into','values','join','table'):
                for i, line in enumerate(lines):
                    if tgt_clean in line.lower():
                        enriched["line_num"] = i + 1  # 1-based
                        break

        # Bug 3 fix: split compound edge types, each gets own sql_range
        etypes = [t.strip() for t in edge_type.split(",")] if "," in edge_type else [edge_type]
        # For compound types: emit one edge per individual type, each with own range/style
        if len(etypes) > 1:
            for et in etypes:
                enriched_copy = dict(enriched)
                enriched_copy["edge_type"] = et
                # CW8: never propagate a None sql_range — default to whole-script range
                r = (find_sql_range(enriched_copy, sql_text) or
                     find_sql_range(enriched, sql_text) or
                     [1, 1, 1, 1])
                et_style = EDGE_TYPE_STYLE.get(et, EDGE_TYPE_STYLE["SUBSET"])
                et_category = CATEGORY_MAP.get(et, "structure")
                new_edges.append({
                    "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{et}'.encode()).hexdigest()[:12]}",
                    "source": src_new,
                    "target": tgt_new,
                    "edge_type": et,
                    "category": et_category,
                    "color": et_style["color"],
                    "label": et,
                    "line_style": et_style["line"],
                    "width": et_style["width"],
                    "desc": et_style["desc"],
                    "sql_range": r,
                })
        else:
            # CW8: never propagate a None sql_range — default to whole-script range
            sql_range = find_sql_range(enriched, sql_text) or [1, 1, 1, 1]
            new_edges.append({
                "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{edge_type}'.encode()).hexdigest()[:12]}",
                "source": src_new,
                "target": tgt_new,
                "edge_type": edge_type,
                "category": category,
                "color": style["color"],
                "label": edge_type,
                "line_style": style["line"],
                "width": style["width"],
                "desc": style["desc"],
                "sql_range": sql_range,
            })
    return new_edges, node_labels


def _combine_edges(new_edges: list) -> list:
    """Phase 5 (CW4): same (source,target,edge_type) → combine labels/sql_ranges."""
    combined_edges = {}
    for e in new_edges:
        key = (e["source"], e["target"], e["edge_type"])
        if key in combined_edges:
            existing = combined_edges[key]
            # Combine labels
            existing_labels = set(existing.get("label", "").split(", "))
            existing_labels.add(e.get("label", ""))
            existing["label"] = ", ".join(sorted(existing_labels))
            # Keep shortest non-zero sql_range (most specific)
            if e.get("sql_range") and not existing.get("sql_range"):
                existing["sql_range"] = e["sql_range"]
            elif e.get("sql_range") and existing.get("sql_range"):
                er = existing["sql_range"]
                nr = e["sql_range"]
                if len(er) >= 4 and len(nr) >= 4:
                    elen = max(1, er[2] - er[0]) if er[2] > er[0] else 999
                    nlen = max(1, nr[2] - nr[0]) if nr[2] > nr[0] else 999
                    if nlen < elen:
                        existing["sql_range"] = nr
        else:
            combined_edges[key] = e
    return list(combined_edges.values())


def _promote_field_edges(new_edges: list, field_nodes: list) -> list:
    """Phase 6 (CW4): promote field-level edges to their parent tables.

    SCHEMA edges (table→field ownership) are removed since ownership is
    implicit in the compound node structure. Each edge type keeps its own
    edge with its own sql_range (V3.3.65).

    P2: edges incident on a search-target seed field stay at field level —
    promoting them hid the seed's own data flow (e.g. its FILTER edges
    vanished into the parent alias table node).
    """
    field_parents = {}
    target_field_ids = set()  # P2: search-target seed fields keep field-level edges
    for fn in field_nodes:
        pid = fn.get("parent")
        if pid:
            field_parents[fn["id"]] = pid
        if fn.get("is_target"):
            target_field_ids.add(fn["id"])

    # V3.3.65: Promote fields→tables, keep edges separate per type.
    # Each edge type gets its own edge with its own sql_range.
    # No compound merging — clicking different edge types shows different SQL.
    promoted = []
    for e in new_edges:
        src = e["source"]
        tgt = e["target"]
        etype = e["edge_type"]

        if etype == "SCHEMA":
            continue
        if src in field_parents and src not in target_field_ids:
            src = field_parents[src]
        if tgt in field_parents and tgt not in target_field_ids:
            tgt = field_parents[tgt]
        if src == tgt:
            continue

        e["source"] = src
        e["target"] = tgt
        if e.get("sql_range"):
            e["sql_ranges"] = {etype: e["sql_range"]}
        promoted.append(e)

    return promoted


def _survive_join_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict, field_nodes: list,
                        node_labels: dict, sql_text: str) -> list:
    """Phase 7 (CW4): Bug 45 (Pattern 2) JOIN edge survival pass.

    filter_relevant() removes JOIN edges because JOIN is conditional (both ends
    need a production path). But JOIN edges are semantically valuable — they show
    table relationships even without value flow. After promotion, re-add JOIN
    edges from the full graph that connect tables in the current L2 graph.
    """
    # Build node_by_id for JOIN survival pass
    node_by_id = {}
    for tn_id, tn in table_nodes.items():
        node_by_id[tn_id] = tn
    for fn in field_nodes:
        node_by_id[fn["id"]] = fn

    # Bug 45: Build full_node_by_id for fallback resolution when id_map misses
    # (field-level endpoints filtered out). Resolve to parent table via label prefix
    # or source_tables.
    full_node_by_id = {}
    for fn in full_graph.get("nodes", []):
        fnd = fn.get("data", fn)
        full_node_by_id[fnd.get("id", "")] = fnd

    seen_join_keys = set()
    for e in new_edges:
        if e.get("edge_type") == "JOIN":
            seen_join_keys.add((e["source"], e["target"]))
    full_edges = full_graph.get("edges", [])
    for fe in full_edges:
        fed = fe.get("data", fe)
        fetype = fed.get("edge_type", "") or fed.get("relationship", "")
        if fetype != "JOIN":
            continue
        src_orig = fed.get("source", "")
        tgt_orig = fed.get("target", "")
        src_new = id_map.get(src_orig)
        tgt_new = id_map.get(tgt_orig)

        # Bug 45: When field-level endpoint was filtered out, resolve to parent table
        if not src_new and src_orig in full_node_by_id:
            src_node = full_node_by_id[src_orig]
            src_label = src_node.get("label", "")
            src_tables = src_node.get("source_tables", [])
            src_parent = (src_tables[0] if src_tables else
                          src_label.rsplit(".", 1)[0] if "." in src_label else "")
            for tn in table_nodes.values():
                if tn.get("table_name") == src_parent:
                    src_new = tn["id"]
                    break
        if not tgt_new and tgt_orig in full_node_by_id:
            tgt_node = full_node_by_id[tgt_orig]
            tgt_label = tgt_node.get("label", "")
            tgt_tables = tgt_node.get("source_tables", [])
            tgt_parent = (tgt_tables[0] if tgt_tables else
                          tgt_label.rsplit(".", 1)[0] if "." in tgt_label else "")
            for tn in table_nodes.values():
                if tn.get("table_name") == tgt_parent:
                    tgt_new = tn["id"]
                    break

        if not src_new or not tgt_new or src_new == tgt_new:
            continue
        key = (src_new, tgt_new)
        if key in seen_join_keys:
            continue
        seen_join_keys.add(key)
        src_obj = node_by_id.get(src_new, {})
        tgt_obj = node_by_id.get(tgt_new, {})
        if src_obj.get("type") in ("field",) or tgt_obj.get("type") in ("field",):
            continue
        # CW8: enriched edge with labels so find_sql_range can locate the
        # JOIN clause (raw cache edges carry relationship, not edge_type,
        # and no source_label/target_label).
        fed_enriched = dict(fed)
        fed_enriched.setdefault("edge_type", fetype)
        fed_enriched.setdefault(
            "source_label",
            node_labels.get(src_orig, "") or
            full_node_by_id.get(src_orig, {}).get("label", ""))
        fed_enriched.setdefault(
            "target_label",
            node_labels.get(tgt_orig, "") or
            full_node_by_id.get(tgt_orig, {}).get("label", ""))
        new_edges.append({
            "id": f"l2e_join_survive_{src_new}_{tgt_new}",
            "source": src_new,
            "target": tgt_new,
            "edge_type": "JOIN",
            "category": "filter",
            "color": "#E91E63",
            "label": "JOIN",
            "line_style": "dashed",
            "width": 2,
            "desc": "JOIN key (table relationship)",
            # CW8: never propagate a None sql_range — compute it, else whole-script default
            "sql_range": find_sql_range(fed_enriched, sql_text) or [1, 1, 1, 1],
        })
    return new_edges


def _simplify_dml_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict) -> tuple:
    """Phase 8 (CW4): DML edges route through the ⟐ output (intermediate_table).

    Returns (new_edges, dml_pairs).
    """
    # ── Simplification 1: DML edges route through ⟐ output (intermediate_table) ──
    # Instead of creating synthetic qo_ nodes, use the existing intermediate_table
    # ("⟐ output") node that already represents the SELECT result set.
    # This eliminates 4 regression-prone patches: qo_ creation, dedup, repointing, self-loop removal.
    #
    # Before: raw_orders ──[DML]──> stg_orders
    # After:  raw_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_orders
    #
    # All intermediate operations (TRANSFORM, AGGREGATE, FILTER, JOIN, etc.) connect to ⟐ output,
    # not directly to the DML target. The output node is the trunk of the data flow.
    intermediate_id = None
    for tn in table_nodes.values():
        if isinstance(tn, dict) and tn.get("type") == "intermediate_table":
            intermediate_id = tn.get("id")
            break

    # Collect DML target tables and DML source→target pairs
    # Bug 46: Populate from full_graph.edges (unfiltered), not new_edges.
    # filter_relevant() removes DML edges whose source columns are not in
    # the lineage set, making dml_targets empty. The redirect pass at line
    # ~635 needs dml_targets to route TABLE_FLOW through intermediate_id.
    dml_targets = set()
    dml_sources = set()
    dml_pairs = set()  # (source, target) pairs from DML edges
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

    new_dml_edges = []
    for e in new_edges:
        etype = e.get("edge_type", "")
        src = e.get("source", "")
        tgt = e.get("target", "")
        # 1. Suppress TABLE_FLOW bypass edges (replaced by source→⟐→target chain)
        if (src in dml_sources and tgt in dml_targets
            and etype == "TABLE_FLOW"
            and src != intermediate_id and tgt != intermediate_id):
            continue
        # 2. Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
        if (src in dml_sources and tgt in dml_targets
            and "DML" not in etype.upper()
            and etype != "TABLE_FLOW"
            and src != intermediate_id and tgt != intermediate_id
            and intermediate_id):
            e["target"] = intermediate_id
            new_dml_edges.append(e)
            continue
        # 3. Replace DML edges with ⟐ output → target (TABLE_FLOW)
        if "DML" in etype.upper() and intermediate_id:
            output_edge = dict(e)
            output_edge["id"] = f"{e['id']}_dml_out"
            output_edge["source"] = intermediate_id
            output_edge["edge_type"] = "TABLE_FLOW"
            output_edge["label"] = "TABLE_FLOW"
            if output_edge.get("sql_ranges"):
                tf_range = output_edge["sql_ranges"].get("TABLE_FLOW", output_edge.get("sql_range"))
                output_edge["sql_ranges"] = {"TABLE_FLOW": tf_range}
                output_edge["sql_range"] = tf_range
            new_dml_edges.append(output_edge)
        else:
            new_dml_edges.append(e)
    new_edges = new_dml_edges

    # Bug 46 (Pattern 2): Redirect TABLE_FLOW edges that bypass ⟐ output.
    # After DML simplification, any surviving TABLE_FLOW edge into a DML target
    # that doesn't go through intermediate_id should be redirected.
    if intermediate_id:
        for e in new_edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            etype = e.get("edge_type", "")
            if tgt in dml_targets and src != intermediate_id and etype == "TABLE_FLOW":
                e["source"] = intermediate_id

    return new_edges, dml_pairs


def _dedup_edges(new_edges: list) -> list:
    """Phase 9 (CW4): merge edges with the same (source,target,type)."""
    deduped = {}
    for e in new_edges:
        key = (e.get("source"), e.get("target"), e.get("edge_type"))
        if key in deduped:
            ex = deduped[key]
            er = ex.get("sql_range"); nr = e.get("sql_range")
            if nr and (not er or (len(er)>=4 and len(nr)>=4 and (nr[2]-nr[0])<(er[2]-er[0]))):
                ex["sql_range"] = nr
            sr = ex.get("sql_ranges", {})
            sr.update(e.get("sql_ranges", {}))
            ex["sql_ranges"] = sr
        else:
            deduped[key] = e
    return list(deduped.values())


def _sync_alias_and_dml_fields(field_nodes: list, table_nodes: dict,
                               alias_map: dict, dml_pairs: set,
                               full_graph: dict, nodes: list) -> None:
    """Phase 10 (CW4): Bug 28 alias field sync + DML phantom fields + Bug 31.

    Per formal definition: when alias exists, its field set MUST mirror
    the original table. And DML edges show fields flowing into targets.
    Mutates field_nodes in place.
    """
    # Build field index: parent_table_id -> list of field dicts
    field_by_parent = {}
    for fn in field_nodes:
        pid = fn.get("parent", "")
        if pid:
            field_by_parent.setdefault(pid, []).append(fn)

    # ── Bug 31: Output table fields from SCHEMA edges ──
    # Per formal definition: output table fields = {columns with SCHEMA edge
    # FROM this output table}. Read from full_graph (before lineage filtering)
    # because filter_relevant() may remove SCHEMA edges if the output table
    # is not in the lineage set (TABLE_FLOW not followed by BFS).
    existing_vt_ids = {tn["original_id"] for tn in table_nodes.values()
                       if tn.get("variable_type") == "virtual_table"}
    full_edges = full_graph.get("edges", [])
    for e in full_edges:
        ed = e.get("data", e)
        etype = ed.get("edge_type") or ed.get("relationship", "")
        if etype == "SCHEMA" and ed.get("source") in existing_vt_ids:
            # Find the column node that this SCHEMA edge points to
            for n in nodes:
                nd = n.get("data", n)
                if nd.get("id") == ed.get("target"):
                    label = nd.get("label", "")
                    # Extract field name from label (e.g., "c.customer_id" → "customer_id")
                    fn = label.rsplit(".", 1)[-1] if "." in label else label
                    tn_name = nd.get("table_name", "") or label.rsplit(".", 1)[0] if "." in label else ""
                    # Get the output table's compound node id
                    vt_id = table_nodes[ed["source"]]["id"] if ed["source"] in table_nodes else None
                    if vt_id and fn:
                        already = any(
                            f.get("parent") == vt_id and f.get("label") == fn
                            for f in field_nodes
                        )
                        if not already:
                            field_nodes.append({
                                "id": f"fld_{hashlib.md5((vt_id + fn).encode()).hexdigest()[:10]}",
                                "label": fn,
                                "type": "field",
                                "variable_type": "field",
                                "field_group": "direct",
                                "table_name": tn_name,
                                "field_name": fn,
                                "parent": vt_id,
                                "original_id": nd.get("id"),
                            })
                    break

    # Sync 1: alias -> canonical (alias invariant)
    full_orig_src = {}
    for n in full_graph.get("nodes", []):
        nd = n.get("data", n)
        _st = nd.get("source_tables", [])
        full_orig_src[nd.get("id", "")] = _st[0] if _st else ""
    new_to_orig = {tn["id"]: tid for tid, tn in table_nodes.items()}
    for label, canonical in alias_map.items():
        if label == canonical:
            continue
        # Find alias table node(s) and the canonical node
        alias_tbl_ids = []
        canon_tbl_id = None
        for tid, tn in table_nodes.items():
            if tn["table_name"] == label:
                alias_tbl_ids.append(tn["id"])
            if tn["table_name"] == canonical:
                canon_tbl_id = tn["id"]
        if not alias_tbl_ids or not canon_tbl_id:
            continue
        # B3/P1: the same alias label has one compound node per scope — the
        # old loop kept only the LAST instance (usually a field-less one) and
        # the sync silently died. Pick the first instance that actually
        # holds fields AND whose own source table is the canonical — the
        # label can name different physical tables per scope (p1 aliases
        # bdm_acc_loan_info in the CTE scopes but loan_final at TOP0; the
        # derived-table p2 reads ods_hub_lsacmsp columns while p2@TOP0
        # aliases bdm_acc_loan_info_sup), and syncing a foreign scope's
        # fields onto the canonical would be wrong. When no instance
        # qualifies, keep the previous behavior (skip).
        alias_tbl_id = None
        for aid in alias_tbl_ids:
            if aid not in field_by_parent:
                continue
            if full_orig_src.get(new_to_orig.get(aid, "")) == canonical:
                alias_tbl_id = aid
                break
        if alias_tbl_id is None:
            continue
        if alias_tbl_id in field_by_parent:
            # Copy alias fields to canonical table
            for af in field_by_parent[alias_tbl_id]:
                exists = any(
                    f.get("parent") == canon_tbl_id and f.get("label") == af.get("label")
                    for f in field_nodes
                )
                if not exists:
                    proxy = dict(af)
                    proxy["id"] = f"sync_{af['id']}_canon"
                    proxy["parent"] = canon_tbl_id
                    proxy["field_group"] = "direct"
                    field_nodes.append(proxy)

    # Sync 2: DML phantom fields (field -> DML target table)
    # Bug 29: After field promotion, dml_pairs may contain table IDs (not field IDs).
    # Handle both: table ID → sync all fields under that table; field ID → direct match.
    for (src_fid, tgt_tid) in dml_pairs:
        # Find all field nodes whose parent is src_fid (table-level DML after promotion)
        src_fields = [fn for fn in field_nodes if fn.get("parent") == src_fid]
        if not src_fields:
            # src_fid might be a field ID (pre-promotion path) — try direct match
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


def _assemble_output(table_nodes: dict, field_nodes: list, new_edges: list,
                     nodes: list, sql_text: str, script_name: str,
                     target_full: str) -> dict:
    """Phase 11 (CW4): assemble the output graph and run the range partition pass."""
    # ── Assemble output (only table+field compound nodes) ──
    # Issue a: merged_original_ids is builder-internal bookkeeping (the
    # dedup merge record) — it must never leak into the API response.
    def _clean(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "merged_original_ids"}

    all_new_nodes = (
        [{"data": _clean(tn)} for tn in table_nodes.values()] +
        [{"data": _clean(fn)} for fn in field_nodes]
    )

    # Partition pass: reduce edge range overlap so edges form a near-partition
    if new_edges:
        edge_dicts = [e for e in new_edges]  # new_edges are plain dicts
        partition_edge_ranges(edge_dicts, len(sql_text.split('\n')))
        new_edges = edge_dicts

    total_edges = len(new_edges)
    return {
        "nodes": all_new_nodes,
        "edges": [{"data": e} for e in new_edges],
        "script_name": script_name,
        "total_nodes": len(nodes),
        "filtered_nodes": len(all_new_nodes),
        "total_edges": total_edges,
        "target": target_full,
    }


def _build_l2_graph(ws_id: str, script_name: str, sql_text: str,
                    table: str, field: str,
                    relevance_filter: bool = True) -> dict:
    """Build Level 2 per-script graph with compound nodes and edge metadata.

    Returns:
      {
        "nodes": [{"data": {id, label, type, parent?, field_group?, is_target?, ...}}],
        "edges": [{"data": {id, source, target, edge_type, category, sql_range?, ...}}],
        "script_name": str,
        "total_nodes": int,           # nodes before filtering
        "filtered_nodes": int,        # nodes after filtering
        "target": "table.field",
        "search_matched": bool,       # False only when a filter was requested
                                      # and no target/direct seed matched
      }

    Issue a: one physical table → exactly one table node (dedup by table
    label); all contexts' edges re-point to the keeper. Field nodes of
    merged contexts re-parent to the keeper and dedup by (parent, name).

    Node types in L2:
      - source_table, intermediate_table, output_table (compound parents)
      - field (child of table, with parent=data.parent)
      - cte_table (CTE definition, L2 only)
      - expression, aggregate, window, transform, case, literal (existing V2 types)

    Edge metadata per formal definition §10:
      - edge_type: formal type (REF, JOIN, FILTER, etc.)
      - category: visual group (copy, filter, aggregate, compute, combine, write, structure)
      - sql_range: [start_line, start_col, end_line, end_col] for SQL highlighting
    """
    # CW4: orchestration only — every stage is a named phase function above,
    # with shared state passed explicitly between phases.
    full_graph, table_schemas = _load_or_build_graph(ws_id, script_name, sql_text)
    graph_data = _apply_relevance_filter(full_graph, table, field, table_schemas,
                                         relevance_filter)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    target_node_ids, direct_ids = _compute_target_and_direct_ids(nodes, edges, table, field)
    table_nodes, field_nodes, other_nodes, alias_map = _classify_compound_nodes(
        nodes, full_graph, script_name, target_node_ids, direct_ids, table)
    id_map = _build_id_map(table_nodes, field_nodes, other_nodes)
    # Issue a: resolve search-target/direct ids to the merged keepers so
    # highlighting lands on the single table node / deduped field node,
    # never on a merged-away ghost nid.
    target_mapped, direct_mapped = _map_search_target_ids(
        field_nodes, table_nodes, target_node_ids, direct_ids, id_map)

    new_edges, node_labels = _build_edge_list(edges, nodes, id_map, sql_text)
    new_edges = _combine_edges(new_edges)
    new_edges = _promote_field_edges(new_edges, field_nodes)
    new_edges = _survive_join_edges(new_edges, full_graph, id_map, table_nodes,
                                    field_nodes, node_labels, sql_text)
    new_edges, dml_pairs = _simplify_dml_edges(new_edges, full_graph, id_map,
                                               table_nodes)
    new_edges = _dedup_edges(new_edges)

    _sync_alias_and_dml_fields(field_nodes, table_nodes, alias_map, dml_pairs,
                               full_graph, nodes)
    result = _assemble_output(table_nodes, field_nodes, new_edges, nodes, sql_text,
                              script_name, f"{table}.{field}")
    # Issue a: search_matched contract (frontend + BE2). False ONLY when a
    # relevance filter was requested and no target/direct seed matched —
    # the exact "the searched field is not in this script" signal. True
    # when the field matched, or when no filter was requested.
    result["search_matched"] = (not relevance_filter) or bool(target_mapped or direct_mapped)
    return result
