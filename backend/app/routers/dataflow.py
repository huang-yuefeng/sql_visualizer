"""Dataflow router — search, views, L1/L2 graphs, SQL highlight."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.services.workspace_service import get_workspace, get_workspace_dir
from app.services.dataflow_service import (
    _load_views, _save_views,
    create_search, get_level2_graph,
    list_views, delete_view,
)
from app.services.sql_highlight_service import get_highlight_ranges

router = APIRouter(tags=["dataflow"])


def _load_index(ws_id: str) -> tuple[dict, dict]:
    """Load table_index and field_index from cache. Prefers filtered index."""
    cache_dir = get_workspace_dir(ws_id) / "cache"
    # Prefer filtered index if available
    filtered_path = cache_dir / "filtered_index.json"
    if filtered_path.exists():
        filtered = json.loads(filtered_path.read_text())
        return filtered.get("table_index", {}), filtered.get("field_index", {})
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

    ti, fi = _load_index(ws_id)
    if not ti and not fi:
        raise HTTPException(status_code=400, detail="Indexes not found. Run index first.")

    result = create_search(ws_id, table, field, ti, fi)
    return result


@router.get("/workspace/{ws_id}/views")
async def get_views(ws_id: str):
    """List all search views for this workspace."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"views": list_views(ws_id)}


@router.post("/workspace/{ws_id}/views/{view_id}/children")
async def add_view_child(ws_id: str, view_id: str, body: dict):
    """Add a child (L2 script) entry to a view. Persisted to views.json."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
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
async def remove_view(ws_id: str, view_id: str):
    """Delete a search view or child L2 entry."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ok = delete_view(ws_id, view_id)
    if not ok:
        raise HTTPException(status_code=404, detail="View not found")
    return {"deleted": True}


@router.get("/workspace/{ws_id}/views/{view_id}/level1")
async def get_level1(ws_id: str, view_id: str):
    """Get L1 cross-script graph for a view. Rebuilds fresh each time."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    views = list_views(ws_id)
    view = next((v for v in views if v["view_id"] == view_id), None)
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    
    # Rebuild L1 graph fresh — never return stale cache
    from app.services.dataflow_service import _build_l1_graph
    script_ids = view.get("script_ids", [])
    table = view.get("table", "")
    field = view.get("field", "")
    l1_graph = _build_l1_graph(ws_id, script_ids, table, field)
    
    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": script_ids,
        "l1_graph": l1_graph,
    }


@router.get("/workspace/{ws_id}/views/{view_id}/level2")
async def get_level2(ws_id: str, view_id: str, script: str = Query(...),
                      filter: bool = Query(True)):
    """Get L2 per-script graph for a view's script."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
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

    result = get_level2_graph(ws_id, view_id, script, table, field, filter)
    return result


@router.get("/workspace/{ws_id}/scripts/{script_name}/highlight")
async def get_highlight(ws_id: str, script_name: str,
                         table: str = Query(...), field: str = Query(...)):
    """Get SQL highlight ranges for a script."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
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

    ti, fi = _load_index(ws_id)
    if not ti and not fi:
        raise HTTPException(status_code=400, detail="Index not found")

    # Run search to get L1 graph
    from app.services.dataflow_service import create_search
    search_result = create_search(ws_id, table, field, ti, fi)

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
