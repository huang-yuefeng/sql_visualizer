"""Dataflow router — search, views, L1/L2 graphs, SQL highlight."""
import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from app.routers.workspace import _session_ctx
from app.services.workspace_service import get_workspace, get_workspace_dir
from app.services.logger import _push, _ts
from app.services.folder_index_service import resolve_name_ci, scripts_for_name_ci
from app.services.dataflow_service import (
    _load_views, _save_views, _persist_search_view,
    create_search, get_level2_graph,
    list_views, delete_view,
)
from app.services.heavy_gate import gate
from app.services.sql_highlight_service import get_highlight_ranges

router = APIRouter(tags=["dataflow"])


# ── R29 direction allowlist (CR2/CR7) — K4 ruling 4 (2026-08-28) ──
# R38 already removed the frontend Upstream/Downstream switch and declared
# "downstream" the only direction, but the API kept defaulting to — and
# honoring — "upstream", so a direct API caller (or any client that still
# sends the legacy value) got a DIFFERENT graph than the UI for the same
# search. The boundary now agrees with the product: an ABSENT value and a
# legacy "upstream" both resolve to "downstream"; only a value outside the
# allowlist ("UPSTREAM", a typo, an empty string) is a 400 (never a silent
# fall-through). The upstream walker machinery below the router is
# untouched (API-unreachable now; its retirement is a separate work item).
_VALID_DIRECTIONS = {"upstream", "downstream"}


def _normalize_direction(value) -> str:
    """Validate + normalize the R29 direction at the router boundary.

    None (omitted) → "downstream"; a legacy "downstream" passes through
    unchanged; a legacy "upstream" is COERCED to "downstream" (the R38
    legacy treatment — accepted, never honored); anything outside the
    allowlist → 400. A NON-STRING body value (a dict/list — FastAPI happily
    hands a JSON object/array through) → 400 too, not a TypeError-500: a
    membership test against a set raises on an unhashable operand, so the
    isinstance check has to come first. Callers always get a canonical
    "downstream".
    """
    if value is None:
        return "downstream"
    if not isinstance(value, str) or value not in _VALID_DIRECTIONS:
        raise HTTPException(
            status_code=400,
            detail=("Invalid direction %r — must be 'downstream' "
                    "(legacy 'upstream' accepted)") % (value,))
    return "downstream"


def _run_coro_in_thread(coro_fn, *args, **kwargs):
    """Run an async function to completion on a worker thread's own event loop.

    R31 (#273): create_search is `async def` but its body is CPU-bound (L1
    graph building). Running it via asyncio.to_thread keeps the single
    worker's event loop free of the blocking graph build.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_fn(*args, **kwargs))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        asyncio.set_event_loop(None)


def _load_index(ws_id: str) -> tuple[dict, dict, bool, int, int]:
    """Load table_index and field_index from cache. Prefers filtered index.

    Returns (ti, fi, filtered_active, scope_tables, scope_fields) —
    filtered_active tells callers a filter is in force (filtered_index.json
    exists), which lets them distinguish "filter active but empty" from
    "never indexed". The scope counts are computed HERE once (L8) so
    _search_diagnostic_values doesn't re-read the file (TOCTOU + double IO).
    """
    cache_dir = get_workspace_dir(ws_id) / "cache"
    # Prefer filtered index if available
    filtered_path = cache_dir / "filtered_index.json"
    if filtered_path.exists():
        filtered = json.loads(filtered_path.read_text())
        ti = filtered.get("table_index", {})
        fi = filtered.get("field_index", {})
        return ti, fi, True, len(ti), len(fi)
    ti_path = cache_dir / "table_index.json"
    fi_path = cache_dir / "field_index.json"
    ti = json.loads(ti_path.read_text()) if ti_path.exists() else {}
    fi = json.loads(fi_path.read_text()) if fi_path.exists() else {}
    return ti, fi, False, len(ti), len(fi)



def _emit_search_diagnostic(ws_id, table, field, filter_active, scope_tables, scope_fields,
                            table_in_index, field_in_index, table_scripts, field_scripts,
                            match_scripts, suggestion):
    """R17: Emit a compact ASCII diagnostic block to the LogPanel after each search."""
    W = 80
    lines = []
    lines.append("┌─ SEARCH DIAGNOSTIC " + "─" * (W - 20) + "┐")
    lines.append(("│ Query: table=%s  field=%s" % (table, field)).ljust(W - 1) + "│")
    lines.append(("│ Filter active: %s  (%s tables, %s fields in scope)" % (
        "YES" if filter_active else "NO", scope_tables, scope_fields)).ljust(W - 1) + "│")
    lines.append(("│ Table in index: %s  (%s scripts)" % (
        "YES" if table_in_index else "NO", table_scripts)).ljust(W - 1) + "│")
    lines.append(("│ Field in index: %s  (%s scripts)" % (
        "YES" if field_in_index else "NO", field_scripts)).ljust(W - 1) + "│")
    lines.append(("│ Matching scripts: %s" % match_scripts).ljust(W - 1) + "│")
    if suggestion != "OK":
        lines.append(("│ ⚠ %s" % suggestion).ljust(W - 1) + "│")
    lines.append("└" + "─" * (W - 2) + "┘")
    for line in lines:
        _push(ws_id, "profile", line)


def _search_diagnostic_values(table, field, ti, fi, result, filter_active,
                              scope_tables, scope_fields,
                              base_table_in_index=True, base_field_in_index=True):
    """Compute the R17 diagnostic inputs (shared by the normal + no_matches paths).

    The no_matches path (F1/R3) reuses the same inputs so the emitted block
    is identical in shape to a regular search's. Index and scope values come
    from _load_index (L8) — no re-read of filtered_index.json here.

    BE2 (issue c): the suggestion must distinguish a table/field that is
    absent from the BASE index (no script queries it — no data flow exists,
    and the filter CSVs are NOT to blame) from one that IS in the base index
    but excluded by the active filter (legitimate CSV hint).

    F5 (audit #383, R2.10): presence and script counts resolve
    case-insensitively (`resolve_name_ci`), mirroring create_search — an
    index keyed by each script's own casing (`dm_flag2` / `DM_FLAG2`) must
    not make the diagnostic claim "not queried by any indexed script" for
    a natural-spelling query the search itself resolves.
    """
    _t_canon, t_group = resolve_name_ci(ti, table)
    _f_canon, f_group = resolve_name_ci(fi, field)
    table_in_index = bool(t_group)
    field_in_index = bool(f_group)
    table_scripts = len(scripts_for_name_ci(ti, table))
    field_scripts = len(scripts_for_name_ci(fi, field))
    match_scripts = len(result.get("script_ids", []))
    if not base_table_in_index:
        suggestion = "Table %s is not queried by any indexed script - no data flow exists for it" % table
    elif not base_field_in_index:
        suggestion = ("Field %s.%s is not queried by any indexed script - "
                      "no data flow exists for it") % (table, field)
    elif filter_active and not table_in_index:
        suggestion = "Table not in filter scope - add to script_table.csv or clear filter"
    elif filter_active and not field_in_index:
        suggestion = "Field not in filter scope - add to table_col.csv or clear filter"
    elif match_scripts == 0 and table_in_index and field_in_index:
        suggestion = "Table and field exist but no script contains both - try different field"
    elif match_scripts == 0:
        suggestion = "No matching scripts - check table/field name spelling"
    else:
        suggestion = "OK"
    return (filter_active, scope_tables, scope_fields, table_in_index, field_in_index,
            table_scripts, field_scripts, match_scripts, suggestion)


def _load_base_index(ws_id: str) -> tuple[dict, dict]:
    """Load the UNFILTERED table_index.json / field_index.json.

    BE2 (issue c): the R17 diagnostic needs to know whether a searched
    table/field exists in the base index at all — the loaded (possibly
    filtered) index cannot distinguish "no script queries it" from "the
    filter CSV excluded it".
    """
    cache_dir = get_workspace_dir(ws_id) / "cache"
    ti_path = cache_dir / "table_index.json"
    fi_path = cache_dir / "field_index.json"
    ti = json.loads(ti_path.read_text()) if ti_path.exists() else {}
    fi = json.loads(fi_path.read_text()) if fi_path.exists() else {}
    return ti, fi


@router.post("/workspace/{ws_id}/search")
async def search_dataflow(ws_id: str, body: dict):
    """Search for data flow of table.field. body: {table, field}"""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not ws.get("indexed"):
        raise HTTPException(status_code=400, detail="Workspace not indexed. Run index first.")

    table = body.get("table", "").strip()
    field = body.get("field", "").strip()
    if not table or not field:
        raise HTTPException(status_code=400, detail="Both 'table' and 'field' are required")

    # R29/K4 ruling 4: query direction — an absent value and the legacy
    # "upstream" both resolve to "downstream" (the field's READING flow,
    # the only direction R38 kept); anything outside the allowlist is a
    # 400, never a silent fall-through to a branch.
    direction = _normalize_direction(body.get("direction"))

    ti, fi, filtered_active, scope_tables, scope_fields = _load_index(ws_id)
    # BE2: base-index presence drives the R17 suggestion (base vs CSV scope).
    # F5: presence is CASE-INSENSITIVE (same resolution rule as create_search)
    # — index keys carry each script's own casing.
    base_ti, base_fi = _load_base_index(ws_id)
    base_table_in_index = bool(resolve_name_ci(base_ti, table)[1])
    base_field_in_index = bool(resolve_name_ci(base_fi, field)[1])
    if not ti and not fi:
        if filtered_active:
            # F1: filter active but empty (empty intersection) — indexing
            # already passed (see 400 guard above); the filter simply matches
            # nothing. Return a successful empty result instead of a 400.
            result = {
                "view_id": uuid.uuid4().hex[:12],
                "table": table,
                "field": field,
                "script_ids": [],
                "l1_graph": {"nodes": [], "edges": [], "target": "table.field"},
                "match_mode": "no_matches",
                "message": "Filter active — no tables in scope",
                "direction": direction,
            }
            # R3: the no_matches path also emits the R17 search diagnostic
            # (same block shape as a regular search, via the same _push hook).
            _emit_search_diagnostic(ws_id, table, field,
                                    *_search_diagnostic_values(table, field, ti, fi, result,
                                                               filtered_active, scope_tables, scope_fields,
                                                               base_table_in_index, base_field_in_index))
            # R3: persist the empty view like any other search, so it
            # survives reload (create_search is bypassed on this path).
            # N4: l1_graph_cache carries `target` for shape parity with
            # regular views. M8: match_mode + message saved so the frontend
            # can show the no-match banner after a reload.
            await _persist_search_view(ws_id, {
                "view_id": result["view_id"],
                "type": "search",
                "table": table,
                "field": field,
                "script_ids": [],
                "script_count": 0,
                "l1_graph_cache": {"nodes": [], "edges": [], "target": "table.field"},
                "match_mode": "no_matches",
                "message": "Filter active — no tables in scope",
                "direction": direction,
                "children": [],
            })
            return result
        raise HTTPException(status_code=400, detail="Indexes not found. Run index first.")

    lineage_mode = body.get("lineage_mode", True)  # R18: default True
    # R31 (#273): under the global heavy-op gate — while another heavy op
    # runs, this returns 409 "system busy — please wait". create_search's L1
    # graph build is CPU-bound and runs in a worker thread so the single
    # worker's event loop is not blocked.
    with gate as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="system busy — please wait")
        result = await asyncio.to_thread(
            _run_coro_in_thread, create_search, ws_id, table, field, ti, fi,
            lineage_mode, direction)

    # ── R17: Search diagnostic logging ──
    _emit_search_diagnostic(ws_id, table, field,
                            *_search_diagnostic_values(table, field, ti, fi, result,
                                                       filtered_active, scope_tables, scope_fields,
                                                       base_table_in_index, base_field_in_index))
    return result


@router.get("/workspace/{ws_id}/views")
async def get_views(ws_id: str):
    """List all search views for this workspace."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"views": list_views(ws_id)}


@router.post("/workspace/{ws_id}/views/{view_id}/children")
async def add_view_child(request: Request, ws_id: str, view_id: str, body: dict):
    """Add a child (L2 script) entry to a view. Persisted to views.json."""
    username, _ = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only mutation — only the workspace creator may
    # add a child view (non-creator session → 403).
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may add a child view")
    views = _load_views(ws_id)
    for v in views:
        if v["view_id"] == view_id:
            children = v.setdefault("children", [])
            # Avoid duplicates
            if not any(c["view_id"] == body.get("view_id") for c in children):
                children.append(body)
            _save_views(ws_id, views)
            return {"added": True, "view_id": view_id, "child_id": body.get("view_id")}
    raise HTTPException(status_code=404, detail="Parent view not found")


@router.delete("/workspace/{ws_id}/views/{view_id}")
async def remove_view(request: Request, ws_id: str, view_id: str):
    """Delete a search view or child L2 entry."""
    username, _ = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only mutation — only the workspace creator may
    # delete a view (non-creator session → 403).
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may delete a view")
    ok = delete_view(ws_id, view_id)
    if not ok:
        raise HTTPException(status_code=404, detail="View not found")
    return {"deleted": True}


@router.get("/workspace/{ws_id}/views/{view_id}/level1")
async def get_level1(ws_id: str, view_id: str,
                     direction: str | None = Query(None)):
    """Get L1 cross-script graph for a view. Rebuilds fresh each time.

    R29: `direction` query param overrides the view's persisted direction
    (the search-time choice survives reload via views.json). K4 ruling 4:
    an absent param and a legacy "upstream" both resolve to "downstream"
    (the only honored direction). Passed to _build_l1_graph — the
    directional projection."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    views = list_views(ws_id)
    view = next((v for v in views if v["view_id"] == view_id), None)
    if not view:
        raise HTTPException(status_code=404, detail="View not found")

    # Rebuild L1 graph fresh — never return stale cache
    from app.services.dataflow_service import _build_l1_graph, _filter_l1_by_lineage
    script_ids = view.get("script_ids", [])
    table = view.get("table", "")
    field = view.get("field", "")
    # CR2: an explicit query param is validated strictly ("" and typos →
    # 400); only an ABSENT param falls back to the view's persisted
    # direction (or the downstream default). A persisted legacy "upstream"
    # is coerced — accepted, never honored.
    direction = (_normalize_direction(direction) if direction is not None
                 else _normalize_direction(view.get("direction")))
    l1_graph = _build_l1_graph(ws_id, script_ids, table, field,
                               direction=direction)
    # BE2 (issues b+c): mirror the search-time path — search views carry a
    # table+field, so apply the same R18 lineage filter. Only flow-relevant
    # scripts/tables survive (keeps L1 simple, consistent with /search).
    # R29: table-only searches only — field queries skip it (the
    # directional L1 already IS the field flow, mirror of create_search).
    if table and not field:
        l1_graph = _filter_l1_by_lineage(l1_graph, table, field)

    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": script_ids,
        "l1_graph": l1_graph,
        "direction": direction,
    }


@router.get("/workspace/{ws_id}/views/{view_id}/level2")
def get_level2(ws_id: str, view_id: str, script: str = Query(...),
               filter: bool = Query(True),
               direction: str | None = Query(None)):
    """Get L2 per-script graph for a view's script.

    R29: `direction` query param overrides the view's persisted direction
    (search-time choice survives reload via views.json). K4 ruling 4: an
    absent param and a legacy "upstream" both resolve to "downstream".
    Threaded into get_level2_graph — the strict field-flow filter and the
    L2 builder.

    W5/R25: every edge carries its per-edge payload (highlight_line /
    flow_kind / reason) built at L2 build time — the old response-level
    `highlights` and the `highlight_strategy` query param are gone (R25
    item 3); the payload is unconditional.

    E4 (item 2): plain `def`, not `async def` — the cold path runs the
    full extraction pipeline (parse + graph + schema infer + cache
    writes), which must run in FastAPI's threadpool, never on the event
    loop (one request used to freeze the whole service).
    E4 (item 1): `script` is user-controlled — validate it against the
    workspace scripts dir via the shared containment resolver before any
    read/pipeline work; a traversal attempt gets the same error shape the
    service returns for a genuinely missing script.
    """
    from app.services.filter_service import resolve_script
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if resolve_script(ws_id, script) is None:
        return {"error": f"Script '{script}' not found"}
    views = list_views(ws_id)

    # Find parent view
    view = next((v for v in views if v["view_id"] == view_id), None)
    if not view:
        # Check children
        for v in views:
            for c in v.get("children", []):
                if c["view_id"] == view_id:
                    view = v
                    break

    if not view:
        raise HTTPException(status_code=404, detail="View not found")

    table = view.get("table", "")
    field = view.get("field", "")
    # CR2: an explicit query param is validated strictly ("" and typos →
    # 400); only an ABSENT param falls back to the view's persisted
    # direction (or the downstream default). A persisted legacy "upstream"
    # is coerced — accepted, never honored.
    direction = (_normalize_direction(direction) if direction is not None
                 else _normalize_direction(view.get("direction")))

    result = get_level2_graph(ws_id, view_id, script, table, field, filter,
                              direction)
    return result


@router.get("/workspace/{ws_id}/scripts/{script_name}/highlight")
def get_highlight(ws_id: str, script_name: str,
                  table: str = Query(...), field: str = Query(...)):
    """Get SQL highlight ranges for a script.

    E4 (item 3): `script_name` previously joined raw into the scripts path
    — `script=..` raised IsADirectoryError (500). Route through the
    containment resolver; missing / not-a-file → 404.

    E4 (threadpool, code review #5): plain `def`, not `async def` —
    `get_highlight_ranges` runs `build_graph_data` + `filter_relevant`
    synchronously; a sync route runs in FastAPI's threadpool, never on the
    event loop (mirror of the `get_level2` conversion above).
    """
    from app.services.filter_service import resolve_script
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    sp = resolve_script(ws_id, script_name)
    if sp is None or not sp.is_file():
        raise HTTPException(status_code=404, detail=f"Script '{script_name}' not found")
    return get_highlight_ranges(ws_id, script_name, table, field)


# ═══════════════════════════════════════════════════════════════════
# Debug endpoint — fast layout verification without browser
# ═══════════════════════════════════════════════════════════════════

@router.post("/workspace/{ws_id}/debug/graph")
async def debug_graph_layout(ws_id: str, body: dict):
    """Return computed graph layout data (table heights, field positions, edges)
    for fast verification without needing a browser.

    body: {table, field}  — same as search endpoint
    Returns: {
        l1: {tables: [{id, label, x, y, height, fields: [{id, label, ry}]}],
             scripts: [{id, label, x, y}],
             edges: [{source, target, edge_type}]},
        field_bounds_check: [{field_id, label, table_id, table_y, table_half,
                              field_y, inside}]
    }
    """
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not ws.get("indexed"):
        raise HTTPException(status_code=400, detail="Workspace not indexed")

    table = body.get("table", "").strip()
    field = body.get("field", "").strip()
    if not table or not field:
        raise HTTPException(status_code=400, detail="Both 'table' and 'field' are required")

    ti, fi, _, _, _ = _load_index(ws_id)
    if not ti and not fi:
        raise HTTPException(status_code=400, detail="Index not found")

    # Run search to get L1 graph — under the global heavy-op gate (R31 #273),
    # like /search: CPU-bound work runs in a worker thread so the event loop
    # is not blocked; a concurrent heavy op returns 409 "system busy".
    from app.services.dataflow_service import create_search
    with gate as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="system busy — please wait")
        search_result = await asyncio.to_thread(
            _run_coro_in_thread, create_search, ws_id, table, field, ti, fi)

    # Extract graph data
    l1_data = search_result.get("l1_graph", {})
    nodes = l1_data.get("nodes", [])
    edges = l1_data.get("edges", [])

    # ── Compute same layout as frontend ──
    TABLE_HDR_H = 26
    FIELD_H = 50
    TABLE_MIN_H = 80

    # Build field→parent lookup
    fields_by_parent = {}
    table_nodes = []
    script_nodes = []
    field_nodes = []

    for n in nodes:
        nd = n.get("data", n)
        t = nd.get("type", "")
        if t.endswith("_table") or t in ("query_output", "cte_table"):
            table_nodes.append({"id": nd["id"], "label": nd.get("label", ""),
                                "x": nd.get("x", 0), "y": nd.get("y", 0),
                                "type": t})
        elif t == "script_node":
            script_nodes.append({"id": nd["id"], "label": nd.get("label", ""),
                                 "x": nd.get("x", 0), "y": nd.get("y", 0),
                                 "type": t})
        elif t == "field":
            pid = nd.get("parent", "")
            field_nodes.append({"id": nd["id"], "label": nd.get("label", ""),
                               "parent": pid, "type": t})
            if pid:
                if pid not in fields_by_parent:
                    fields_by_parent[pid] = []
                fields_by_parent[pid].append({"id": nd["id"], "label": nd.get("label", "")})

    # ── Check for duplicate fields in fields_by_parent (anti-pattern detection) ──
    duplicate_warnings = []
    seen_field_ids = set()
    for pid, flds in fields_by_parent.items():
        ids_in_group = [f["id"] for f in flds]
        for fid in ids_in_group:
            if fid in seen_field_ids:
                duplicate_warnings.append(f"DUPLICATE: field {fid} appears in multiple groups or twice in {pid}")
            seen_field_ids.add(fid)

    # Compute table heights and field relative positions (centered)
    tables_out = []
    for tn in table_nodes:
        pid = tn["id"]
        flds = fields_by_parent.get(pid, [])
        flds.sort(key=lambda f: f.get("label", ""))

        n = len(flds)
        th = max(TABLE_MIN_H, TABLE_HDR_H + 12 + n * FIELD_H + 12)
        start_y = -(th / 2) + TABLE_HDR_H + 6 + FIELD_H / 2

        fields_out = []
        for i, f in enumerate(flds):
            ry = start_y + i * FIELD_H
            fields_out.append({"id": f["id"], "label": f["label"], "ry": round(ry, 2)})

        tables_out.append({
            "id": pid, "label": tn["label"], "type": tn["type"],
            "x": tn["x"], "y": tn["y"],
            "height": th, "field_count": n,
            "fields": fields_out,
        })

    # ── Field bounds check ──
    bounds_checks = []
    for tn in tables_out:
        thalf = tn["height"] / 2
        ty = tn["y"]
        for f in tn["fields"]:
            field_y = ty + f["ry"]
            inside = (ty - thalf - 2) < field_y < (ty + thalf + 2)
            bounds_checks.append({
                "field_id": f["id"], "label": f["label"],
                "table_id": tn["id"], "table_label": tn["label"],
                "table_y": ty, "table_half": thalf,
                "field_abs_y": round(field_y, 2),
                "inside": inside,
            })

    return {
        "workspace_id": ws_id,
        "query": {"table": table, "field": field},
        "l1": {
            "tables": tables_out,
            "scripts": script_nodes,
            "edges": [{"source": e.get("data", e).get("source", ""),
                       "target": e.get("data", e).get("target", ""),
                       "edge_type": e.get("data", e).get("edge_type", "")} for e in edges],
        },
        "field_bounds_check": bounds_checks,
        "fields_outside_table": sum(1 for b in bounds_checks if not b["inside"]),
        "duplicate_warnings": duplicate_warnings,
    }
