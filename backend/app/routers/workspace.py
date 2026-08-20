"""Workspace router — zip upload, workspace CRUD."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from app.services.logger import _push
from app.services.workspace_service import (
    create_workspace, get_workspace, delete_workspace,
    get_workspace_dir, cleanup_all_workspaces, is_valid_ws_id,
)
from app.services.export_config_service import (
    get_export_config, save_export_config, reset_export_config,
    apply_export_config, DEFAULT_CONFIG,
)
from app.services.folder_index_service import (
    scan_folder, index_scripts, get_index_status,
    get_index_progress,
)
from app.services.filter_service import apply_filter_config

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
    """Delete workspace and all its data.

    F2: ws_id is user-controlled path input — validate it first. A
    malformed id (not 12 hex chars) is a 400; a well-formed id that names
    no workspace is a 404 (consistent with delete_workspace's False).
    """
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    ok = delete_workspace(ws_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Clean up SSE log queue
    from app.services.logger import remove_queue
    remove_queue(ws_id)
    return {"deleted": True}


@router.post("/workspace/{ws_id}/scan")
async def scan_workspace(ws_id: str):
    """Scan workspace directory, return file tree."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return scan_folder(ws_id)


@router.post("/workspace/{ws_id}/index")
def index_workspace(ws_id: str, body: dict):
    """Index the ENTIRE workspace — the index is ALWAYS the complete
    workspace index, never a caller-supplied subset.

    #257: the body's `scripts` list is IGNORED. A partial script list used
    to overwrite cache/table_index.json with exactly that list (no merge),
    silently destroying search coverage for every script left out (observed
    live: bdm_acc_loan_info.ACCT_CLOSE_DT returned "not queried by any
    script" after a partial index; a full re-index fixed it). The index is
    rebuilt over EVERY pipeline SQL file on every call; uploading a folder
    is the single index update.

    E4 (item 2): plain `def`, not `async def` — indexing runs the full
    extraction pipeline (parse + graph + schema inference + analysis-cache
    writes) per script; it must run in FastAPI's threadpool, never on the
    event loop (a large index request used to freeze the whole service).
    """
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # #257: always rebuild from the on-disk tree — a subset `scripts` body
    # must never shrink the index. _collect_sql_files excludes schema files
    # (evidence-only); index_scripts discovers those itself. C-13(a)/#257:
    # scan ONCE with a parsed_cache and thread both the tree and the cache
    # into index_scripts — without it, index_scripts would scan_folder
    # again (re-read + re-parse every .sql) a second time per request,
    # doubling the scan cost and opening a two-scan TOCTOU on the on-disk
    # tree (a script vanishing between the scans would silently lose
    # coverage — the exact class #257 fixes).
    parsed_cache = {}
    tree = scan_folder(ws_id, parsed_cache=parsed_cache)
    scripts = _collect_sql_files(tree)

    result = index_scripts(ws_id, scripts, tree=tree, parsed_cache=parsed_cache)
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

    Logic lives in app.services.filter_service (F6); this handler is
    HTTP-only. `push=_push` is resolved at call time so tests can
    intercept the R16 diagnostic stream.
    """
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return await apply_filter_config(ws_id, script_table, table_col, push=_push)


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


# E4 (item 4): `type` is user-controlled and was joined raw into the cache
# path (`f"{type}_index.json"`) — `type=../../../<other_ws>/cache/table`
# read another workspace's table_index.json. Whitelist the index kinds the
# indexer actually writes (folder_index_service: table_index.json /
# field_index.json / pair_index.json); anything else is a 400.
_ACCEPTED_INDEX_TYPES = frozenset({"table", "field", "pair"})


@router.get("/workspace/{ws_id}/autocomplete")
def autocomplete(ws_id: str, type: str = "table", q: str = ""):
    """Get autocomplete suggestions. type: 'table' or 'field'.

    E4 (item 4): unknown `type` values (e.g. path traversal) are rejected
    with 400 — the cache path is only ever built from the whitelist.
    E4 (item 2): plain `def` — index JSON files are large; the parse runs
    in the threadpool, not on the event loop.
    """
    from app.services.folder_index_service import autocomplete as ac
    import json

    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if type not in _ACCEPTED_INDEX_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown autocomplete type: {type}")

    cache_dir = get_workspace_dir(ws_id) / "cache"
    index_path = cache_dir / (f"{type}_index.json")

    if not index_path.exists():
        return {"suggestions": []}

    try:
        index = json.loads(index_path.read_text())
    except Exception:
        return {"suggestions": []}  # corrupt index cache — never 500

    suggestions = ac(index, type, q)
    return {"suggestions": suggestions}


def _collect_sql_files(tree: dict) -> list:
    """Recursively collect all pipeline-script paths from a tree.

    A1: schema files (file_class == "schema" — DDL-only) are excluded:
    they are evidence-only, never pipeline scripts. Old trees without the
    file_class key default to "script" (defensive read), preserving the
    pre-A1 behavior. index_scripts discovers schema files itself, so the
    S4b evidence pass still sees them on this auto-select path.
    """
    paths = []
    if (tree.get("type") == "file" and tree.get("is_sql")
            and tree.get("file_class", "script") != "schema"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_sql_files(child))
    return paths
