"""Workspace router — zip upload, workspace CRUD."""
from fastapi import APIRouter, HTTPException, UploadFile, File
import csv
import io
from app.services.workspace_service import (
    create_workspace, get_workspace, delete_workspace,
    get_workspace_dir, cleanup_all_workspaces,
)
from app.services.export_config_service import (
    get_export_config, save_export_config, reset_export_config,
    apply_export_config, DEFAULT_CONFIG,
)
from app.services.folder_index_service import (
    scan_folder, index_scripts, get_index_status,
    get_index_progress,
)

router = APIRouter(tags=["workspace"])


@router.post("/workspace")
async def upload_workspace(file: UploadFile):
    """Upload a zip file, create workspace. Auto-scans and returns file tree."""
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files accepted")
    
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 100MB)")
    
    try:
        ws_id = create_workspace(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract zip: {str(e)}")
    
    # Auto-scan
    tree = scan_folder(ws_id)
    
    return {
        "workspace_id": ws_id,
        "file_tree": tree,
    }


@router.get("/workspace/{ws_id}")
async def get_workspace_info(ws_id: str):
    """Get workspace metadata and status."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    status = get_index_status(ws_id)
    ws["index_status"] = status
    return ws


@router.delete("/workspace/{ws_id}")
async def delete_workspace_endpoint(ws_id: str):
    """Delete workspace and all its data."""
    ok = delete_workspace(ws_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True}


@router.post("/workspace/{ws_id}/scan")
async def scan_workspace(ws_id: str):
    """Scan workspace directory, return file tree."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return scan_folder(ws_id)


@router.post("/workspace/{ws_id}/index")
async def index_workspace(ws_id: str, body: dict):
    """Index selected scripts. body: {scripts: ["path1.sql", ...]}"""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    scripts = body.get("scripts", [])
    if not scripts:
        # Auto-select all SQL files from scan
        tree = scan_folder(ws_id)
        scripts = _collect_sql_files(tree)
    
    result = index_scripts(ws_id, scripts)
    return result



@router.get("/workspace/{ws_id}/status")
async def get_workspace_status(ws_id: str):
    """Poll workspace indexing progress."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    progress = get_index_progress(ws_id)
    status = get_index_status(ws_id)
    return {"workspace_id": ws_id, "progress": progress, "index_status": status}


@router.post("/workspace/{ws_id}/filter-config")
async def upload_filter_config(ws_id: str,
                                script_table: UploadFile = File(None),
                                table_col: UploadFile = File(None)):
    """Upload CSV filter files to narrow the table/field index.
    
    File 1 (script_table): SCRIPT_NAME, TABLE_NAME columns
    File 2 (table_col): SYSTEM, TABLE_NAME, COL_NAME, COL_COMMENT columns
    
    If neither file is uploaded, clears any active filter (show all).
    Stores filtered_index.json in workspace cache.
    """
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cache_dir = get_workspace_dir(ws_id) / "cache"

    # Parse CSV files
    allowed_scripts = None  # None = no filter
    allowed_tables = None
    allowed_columns = None

    if script_table and script_table.filename:
        raw = (await script_table.read()).decode("utf-8", errors="replace")
        allowed_scripts = set()
        allowed_tables = set()
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            sn = row.get("SCRIPT_NAME", "").strip()
            tn = row.get("TABLE_NAME", "").strip()
            if sn: allowed_scripts.add(sn)
            if tn: allowed_tables.add(tn)

    if table_col and table_col.filename:
        raw = (await table_col.read()).decode("utf-8", errors="replace")
        if allowed_tables is None:
            allowed_tables = set()
        allowed_columns = set()
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            tn = row.get("TABLE_NAME", "").strip()
            cn = row.get("COL_NAME", "").strip()
            if tn: allowed_tables.add(tn)
            if cn: allowed_columns.add(cn)

    # If neither file uploaded, clear filter
    if allowed_scripts is None and allowed_tables is None and allowed_columns is None:
        fp = cache_dir / "filtered_index.json"
        if fp.exists():
            fp.unlink()
        return {"filtered": False, "message": "Filter cleared — showing all indexed entries"}

    # Load full indexes
    import json
    ti_path = cache_dir / "table_index.json"
    fi_path = cache_dir / "field_index.json"
    ti = json.loads(ti_path.read_text()) if ti_path.exists() else {}
    fi = json.loads(fi_path.read_text()) if fi_path.exists() else {}

    # Filter table_index
    filtered_ti = {}
    for tname, tdata in ti.items():
        if allowed_tables and tname not in allowed_tables:
            continue
        filtered_scripts = [s for s in tdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts]
        filtered_fields = [f for f in tdata.get("fields", [])
                          if allowed_columns is None or f in allowed_columns]
        if filtered_scripts or filtered_fields:
            filtered_ti[tname] = {
                "scripts": filtered_scripts,
                "fields": filtered_fields,
            }

    # Filter field_index
    filtered_fi = {}
    for fname, fdata in fi.items():
        if allowed_columns and fname not in allowed_columns:
            continue
        filtered_scripts = [s for s in fdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts]
        filtered_tables = [t for t in fdata.get("tables", [])
                          if allowed_tables is None or t in allowed_tables]
        if filtered_scripts or filtered_tables:
            filtered_fi[fname] = {
                "scripts": filtered_scripts,
                "tables": filtered_tables,
            }

    # Save filtered index
    (cache_dir / "filtered_index.json").write_text(json.dumps({
        "table_index": filtered_ti,
        "field_index": filtered_fi,
    }, indent=2))

    return {
        "filtered": True,
        "table_count": len(filtered_ti),
        "field_count": len(filtered_fi),
    }


@router.delete("/workspace")
async def cleanup_workspaces():
    """Delete ALL workspaces. Use with caution."""
    removed = cleanup_all_workspaces()
    return {"cleaned": removed}

@router.get("/workspace/{ws_id}/export-config")
async def get_export_config_endpoint(ws_id: str):
    """Get current SQL export config (or defaults if none uploaded)."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return get_export_config(ws_id)


@router.put("/workspace/{ws_id}/export-config")
async def update_export_config(ws_id: str, body: dict):
    """Save SQL export config. Body: partial or full config dict."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    config = save_export_config(ws_id, body)
    return config


@router.delete("/workspace/{ws_id}/export-config")
async def delete_export_config(ws_id: str):
    """Reset SQL export config to defaults."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return reset_export_config(ws_id)


@router.get("/workspace/{ws_id}/export-config/default")
async def get_default_config():
    """Return the built-in default export config (read-only reference)."""
    return dict(DEFAULT_CONFIG)


@router.get("/workspace/{ws_id}/autocomplete")
async def autocomplete(ws_id: str, type: str = "table", q: str = ""):
    """Get autocomplete suggestions. type: 'table' or 'field'."""
    from app.services.folder_index_service import autocomplete as ac
    import json
    
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    cache_dir = get_workspace_dir(ws_id) / "cache"
    index_path = cache_dir / (f"{type}_index.json")
    
    if not index_path.exists():
        return {"suggestions": []}
    
    index = json.loads(index_path.read_text())
    suggestions = ac(index, type, q)
    return {"suggestions": suggestions}


def _collect_sql_files(tree: dict) -> list:
    """Recursively collect all .sql file paths from a tree."""
    paths = []
    if tree.get("type") == "file" and tree.get("is_sql"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_sql_files(child))
    return paths
