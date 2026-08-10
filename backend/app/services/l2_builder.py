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
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.services.graph_service import (
    build_graph_data,
    get_edge_style as _get_edge_style,
    get_category as _get_category,
    EDGE_TYPE_STYLE,
    CATEGORY_MAP,
)
from app.extractor.schema_inference import infer_table_schemas
from app.extractor.lineage import filter_by_field_flow
from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.services.highlight_strategies import get_strategy, FIELD_LIKE_TYPES

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
    full_graph = None
    _table_schemas = None
    if graph_cache_path.exists():
        cached_graph = json.loads(graph_cache_path.read_text())
        # C9 (v3.3.140): graphs below format_version 4 predate the
        # node-carried line_start/line_end the strict table.field walker
        # and its highlights depend on — treat a stale cache as a miss and
        # rebuild (the build path below overwrites the stale cache).
        if cached_graph.get("format_version", 0) >= 4:
            full_graph = cached_graph
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
            if full_graph.get("format_version") != 4:
                _log.warning("L2 cache %s has format_version=%r (expected 4) — stale graph cache",
                             graph_cache_path.name, full_graph.get("format_version"))
            stage_graph(len(full_graph.get('nodes',[])), len(full_graph.get('edges',[])), ws_id=ws_id)
            # Bug 25: load cached table_schemas on cache hit
            if schemas_cache_path.exists():
                _table_schemas = json.loads(schemas_cache_path.read_text())
    if full_graph is None:
        # C-2(b): prefer the analysis cache when present — build the graph
        # from the cached analysis dict (same key contract as
        # folder_index_service: md5(script_name + sql_text)[:12]) instead of
        # re-running the full extraction pipeline.
        analysis_cache_path = cache_dir / f"analysis_{cache_key}.json"
        result = None
        if analysis_cache_path.exists():
            result = json.loads(analysis_cache_path.read_text())
            # C9 (v3.3.140): analysis caches from an older extractor are
            # stale (extraction-semantics changes — phantom subquery dedup,
            # PARTITION vars — must never serve old analysis) — ignore the
            # cache and re-run the full analysis on mismatch.
            if result.get("extractor_version") != EXTRACTOR_VERSION:
                result = None
            else:
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
        # C9 (v3.3.140): format_version 4 = node-carried line_start/line_end.
        full_graph["format_version"] = 4
        # v3.3.145: A1 records statement-level parse diagnostics on the
        # analysis result — ride them on the graph cache so the fast path
        # (and _build_l2_graph's response) serves the same data. Stale
        # caches predating this default to [] (no reconstruction).
        full_graph["parse_errors"] = result.get("parse_errors", [])
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
    """Phase 2 (CW4): apply the strict table.field flow filter, or return the full graph.

    v3.3.140: filter_by_field_flow() (the strict per-instance table.field
    walker in lineage.py) replaces filter_relevant() — the requirement
    changed from table-level flow to exact flow of table.field. Flag
    semantics unchanged: only applied when filtering is requested.
    """
    if relevance_filter:
        return filter_by_field_flow(full_graph, table, field, table_schemas=table_schemas)
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
                   "window", "case", "transform", "literal"):
            # W-iteration (v3.3.147): "literal" included — the searched
            # field's literal VALUE appearance ('$(load_date)' AS
            # data_dt@213 → rrcdm, P17 §8.5) must be a target node so its
            # write-side DML edge survives at field level (value edge).
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
    # C3: (parent_table_id, label, line_start) -> keeper alias compound
    # node — alias identity is (label, line): a different code line = a
    # DIFFERENT alias node; the same (label, line) = the same node.
    alias_nodes_by_key = {}
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

            if is_alias:
                # C3 (v3.3.140): alias node identity is (label, line) — the
                # user directive: a different code line = a DIFFERENT alias
                # node; the same (label, line) = the same node. Alias
                # compound nodes merge/dedup by (physical parent, label,
                # line_start), and the display label carries the line
                # ("p1@29") so duplicate alias instances are distinguishable
                # (review item #4). `table_name` keeps the raw label — all
                # field-parent matching uses table_name, never the display
                # label. Physical-table compound nodes keep the label-keyed
                # merge (R22: one compound node per physical table);
                # ⟐/CTE/output nodes keep their existing keys.
                alias_line = int(nd.get("line_start") or 0)
                display_label = f"{display_label}@{alias_line}" if alias_line > 0 else display_label
                # Resolve the alias's physical parent compound id (its own
                # source_tables are reliable — design doc §4) for the dedup
                # key; when the parent is not classified yet the key's
                # parent slot is None (same-line duplicates still merge).
                alias_parent_id = None
                if src_tables and len(src_tables) == 1:
                    for tn in table_nodes.values():
                        if tn["table_name"] == src_tables[0]:
                            alias_parent_id = tn["id"]
                            break
                    if alias_parent_id is None:
                        resolved_alias = alias_map.get(src_tables[0], src_tables[0])
                        for tn in table_nodes.values():
                            if tn["table_name"] == resolved_alias:
                                alias_parent_id = tn["id"]
                                break
                alias_key = (alias_parent_id, label, alias_line)
                dup_alias = alias_nodes_by_key.get(alias_key)
                if dup_alias is not None:
                    dup_alias["merged_original_ids"].append(nid)
                    continue

            table_nodes[nid] = {
                "id": tbl_id,
                "label": display_label,
                "type": tbl_type,
                "table_name": label,
                "variable_type": vt,
                "original_id": nid,
                # The extraction context rides on the compound node — it is
                # carried extraction-time info (scopes like
                # "CTE{loan_final}/subq1"), surfaced in the L2 response.
                "context": nd.get("context", ""),
            }
            if vt in ("table", "view") and not is_alias:
                table_nodes[nid]["merged_original_ids"] = []
                table_nodes_by_label[label] = table_nodes[nid]
            elif is_alias:
                table_nodes[nid]["merged_original_ids"] = []
                alias_nodes_by_key[alias_key] = table_nodes[nid]
            continue

        # ── Column-like nodes → field children ──
        if vt in ("column", "cte_column") or label.count(".") == 1:
            # Find parent table from source_tables
            # I2 (v3.3.145): the extractor's source_tables are exact per
            # field (set at extraction, incl. the defining alias/derived
            # scope), so attribution is extraction-time only — the same-name
            # first-match is pinned and the B3 scope-context picker plus the
            # label-prefix first-match fallback are gone (dead for
            # attribution). Seed placement is handled by the seed re-parent
            # pass instead.
            parent_table_id = None
            if src_tables and len(src_tables) == 1:
                # Bug 28: Match source table name directly (aliases are now visible nodes)
                # Try exact match first, then try canonical name if this is an alias
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

    # B3/P1: seed copy — an is_target seed field that landed on an ALIAS of
    # the searched table is COPIED onto the searched table's own compound
    # node when that node carries no same-named field yet (copying to the
    # searched table — the field stays on its original alias parent, e.g.
    # p1@29, AND appears on the searched table). Without this the seed
    # shows only on the first same-name alias instance while the base
    # table node stays field-less. When the keeper already owns the label
    # (e.g. the alias field duplicates a bare-FROM read), the copy is
    # skipped to avoid duplication.
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
                # C4 (v3.3.140): COPY — the original fn stays on its alias
                # parent; a proxy with the same label is added under the
                # searched table's compound node.
                proxy = dict(fn)
                proxy["id"] = f"seed_{fn['id']}_{keeper_tbl_id[:8]}"
                proxy["parent"] = keeper_tbl_id
                proxy["field_group"] = "direct"
                field_nodes.append(proxy)
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


def _carry_edge_info(src_nd: dict, tgt_nd: dict, raw_edge: dict) -> dict:
    """Extraction-time info carried on every L2 edge (W5/R25).

    The payload phase (highlight_strategies.single_line) derives
    highlight_line/flow_kind/reason from these fields ONLY — never from
    text search at render (never-patch rule). All lines are the raw
    var-carried line_start values: merged compound nodes' line_start would
    collapse per-appearance anchors (p1.data_dt@43 vs. the data_dt keeper
    @160), so the per-edge raw lines ride the edge through the pipeline.
    """
    src_vt = src_nd.get("variable_type", "")
    tgt_vt = tgt_nd.get("variable_type", "")
    src_tables = src_nd.get("source_tables") or []
    tgt_tables = tgt_nd.get("source_tables") or []
    src_label = src_nd.get("label", "")
    tgt_label = tgt_nd.get("label", "")

    def _owner(tables, label):
        return tables[0] if tables else (label.rsplit(".", 1)[0] if "." in label else "")

    def _canon(tables, label):
        return tables[0] if tables else (label.rsplit(".", 1)[0] if "." in label else label)

    return {
        "_src_line": int(src_nd.get("line_start") or 0),
        "_tgt_line": int(tgt_nd.get("line_start") or 0),
        "_src_label": src_label,
        "_tgt_label": tgt_label,
        "_src_vt": src_vt,
        "_tgt_vt": tgt_vt,
        "_src_tables": list(src_tables),
        "_tgt_tables": list(tgt_tables),
        "_op": raw_edge.get("operation", ""),
        "_src_field_like": (src_vt in FIELD_LIKE_TYPES
                            or (src_nd.get("defined_in") or "").upper() == "PARTITION"),
        "_src_is_vt": src_vt in ("virtual_table", "subquery", "union_branch"),
        "_tgt_is_vt": tgt_vt in ("virtual_table", "subquery", "union_branch"),
        "_src_owner": _owner(src_tables, src_label),
        "_tgt_canon": _canon(tgt_tables, tgt_label),
    }


def _build_edge_list(edges: list, nodes: list, id_map: dict,
                     sql_text: str) -> tuple:
    """Phase 4 (CW4): build the raw edge list with categories and the
    carried extraction-time info the payload derives from (W5/R25).

    Compound edge types are split per-type (Bug 3); each split edge carries
    the same extraction-time info as its parent raw edge. The old
    sql_range enrichment (find_sql_range) is gone with sql_range_finder —
    the payload phase replaces it with per-edge highlight_line.

    Returns (new_edges, node_labels).
    """
    new_edges = []

    # Raw node lookup: id → data (label/line_start/variable_type/…)
    node_info = {}
    for n in nodes:
        nd = n.get("data", n)
        node_info[nd.get("id", "")] = nd

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

        carried = _carry_edge_info(node_info.get(src_orig, {}),
                                   node_info.get(tgt_orig, {}), ed)

        # Bug 3 fix: split compound edge types, each keeps its own carried
        # extraction-time info (the payload derives per-type anchors).
        etypes = [t.strip() for t in edge_type.split(",")] if "," in edge_type else [edge_type]
        for et in etypes:
            if len(etypes) > 1:
                et_style = EDGE_TYPE_STYLE.get(et, EDGE_TYPE_STYLE["SUBSET"])
                et_category = CATEGORY_MAP.get(et, "structure")
                color = et_style["color"]
                line_style = et_style["line"]
                width = et_style["width"]
                desc = et_style["desc"]
            else:
                color = style["color"]
                line_style = style["line"]
                width = style["width"]
                desc = style["desc"]
            new_edges.append({
                "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{et}'.encode()).hexdigest()[:12]}",
                "source": src_new,
                "target": tgt_new,
                "edge_type": et,
                "category": et_category if len(etypes) > 1 else category,
                "color": color,
                "label": et,
                "line_style": line_style,
                "width": width,
                "desc": desc,
                **carried,
            })
    return new_edges, {i: nd.get("label", "") for i, nd in node_info.items()}


def _combine_edges(new_edges: list) -> list:
    """Phase 5 (CW4): same (source,target,edge_type) → combine labels.

    The first occurrence keeps its carried extraction-time info (the
    payload anchor is per-edge, derived later from that carried info)."""
    combined_edges = {}
    for e in new_edges:
        key = (e["source"], e["target"], e["edge_type"])
        if key in combined_edges:
            existing = combined_edges[key]
            # Combine labels
            existing_labels = set(existing.get("label", "").split(", "))
            existing_labels.add(e.get("label", ""))
            existing["label"] = ", ".join(sorted(existing_labels))
        else:
            combined_edges[key] = e
    return list(combined_edges.values())


def _promote_field_edges(new_edges: list, field_nodes: list) -> list:
    """Phase 6 (CW4): promote field-level edges to their parent tables.

    SCHEMA edges (table→field ownership) are KEPT as-is — the user ruling
    (2026-08-10): every L2 edge is a data flow and highlights; the SCHEMA
    edge included ("the scheme edge is also included"). Their source is a
    table node already and their target must stay the field node, so they
    are appended unchanged (no promotion of either endpoint). Each edge
    type keeps its own edge with its own carried extraction-time info (W5).

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
    # Each edge type gets its own edge with its own carried extraction-time
    # info (the W5 payload derives per-type anchors from it).
    # No compound merging — clicking different edge types shows different SQL.
    promoted = []
    for e in new_edges:
        src = e["source"]
        tgt = e["target"]
        etype = e["edge_type"]

        if etype == "SCHEMA":
            # Ownership is implicit in the compound node structure, but the
            # edge itself stays visible (structure kind, §8.7 rule 6).
            promoted.append(e)
            continue
        if src in field_parents and src not in target_field_ids:
            src = field_parents[src]
        if tgt in field_parents and tgt not in target_field_ids:
            tgt = field_parents[tgt]
        if src == tgt:
            continue

        e["source"] = src
        e["target"] = tgt
        promoted.append(e)

    return promoted


def _survive_join_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict, field_nodes: list,
                        node_labels: dict, sql_text: str,
                        strict: bool = False) -> list:
    """Phase 7 (CW4): Bug 45 (Pattern 2) JOIN edge survival pass.

    filter_relevant() removes JOIN edges because JOIN is conditional (both ends
    need a production path). But JOIN edges are semantically valuable — they show
    table relationships even without value flow. After promotion, re-add JOIN
    edges from the full graph that connect tables in the current L2 graph.

    C6 (v3.3.140): gated — when the strict table.field flow filter is active
    (`strict=True`, the flag comes from _build_l2_graph, which knows whether
    filtering was requested), this is a no-op: the strict closure already
    contains the field-relevant JOIN partners (FILTER/JOIN edges are admitted
    by the walker when a seed zone touches either end), and re-adding JOIN
    edges from the full graph would break the strict field-flow closure. The
    survival heuristic (including its name-first-match fallback) runs only on
    the legacy full-graph path (no filtering requested).
    """
    if strict:
        return new_edges
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
        # W5: carry the raw full-graph nodes' extraction-time info so the
        # payload phase anchors this survival edge like any other (raw
        # cache edges carry relationship, not edge_type).
        src_raw = full_node_by_id.get(src_orig, {})
        tgt_raw = full_node_by_id.get(tgt_orig, {})
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
            **_carry_edge_info(src_raw, tgt_raw, fed),
        })
    return new_edges


def _simplify_dml_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict, field_nodes: list = None) -> tuple:
    """Phase 8 (CW4): DML edges route through the ⟐ output (intermediate_table).

    Returns (new_edges, dml_pairs).
    """
    # P17 (§8.5): search-target seed fields keep field-level edges — the
    # value-edge retention below only fires for them.
    target_field_ids = set()
    for fn in field_nodes or []:
        if fn.get("is_target"):
            target_field_ids.add(fn["id"])
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
    # W5: the intermediate MUST be the "⟐ output" node — the first
    # intermediate_table in iteration order can be a subquery VT (⟐ subq1),
    # routing DML targets through the wrong trunk (bogus subq1→target
    # edges). Prefer table_name "⟐ output", fall back to the first
    # intermediate_table for graphs without a query-output node.
    intermediate_id = None
    for tn in table_nodes.values():
        if isinstance(tn, dict) and tn.get("type") != "intermediate_table":
            continue
        if intermediate_id is None:
            intermediate_id = tn.get("id")
        if (tn.get("table_name") or "").startswith("⟐ output"):
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
            # W5: the rewrite keeps the raw edge's carried extraction-time
            # info; _dml_origin marks the write kind (§8.7 row 3) and its
            # anchor = the write line (rule 3 — the DML target's line).
            output_edge["_dml_origin"] = True
            new_dml_edges.append(output_edge)
            # W-iteration (P17, §8.5): a search-target seed field's VALUE
            # edge (its DML write of the searched field's value column —
            # '$(load_date)' AS data_dt@213 → rrcdm) keeps its source→⟐
            # half: the value appearance stays traceable (the write-group
            # ruling: write line 211 / value line 213 / read line 223).
            # _value_edge marks it so the write anchor uses the VALUE's
            # own line (the source's), not the write line.
            if src in target_field_ids and src != intermediate_id:
                value_edge = dict(e)
                value_edge["id"] = f"{e['id']}_value"
                value_edge["target"] = intermediate_id
                value_edge["edge_type"] = "TABLE_FLOW"
                value_edge["label"] = "TABLE_FLOW"
                value_edge["_dml_origin"] = True
                value_edge["_value_edge"] = True
                new_dml_edges.append(value_edge)
        else:
            new_dml_edges.append(e)
    new_edges = new_dml_edges

    # Bug 46 (Pattern 2): Redirect TABLE_FLOW edges that bypass ⟐ output.
    # After DML simplification, any surviving TABLE_FLOW edge into a DML target
    # that doesn't go through intermediate_id should be redirected.
    #
    # W5: when the bypass source already has a TABLE_FLOW edge into the
    # intermediate (its qo/FROM edge), the redirect would collide with it in
    # dedup — and the bypass edge can come FIRST, so its carried info (the
    # m1 source's own line) would corrupt the qo edge's payload (sup seed:
    # the p2→sup m1 redirect would overwrite pair 15's qo carried info,
    # anchoring 199 instead of the output node's creation line). Drop the
    # redundant bypass instead: its flow is already represented by
    # src→intermediate + intermediate→target.
    if intermediate_id:
        to_intermediate = {(e["source"], e["target"]) for e in new_edges
                           if e.get("target") == intermediate_id
                           and e.get("edge_type") == "TABLE_FLOW"}
        kept = []
        for e in new_edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            etype = e.get("edge_type", "")
            if tgt in dml_targets and src != intermediate_id and etype == "TABLE_FLOW":
                if (src, intermediate_id) in to_intermediate:
                    continue  # redundant bypass — src already flows via the intermediate
                e["source"] = intermediate_id
            kept.append(e)
        new_edges = kept

    return new_edges, dml_pairs


def _dedup_edges(new_edges: list) -> list:
    """Phase 9 (CW4): merge edges with the same (source,target,type).

    The first occurrence keeps its carried extraction-time info (the
    payload anchor is derived from it later)."""
    deduped = {}
    for e in new_edges:
        key = (e.get("source"), e.get("target"), e.get("edge_type"))
        if key not in deduped:
            deduped[key] = e
    return list(deduped.values())


def _sync_alias_and_dml_fields(field_nodes: list, table_nodes: dict,
                               alias_map: dict, dml_pairs: set,
                               full_graph: dict, nodes: list) -> None:
    """Phase 10 (CW4): Bug 28 alias field sync + DML phantom fields.

    Per formal definition: when alias exists, its field set MUST mirror
    the original table. And DML edges show fields flowing into targets.
    Mutates field_nodes in place.

    Bug-31 (fixed): the SCHEMA-edge output-table-field pass that used to
    live here is gone. It bulk-copied virtual-table fields from the FULL
    unfiltered graph into the filtered graph with no closure check — every
    field it materialized was a disconnected duplicate: the column's own
    field node already exists in the filtered graph (classification parents
    it by its source_tables), and surviving SCHEMA edges are re-pointed by
    id_map to that node, never to the copy (which therefore had zero
    incident edges). The syncs below only mirror fields already present in
    the filtered graph (survivors) or copies of survivors.
    """
    # Build field index: parent_table_id -> list of field dicts
    field_by_parent = {}
    for fn in field_nodes:
        pid = fn.get("parent", "")
        if pid:
            field_by_parent.setdefault(pid, []).append(fn)

    # ── Sync 1: alias -> canonical (alias invariant) ──
    # C7 (v3.3.140): stmt_idx per original node — the sync exists-checks
    # below are (parent, label, stmt_idx) aware so cross-statement
    # same-name fields collapse/expand symmetrically with the field dedup
    # key (parent, label, stmt_idx) from _classify_compound_nodes.
    orig_stmt = {}
    for n in nodes:
        nd = n.get("data", n)
        orig_stmt[nd.get("id", "")] = nd.get("stmt_idx")
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
                af_stmt = orig_stmt.get(af.get("original_id", ""))
                exists = any(
                    f.get("parent") == canon_tbl_id and f.get("label") == af.get("label")
                    and orig_stmt.get(f.get("original_id", "")) == af_stmt
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
            fn_stmt = orig_stmt.get(fn.get("original_id", ""))
            exists = any(
                f.get("parent") == tgt_tid and f.get("label") == fn.get("label")
                and orig_stmt.get(f.get("original_id", "")) == fn_stmt
                for f in field_nodes
            )
            if not exists:
                proxy = dict(fn)
                proxy["id"] = f"dml_{fn['id']}_{tgt_tid[:8]}"
                proxy["parent"] = tgt_tid
                proxy["field_group"] = "direct"
                field_nodes.append(proxy)


def _closure_walk(e: dict, entries: list, adjacency: dict,
                  reverse: dict) -> list:
    """The §8.8.3 flow string's walk: from the closure entry (the searched
    seed's field) to this edge's target, rendered as {label}@L{line} hops.

    The walk is a shortest BFS over the FINAL L2 edges (directed first,
    undirected as a fallback — the closure walk is connectivity-based);
    the edge's own segment is appended as the final pair. Leaf edges
    (unreachable from any entry) and SCHEMA/SUBSET edges (rules 6/7 —
    structure/bridge display their own endpoints only) return just the
    own segment [(src_label, src_line), (tgt_label, tgt_line)].

    Returns a list of (label, line) hops ending with the edge's own
    segment (the strategy wraps the final pair in ‖…‖).
    """
    def _own_segment():
        return [(e.get("_src_label") or "?", int(e.get("_src_line") or 0)),
                (e.get("_tgt_label") or "?", int(e.get("_tgt_line") or 0))]

    if e.get("edge_type") in ("SCHEMA", "SUBSET") or not entries:
        return _own_segment()

    def _bfs(start_ids, out_adj):
        """Shortest path (list of edges) from any start_id to target."""
        target = e["source"]
        prev = {sid: None for sid in start_ids}
        queue = list(start_ids)
        seen = set(start_ids)
        while queue:
            node = queue.pop(0)
            if node == target:
                break
            for oe in out_adj.get(node, []):
                nxt = oe["target"]
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = (node, oe)
                    queue.append(nxt)
        if target not in seen:
            return None
        path = []
        node = target
        while prev.get(node) is not None:
            parent, oe = prev[node]
            path.append(oe)
            node = parent
        return list(reversed(path))

    path = _bfs(entries, adjacency)
    if path is None:
        # Undirected fallback: traverse reverse edges as forward ones.
        undirected = {}
        for node, oes in list(adjacency.items()) + list(reverse.items()):
            undirected.setdefault(node, []).extend(oes)
        path = _bfs(entries, undirected)
    if not path:
        # No path (leaf), or the edge's source IS the closure entry — the
        # full path from the entry to the edge's target is the edge itself.
        return _own_segment()

    hops = []
    for pe in path:
        hops.append((pe.get("_src_label") or "?", int(pe.get("_src_line") or 0)))
    hops.append((path[-1].get("_tgt_label") or "?", int(path[-1].get("_tgt_line") or 0)))
    # Append the edge's own segment, deduping the shared junction hop.
    if hops and hops[-1] == (e.get("_src_label"), int(e.get("_src_line") or 0)):
        hops = hops[:-1]
    hops.append((e.get("_src_label") or "?", int(e.get("_src_line") or 0)))
    hops.append((e.get("_tgt_label") or "?", int(e.get("_tgt_line") or 0)))
    return hops


def _attach_flow_payload(new_edges: list, field_nodes: list) -> None:
    """W5/R25 — the per-edge payload phase: every final L2 edge carries
    highlight_line / flow_kind / reason (highlight_strategies.single_line),
    computed from the edge's carried extraction-time info + the closure
    walk from the searched seed's field. Never reconstructed at render.

    Mutates new_edges in place (attaches _path_hops, highlight_line,
    flow_kind, reason; the _-prefixed carriers are stripped at assembly).
    """
    if not new_edges:
        return
    strategy = get_strategy("single_line")
    entries = [fn["id"] for fn in field_nodes if fn.get("is_target")]
    adjacency = {}
    reverse = {}
    for e in new_edges:
        adjacency.setdefault(e["source"], []).append(e)
        reverse.setdefault(e["target"], []).append(e)
    for e in new_edges:
        e["_path_hops"] = _closure_walk(e, entries, adjacency, reverse)
        payload = strategy(e)
        e["highlight_line"] = payload["highlight_line"]
        e["flow_kind"] = payload["flow_kind"]
        e["reason"] = payload["reason"]


def _assemble_output(table_nodes: dict, field_nodes: list, new_edges: list,
                     nodes: list, sql_text: str, script_name: str,
                     target_full: str) -> dict:
    """Phase 11 (CW4): assemble the output graph."""
    # ── Assemble output (only table+field compound nodes) ──
    # Issue a: merged_original_ids is builder-internal bookkeeping (the
    # dedup merge record) — it must never leak into the API response.
    def _clean(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "merged_original_ids"}

    all_new_nodes = (
        [{"data": _clean(tn)} for tn in table_nodes.values()] +
        [{"data": _clean(fn)} for fn in field_nodes]
    )

    # W5: strip the builder-internal carriers (_src_line/_path_hops/_dml_
    # origin/…) — the API edge payload is highlight_line/flow_kind/reason.
    new_edges = [{k: v for k, v in e.items() if not k.startswith("_")}
                 for e in new_edges]

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
        "edges": [{"data": {id, source, target, edge_type, category,
                            highlight_line, flow_kind, reason, ...}}],
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

    Edge metadata per formal definition §10 + R25 (W5):
      - edge_type: formal type (REF, JOIN, FILTER, etc.)
      - category: visual group (copy, filter, aggregate, compute, combine, write, structure)
      - highlight_line: exactly ONE script line per edge (§8.3 anchor rules)
      - flow_kind: the §8.7 canonical kind (chain / field flow / read /
        write / filter / structure / bridge)
      - reason: `<kind> — <flow string>` (§8.8.3, ‖…‖-wrapped current edge)
    The old sql_range/sql_ranges and response-level highlights are gone.
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
    # C6 (v3.3.140): under the strict table.field filter the JOIN survival
    # heuristic is a no-op — the strict closure already carries the
    # field-relevant join partners (see _survive_join_edges docstring).
    new_edges = _survive_join_edges(new_edges, full_graph, id_map, table_nodes,
                                    field_nodes, node_labels, sql_text,
                                    strict=relevance_filter)
    new_edges, dml_pairs = _simplify_dml_edges(new_edges, full_graph, id_map,
                                               table_nodes, field_nodes)
    new_edges = _dedup_edges(new_edges)
    # W5/R25: per-edge payload — highlight_line/flow_kind/reason from the
    # carried extraction-time info + the closure walk (never at render).
    _attach_flow_payload(new_edges, field_nodes)

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
