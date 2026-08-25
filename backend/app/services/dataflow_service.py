"""Dataflow service — cross-script field tracing, L1/L2 graph building, relevance filter."""
import asyncio
import json
import os
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field

from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.services.workspace_service import get_workspace_dir
from app.extractor.lineage import (
    compute_field_lineage,
    filter_graph_by_lineage,
    filter_by_field_flow,
    # Legacy re-export: sql_highlight_service.py imports filter_relevant
    # from here — the legacy consumers keep calling it unchanged (v3.3.140
    # only switches the two L2 call sites to filter_by_field_flow).
    filter_relevant,
)
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.extractor.physical_model import build_physical_model


from app.services.l1_builder import _build_l1_graph
from app.services.l2_builder import _build_l2_graph, build_line_merged_edges

@dataclass
class SearchView:
    view_id: str
    table: str
    field: str
    script_ids: list[str]
    l1_graph_cache: dict = field(default_factory=dict)
    created_at: str = ""


async def create_search(ws_id: str, table: str, field: str,
                        table_index: dict, field_index: dict,
                        lineage_mode: bool = True,
                        direction="upstream") -> dict:
    """Find scripts touching table AND field, build L1 graph.

    1. Find scripts from field_index that contain this field
    2. Find scripts from table_index that contain this table
    3. Intersection = scripts touching BOTH
    4. Build L1 graph via analyze_multiple_scripts()
    5. Store view in views.json (async — the write runs off the event loop, L9)

    R29 (2026-08-12): `direction` ("upstream" default / "downstream")
    selects the field flow direction — threaded into _build_l1_graph (the
    L1 directional projection), persisted on the view, and honored in the
    no-flow message. Field queries keep the EXACT script set (no
    transitive table-closure expansion — that is a table-only search
    behavior) and skip the R18 lineage filter (the directional L1 already
    IS the field flow).
    """
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request
    api_request('POST', f'/workspace/{ws_id}/search', 200, f'table={table} field={field}', ws_id=ws_id)
    cache_dir = ws_dir / "cache"

    # Find scripts touching this table AND this field
    field_scripts = set(field_index.get(field, {}).get("scripts", []))
    table_scripts = set(table_index.get(table, {}).get("scripts", []))
    matching_scripts = sorted(field_scripts & table_scripts)

    match_mode = "exact"
    if not field_scripts:
        # BE2 (issues b+c): a field that no script in the index queries has
        # NO data flow. Do NOT fall back to padding in all scripts that
        # reference the table — that made L1 include scripts that are not in
        # the searched field's data flow at all.
        return await _no_matches_result(
            ws_id, table, field,
            f"Field {table}.{field} is not queried by any script in this "
            "workspace — no data flow exists for it",
            direction=direction)
    if not matching_scripts:
        # The field exists in the index (referenced under other tables) but
        # no script references it together with the searched table — the
        # table.field pair has no data flow either.
        return await _no_matches_result(
            ws_id, table, field,
            f"No script in this workspace references {table}.{field} — "
            "no data flow exists for it",
            direction=direction)
    else:
        # Full transitive closure: any script in the table-dependency connected
        # component can affect or be affected by the target variable.
        # Include ALL scripts reachable via table lineage, not just those
        # that directly reference the field.
        # R29 (2026-08-12): field queries SKIP the expansion — the
        # directional field flow is exact, and the table-closure would drag
        # in scripts that only touch the table (no field flow in either
        # direction); the expansion stays a table-only-search behavior.
        if not field:
            visited_scripts = set(matching_scripts)
            frontier_tables = set()

            # Collect all tables touched by seed scripts
            for s in matching_scripts:
                for tname, tdata in table_index.items():
                    if s in tdata.get("scripts", []):
                        frontier_tables.add(tname)

            # BFS: tables → scripts → more tables → more scripts ...
            changed = True
            max_iterations = 10
            while changed and max_iterations > 0:
                changed = False
                max_iterations -= 1
                new_tables = set()
                for tname in frontier_tables:
                    for s in table_index.get(tname, {}).get("scripts", []):
                        if s not in visited_scripts:
                            visited_scripts.add(s)
                            changed = True
                            # This script touches other tables — add them to frontier
                            for t2, td2 in table_index.items():
                                if s in td2.get("scripts", []):
                                    new_tables.add(t2)
                frontier_tables = new_tables

            if len(visited_scripts) > len(matching_scripts):
                matching_scripts = sorted(visited_scripts)
                match_mode = "expanded"

    # Build L1 graph — R29: the directional projection (downstream keeps
    # the byte-identical legacy shape; upstream renders the writing flow).
    l1_graph = _build_l1_graph(ws_id, matching_scripts, table, field,
                               direction=direction)

    # R29: a field query whose directional closure is EMPTY is a no-flow
    # search, not a no-matches search — the field IS in the scripts (read
    # but never written for upstream; written but never read for
    # downstream) — respond with the no_flow state, mirroring the
    # no_matches handling (the L1 builder stamps flow_empty on an empty
    # directional flow).
    if field and l1_graph.get("flow_empty"):
        if direction == "upstream":
            _msg = f"No writing flow for {table}.{field}"
        else:
            _msg = f"No reading flow for {table}.{field}"
        # CR3: keep the real matching_scripts on the no-flow view so a
        # later GET /level1|/level2 with the opposite direction can
        # re-project — the field IS in these scripts, only this direction's
        # closure is empty.
        return await _no_flow_result(ws_id, table, field, _msg,
                                     script_ids=matching_scripts,
                                     direction=direction)

    # R18: Apply lineage filter to L1 graph when lineage_mode — table-only
    # searches only; field queries skip it (the directional L1 already IS
    # the field flow).
    if lineage_mode and not field:
        l1_graph = _filter_l1_by_lineage(l1_graph, table, field)

    # Create view
    view_id = uuid.uuid4().hex[:12]
    view = SearchView(
        view_id=view_id,
        table=table,
        field=field,
        script_ids=matching_scripts,
        l1_graph_cache=l1_graph,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # Persist to views.json (M8: match_mode saved so the search-mode banner
    # survives a reload — the no_matches path persists it too, in dataflow.py)
    # R29: direction is persisted so the level1 GET restores the same
    # directional projection on reload.
    await _persist_search_view(ws_id, {
        "view_id": view.view_id,
        "type": "search",
        "table": view.table,
        "field": view.field,
        "script_ids": view.script_ids,
        "script_count": len(view.script_ids),
        "l1_graph_cache": view.l1_graph_cache,
        "match_mode": match_mode,
        "direction": direction,
        "children": [],
        "created_at": view.created_at,
    })

    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": matching_scripts,
        "l1_graph": l1_graph,
        "match_mode": match_mode,
        "direction": direction,
    }


async def _no_matches_result(ws_id: str, table: str, field: str, message: str,
                             direction="upstream") -> dict:
    """BE2: no-matches search result (field absent from index / no pair flow).

    Returns the banner-compatible shape the frontend renders for
    ``match_mode === "no_matches"`` (match_mode + message + empty L1 graph),
    identical to the F1 filter-active no_matches path in routers/dataflow.py.
    The view is persisted (R3) so a reload restores the banner.

    R29 (2026-08-12): direction rides the persisted view + response (the
    level1 GET fallback reads it back on reload).
    """
    view_id = uuid.uuid4().hex[:12]
    l1_graph = {"nodes": [], "edges": [], "target": "table.field"}
    await _persist_search_view(ws_id, {
        "view_id": view_id,
        "type": "search",
        "table": table,
        "field": field,
        "script_ids": [],
        "script_count": 0,
        "l1_graph_cache": l1_graph,
        "match_mode": "no_matches",
        "message": message,
        "direction": direction,
        "children": [],
    })
    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": [],
        "l1_graph": l1_graph,
        "match_mode": "no_matches",
        "message": message,
        "direction": direction,
    }


async def _no_flow_result(ws_id: str, table: str, field: str, message: str,
                          script_ids: list[str] | None = None,
                          direction="upstream") -> dict:
    """R29: no-flow search result (the field IS in the scripts, but the
    directional flow is EMPTY — read but never written for upstream,
    written but never read for downstream).

    Mirror of _no_matches_result: banner-compatible shape for
    ``match_mode === "no_flow"`` (match_mode + message + empty L1 graph),
    view persisted so a reload restores the banner.

    CR3: `script_ids` carries the real matching_scripts — the directional
    graph stays empty, but the persisted script set lets a later
    GET /level1|/level2 with the opposite direction re-project (the
    views that most need a direction switch).
    """
    script_ids = script_ids or []
    view_id = uuid.uuid4().hex[:12]
    l1_graph = {"nodes": [], "edges": [], "target": "table.field"}
    await _persist_search_view(ws_id, {
        "view_id": view_id,
        "type": "search",
        "table": table,
        "field": field,
        "script_ids": script_ids,
        "script_count": len(script_ids),
        "l1_graph_cache": l1_graph,
        "match_mode": "no_flow",
        "message": message,
        "direction": direction,
        "children": [],
    })
    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": script_ids,
        "l1_graph": l1_graph,
        "match_mode": "no_flow",
        "message": message,
        "direction": direction,
    }



def _filter_l1_by_lineage(l1_graph: dict, target_table: str, target_field: str) -> dict:
    """R18: Filter L1 graph to show only field nodes in lineage of target field.

    Applies R18.1 empty table cleanup: after filtering, removes table nodes
    with 0 field children except the terminal marker (direct writes_to target
    of a script that has >=1 lineage field).
    """
    nodes = l1_graph.get("nodes", [])
    edges = l1_graph.get("edges", [])

    # Identify target field nodes in L1: field nodes whose field_name matches
    # and parent table matches target_table
    lineage_field_ids = set()
    lineage_table_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("type") == "field":
            tname = nd.get("table_name", "")
            fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
            if tname == target_table and fname == target_field:
                lineage_field_ids.add(nd.get("id"))
                lineage_table_ids.add(nd.get("parent", ""))

    # Bug 27: Use compute_field_lineage pairs instead of name matching
    # Per formal definition: same-name fields from different tables are NOT
    # equivalent. Use the lineage_field_pairs computed by _build_l1_graph
    # via compute_field_lineage (same engine as L2).
    lineage_pairs = l1_graph.get("lineage_field_pairs", set())
    # Convert to dict for O(1) lookup: key = (table_name, field_name)
    if isinstance(lineage_pairs, list):
        lineage_pairs = set(tuple(p) for p in lineage_pairs)
    filtered_nodes = []
    for n in nodes:
        nd = n.get("data", n)
        ntype = nd.get("type", "")
        if ntype == "field":
            tname = nd.get("table_name", "")
            fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
            # Accept if (table_name, field_name) is in the lineage set
            if (tname, fname) in lineage_pairs:
                filtered_nodes.append(n)
                lineage_field_ids.add(nd.get("id"))
                lineage_table_ids.add(nd.get("parent", ""))
        else:
            # table, script_node — always keep
            filtered_nodes.append(n)

    # ── R18.1: Empty table cleanup ──────────────────────────────────────
    # After field filtering, some table nodes may have 0 field children.
    # Rule: keep a table with 0 fields iff it is the direct writes_to target
    # of a script that has >=1 lineage field (terminal marker).
    # Remove all other empty tables and their edges.

    # Collect field parent IDs first (tables with >=1 field after filtering)
    field_parent_ids = set()
    for n in filtered_nodes:
        nd = n.get("data", n)
        if nd.get("type") == "field" and nd.get("parent"):
            field_parent_ids.add(nd.get("parent"))

    # Bug 24c: derive scripts_with_fields from edges (field parent = table ID,
    # not script ID). Find scripts connected to field-bearing tables.
    scripts_with_fields = set()
    for e in edges:
        ed = e.get("data", e)
        if ed.get("edge_type") in ("reads_from", "writes_to"):
            src, tgt = ed.get("source"), ed.get("target")
            if src in field_parent_ids:
                scripts_with_fields.add(tgt)
            if tgt in field_parent_ids:
                scripts_with_fields.add(src)

    # Identify terminal tables: direct writes_to target of scripts with fields
    terminal_table_ids = set()
    for e in edges:
        ed = e.get("data", e)
        if ed.get("edge_type") == "writes_to" and ed.get("source") in scripts_with_fields:
            terminal_table_ids.add(ed.get("target"))

    # Build set of table node types
    table_types = {
        "source_table", "intermediate_table", "output_table",
        "query_output", "cte_table",
    }

    # Keep: scripts, tables with fields, terminal marker tables
    filtered_nodes = [n for n in filtered_nodes
        if n.get("data", n).get("type") == "script_node"
        or n.get("data", n).get("id") in field_parent_ids
        or n.get("data", n).get("id") in terminal_table_ids
        or n.get("data", n).get("type") not in table_types]

    # Rebuild keep_ids and re-filter edges
    # R18.1: Terminal marker outgoing edges are KEPT (requirement changed)
    keep_ids = {n.get("data", n).get("id") for n in filtered_nodes}
    filtered_edges = [e for e in edges
                      if (e.get("data", e).get("source") in keep_ids and
                          e.get("data", e).get("target") in keep_ids)]
    
    # R18.1: Remove disconnected scripts (no remaining table edges after cleanup)
    script_ids = {n.get("data", n).get("id") for n in filtered_nodes
                  if n.get("data", n).get("type") == "script_node"}
    scripts_with_edges = set()
    for e in filtered_edges:
        ed = e.get("data", e)
        scripts_with_edges.add(ed.get("source"))
        scripts_with_edges.add(ed.get("target"))
    disconnected_scripts = script_ids - scripts_with_edges
    # R24: never prune the only script of a single-script workspace — the
    # search already established it IS in the searched field's flow
    # (match_mode exact/expanded), and an empty L1 leaves nothing to
    # double-click into L2. The disconnected-script rule targets
    # flow-irrelevant scripts inside multi-script pipelines only.
    if len(script_ids) > 1 and disconnected_scripts:
        filtered_nodes = [n for n in filtered_nodes
                          if n.get("data", n).get("id") not in disconnected_scripts]
        keep_ids = {n.get("data", n).get("id") for n in filtered_nodes}
        filtered_edges = [e for e in filtered_edges
                          if e.get("data", e).get("source") in keep_ids
                          and e.get("data", e).get("target") in keep_ids]

    return {**l1_graph, "nodes": filtered_nodes, "edges": filtered_edges}
def _atomic_write_text(path: Path, text: str) -> None:
    """Write text via a temp file + os.replace (E4, item 8).

    A direct write_text can leave a truncated/partial cache file behind on
    crash or disk-full, which a later unguarded json.loads turns into a
    500. The temp-name suffix makes concurrent writers safe (each writes
    its own temp file); os.replace is atomic on the same filesystem.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def get_level2_graph(ws_id: str, view_id: str, script_name: str,
                     table: str, field: str, filter_relevant_nodes: bool = True,
                     direction="upstream") -> dict:
    """Build L2 graph for a script. Loads pre-computed graph cache,
    applies relevance filter, returns {graph, parse_errors}.

    W5/R25: the per-edge payload (highlight_line / flow_kind / reason) is
    built into the graph at L2 build time (l2_builder._attach_flow_payload)
    — the old response-level `highlights` and the `highlight_strategy`
    query param are gone (R25 item 3).

    R29 (2026-08-12): `direction` ("upstream" default / "downstream")
    threads into the strict flow filter AND the L2 builder — downstream
    is byte-identical legacy behavior; upstream filters to the field's
    WRITING flow, and the not-in-flow message names the writing side."""
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request, stage_graph

    cache_dir = ws_dir / "cache"

    # E4 (item 1, H1-hardening): `script_name` is user-controlled and was
    # joined raw into the scripts path (`scripts_dir / script_name`) —
    # `script=/app/VERSION` (absolute) read the container's VERSION file
    # and `../../<other_ws>/scripts/x.sql` read another workspace's scripts.
    # Resolve against the workspace scripts dir via the shared containment
    # resolver (filter_service.resolve_script) and never read a directory.
    from app.services.filter_service import resolve_script
    sp = resolve_script(ws_id, script_name)
    if sp is None or not sp.is_file():
        return {"error": f"Script '{script_name}' not found"}

    sql_text = sp.read_text(encoding="utf-8", errors="replace")
    # C-3 (review): analysis cache key discriminates the extractor engine —
    # identical to folder_index_service's write-side key (md5 over
    # (EXTRACTOR_VERSION, script_name, sql_text)) or freshly indexed
    # workspaces are never found here. A stale cache written by an older
    # engine can never match this key — exact-key consumers miss and
    # rebuild lazily.
    cache_key = hashlib.md5(
        (EXTRACTOR_VERSION + "|" + script_name + sql_text)
        .encode()).hexdigest()[:12]

    # Bug 25: Initialize table_schemas before cache check
    table_schemas = None
    # J12-10 stage 3: the physical model the strict walker consumes —
    # built on every path below (hit: analysis cache preferred, else the
    # cached graph; miss: the same analysis the graph was built from).
    physical_model = None
    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"

    # Try pre-computed graph cache (C3: shared GRAPH_CACHE_PREFIX — writers
    # and readers must agree on the versioned name)
    graph_cache_path = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
    graph_data = None
    if graph_cache_path.exists():
        try:
            _cached_graph = json.loads(graph_cache_path.read_text())
        except Exception:
            _cached_graph = None  # E4 (item 8): corrupt/partial cache — miss
        # E4 (item 5): the graph cache carries the extractor version stamped
        # at write time; a hit from an older extractor is stale (extraction-
        # semantics changes must never serve old graphs) — mirror the
        # analysis-cache check in the miss path below.
        if (_cached_graph is not None
                and _cached_graph.get("extractor_version") == EXTRACTOR_VERSION):
            graph_data = _cached_graph
            stage_graph(len(graph_data.get('nodes',[])), len(graph_data.get('edges',[])), ws_id=ws_id)
            # Bug 25: Load cached table_schemas on cache hit. E4: the
            # schemas cache is versioned implicitly — it is written in the
            # same miss as the graph cache and only read under a graph hit,
            # so the graph stamp gates both files. A corrupt/missing schemas
            # cache is a miss (rebuilds the pair together).
            if schemas_cache_path.exists():
                try:
                    table_schemas = json.loads(schemas_cache_path.read_text())
                except Exception:
                    table_schemas = None
            if table_schemas is None:
                graph_data = None
            else:
                # J12-10 stage 3: prefer the analysis cache (the alias_of
                # extraction truth) for the physical model — mirror of
                # l2_builder._load_or_build_graph; a bare graph-cache hit
                # falls back to the cached graph data below.
                analysis_cache_path = cache_dir / f"analysis_{cache_key}.json"
                if analysis_cache_path.exists():
                    try:
                        cached_analysis = json.loads(analysis_cache_path.read_text())
                    except Exception:
                        cached_analysis = None
                    if (cached_analysis is not None
                            and cached_analysis.get("extractor_version")
                            == EXTRACTOR_VERSION):
                        physical_model = build_physical_model(
                            cached_analysis, script_name=script_name)
                # Bare graph-cache hit (never indexed / analysis cache
                # absent or stale): rebuild the model from the cached
                # graph data — mirror of l2_builder._load_or_build_graph.
                if physical_model is None:
                    physical_model = build_physical_model(
                        graph_data, script_name=script_name)
    if graph_data is None:
        # Build on-demand
        from app.extractor.adapter import run_full_analysis
        from app.services.graph_service import build_graph_data
        # C-2(b): prefer the analysis cache when present — build the graph
        # from the cached analysis dict (same key contract as
        # folder_index_service: md5(EXTRACTOR_VERSION + "|" + script_name
        # + sql_text)[:12]) instead of re-running the full extraction
        # pipeline.
        analysis_cache_path = cache_dir / f"analysis_{cache_key}.json"
        result = None
        if analysis_cache_path.exists():
            try:
                result = json.loads(analysis_cache_path.read_text())
            except Exception:
                result = None  # E4 (item 8): corrupt analysis cache — re-run
            # C10 (v3.3.140): analysis caches from an older extractor are
            # stale (extraction-semantics changes — phantom subquery dedup,
            # PARTITION vars — must never serve old analysis) — ignore the
            # cache and re-run the full analysis on mismatch.
            if result is not None and result.get("extractor_version") != EXTRACTOR_VERSION:
                result = None
        if result is None:
            result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        graph_data = build_graph_data(result)
        # R18: build table_schemas for lineage seed validation
        from app.extractor.schema_inference import infer_table_schemas
        table_schemas = infer_table_schemas(
            result.get("variables", []), result.get("dependencies", []))
        # Bug 25: Cache table_schemas alongside graph
        cache_dir.mkdir(parents=True, exist_ok=True)
        # E4 (item 8): atomic writes — a torn cache file must never be
        # readable as a "hit" (reads treat corrupt files as a miss anyway).
        _atomic_write_text(schemas_cache_path, json.dumps(table_schemas, default=str))
        # C-10: also write the versioned GRAPH cache so the next request
        # hits the fast path (previously the miss path only wrote schemas,
        # so every on-demand build re-ran the full analysis).
        # C10 (v3.3.140): format_version 4 = node-carried line_start/line_end.
        graph_data["format_version"] = 4
        # v3.3.145 (case-3): A1 records statement-level parse diagnostics
        # on the analysis result — stamp them onto the graph cache so the
        # fast path serves the same data (stale caches default to [] below).
        graph_data["parse_errors"] = result.get("parse_errors", [])
        # E4 (item 5): stamp the extractor version into the graph cache so
        # reads from an older extractor are detected and rebuilt. The
        # schemas cache is versioned implicitly through this stamp (written
        # in the same miss, read only under a graph hit); it keeps its raw
        # dict shape because l2_builder._load_or_build_graph (not owned by
        # E4) reads it unversioned.
        graph_data["extractor_version"] = EXTRACTOR_VERSION
        _atomic_write_text(graph_cache_path, json.dumps(graph_data, default=str))
        # J12-10 stage 3: the model is built once, from the analysis the
        # graph was built from (the extraction truth — alias_of rides it).
        physical_model = build_physical_model(
            result, script_name=script_name)

    # v3.3.145 (case-3): parse_errors ride the graph cache (stamped at
    # write time); stale caches predating this default to [] — no
    # reconstruction.
    parse_errors = graph_data.get("parse_errors", [])

    # Apply relevance filter (if requested)
    # v3.3.140: the strict table.field flow filter (filter_by_field_flow)
    # replaces filter_relevant — the requirement changed from table-level
    # flow to exact flow of table.field. Flag semantics unchanged.
    if filter_relevant_nodes:
        filtered = filter_by_field_flow(graph_data, table, field,
                                        table_schemas=table_schemas,
                                        physical_model=physical_model,
                                        direction=direction)
    else:
        filtered = graph_data

    # Build the transformed L2 graph with compound nodes
    l2_result = _build_l2_graph(ws_id, script_name, sql_text, table, field,
                                filter_relevant_nodes, direction)

    # BE2 (issues b+c): the script is not in the searched field's data flow.
    # `search_matched` is emitted by _build_l2_graph (BE1 contract): False
    # ONLY when filtering was requested and no target/direct seed matched.
    # Absent → treat as matched. In the not-in-flow case the relevance filter
    # would leave a misleading table-only skeleton — instead rebuild the FULL
    # graph so the panel stays useful, and tell the frontend via
    # search_matched:false + message.
    search_matched = l2_result.get("search_matched", True)
    not_in_flow = bool(table and field) and filter_relevant_nodes and search_matched is False
    if not_in_flow:
        l2_result = _build_l2_graph(ws_id, script_name, sql_text, table, field,
                                    False, direction)
        filtered = graph_data  # fallback counts reflect the full graph

    if not l2_result.get("error"):
        # _build_l2_graph returns {nodes, edges, ...} directly, extract graph
        l2_graph_data = {
            "nodes": l2_result.get("nodes", []),
            "edges": l2_result.get("edges", []),
        }
        response = {
            "script_name": script_name,
            "sql_text": sql_text,
            "graph": l2_graph_data,
            "parse_errors": parse_errors,
            "total_nodes": l2_result.get("total_nodes", len(graph_data.get("nodes", []))),
            "filtered_nodes": l2_result.get("filtered_nodes", len(filtered.get("nodes", []))),
            "total_edges": len(l2_result.get("edges", [])),
        }
        if not_in_flow:
            response["search_matched"] = False
            if direction == "upstream":
                # R29: upstream searched the WRITING flow — the field is
                # not written in this script.
                response["message"] = (
                    f"Script {script_name} is not in the writing flow of "
                    f"{table}.{field} — the field is not written in this "
                    "script. Showing the full script graph."
                )
            else:
                response["message"] = (
                    f"Script {script_name} is not in the data flow of "
                    f"{table}.{field} — the field is not queried in this script. "
                    "Showing the full script graph."
                )
        else:
            # New L2 flow toggle (View 1 / View 2): when a search seed was
            # provided AND the relevance filter ran AND the seed matched
            # (not_in_flow is False), `graph` above IS the field-flow closure
            # (filter_by_field_flow output — payload unchanged). Expose the
            # closure ids + the FULL graph so the frontend can toggle
            # flow-only ↔ full client-side (cytoscape .hide()/.show(), never
            # a re-fetch, never a re-layout).
            #
            # The full build is byte-identical to an explicit
            # filter_relevant_nodes=False request (same _build_l2_graph path
            # the old "Show All" button fetched). Closure-only elements are
            # defensively merged in: some closure edges exist ONLY in the
            # closure build (e.g. the field's DML write legs — the full
            # build's combine/dedup collapses them onto another field's
            # same-key edge), and View 2 must still render them.
            flow_matched = bool(table and field) and filter_relevant_nodes
            if flow_matched:
                flow_nodes = l2_result.get("nodes", [])
                flow_edges = l2_result.get("edges", [])
                response["flow_node_ids"] = [
                    n["data"]["id"] for n in flow_nodes
                    if n.get("data", {}).get("id")
                ]
                response["flow_edge_ids"] = [
                    e["data"]["id"] for e in flow_edges
                    if e.get("data", {}).get("id")
                ]
                # ISSUE-6 / R32: the line-merged flow view — one SQL line ≈
                # one edge. Same node set (passed through unchanged); only
                # the edges are rewritten by the merge pass. The existing
                # flow_node_ids / flow_edge_ids / full_graph payload is
                # untouched — this is a NEW pass, never a mutation.
                response["flow_only_merged"] = {
                    "nodes": flow_nodes,
                    "edges": build_line_merged_edges(flow_edges, flow_nodes),
                }
                full_l2 = _build_l2_graph(ws_id, script_name, sql_text,
                                          table, field, False, direction)
                if not full_l2.get("error"):
                    full_nodes = full_l2.get("nodes", [])
                    full_edges = full_l2.get("edges", [])
                    full_node_ids = {
                        n["data"]["id"] for n in full_nodes
                        if n.get("data", {}).get("id")
                    }
                    full_edge_ids = {
                        e["data"]["id"] for e in full_edges
                        if e.get("data", {}).get("id")
                    }
                    # ISSUE-6 / R32: the full view's merged nodes/edges are
                    # the SAME combined lists as full_graph below — the
                    # merge pass runs over them without mutating them.
                    full_merged_nodes = full_nodes + [
                        n for n in flow_nodes
                        if n.get("data", {}).get("id") not in full_node_ids
                    ]
                    full_merged_edges = full_edges + [
                        e for e in flow_edges
                        if e.get("data", {}).get("id") not in full_edge_ids
                    ]
                    response["full_graph"] = {
                        "nodes": full_merged_nodes,
                        "edges": full_merged_edges,
                    }
                    response["full_merged"] = {
                        "nodes": full_merged_nodes,
                        "edges": build_line_merged_edges(
                            full_merged_edges, full_merged_nodes),
                    }
        return response

    # Fallback: return raw graph with edge count
    return {
        "script_name": script_name,
        "sql_text": sql_text,
        "graph": filtered,
        "parse_errors": parse_errors,
        "total_nodes": len(graph_data.get("nodes", [])),
        "filtered_nodes": len(filtered.get("nodes", [])),
        "total_edges": len(filtered.get("edges", [])),
    }



def _load_views(ws_id: str) -> list:
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request

    views_path = ws_dir / "cache" / "views.json"
    if views_path.exists():
        try:
            return json.loads(views_path.read_text())
        except Exception:
            return []  # E4 (item 8): corrupt views.json — start fresh, never 500
    return []


def _save_views(ws_id: str, views: list):
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request

    views_path = ws_dir / "cache" / "views.json"
    _atomic_write_text(views_path, json.dumps(views, indent=2, ensure_ascii=False))


# E4 (item 6): serialize views.json load→append→save. Without this, two
# concurrent searches could both load the same views list, both append,
# and one view would be silently lost (read-modify-write race). A
# threading.Lock held across the WHOLE sequence inside ONE worker thread
# (asyncio.to_thread) — no blocking on the event loop, and the lock is
# never held across an await.
_views_lock = threading.Lock()


def _persist_view_locked(ws_id: str, view: dict) -> None:
    with _views_lock:
        views = _load_views(ws_id)
        views.append(view)
        _save_views(ws_id, views)


async def _persist_search_view(ws_id: str, view: dict):
    """Append a search view to views.json.

    Shared by create_search and the F1 no_matches path (dataflow.py), so
    every search — even an empty one — survives reload (R3).
    L9: the write embeds the full L1 graph cache — run it in a worker thread
    so large workspaces don't stall the event loop. E4: load→append→save
    runs under _views_lock inside the same worker thread (lost-update
    race fix; the persisted content shape — full L1 graph in the view — is
    a design decision, unchanged).
    """
    view.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    await asyncio.to_thread(_persist_view_locked, ws_id, view)


def list_views(ws_id: str) -> list:
    return _load_views(ws_id)


def delete_view(ws_id: str, view_id: str) -> bool:
    views = _load_views(ws_id)
    # Remove view or child entry
    new_views = []
    found = False
    for v in views:
        if v["view_id"] == view_id:
            found = True
            continue
        # Check children
        children = v.get("children", [])
        v["children"] = [c for c in children if c["view_id"] != view_id]
        if len(v["children"]) < len(children):
            found = True
        new_views.append(v)
    if found:
        _save_views(ws_id, new_views)
    return found
