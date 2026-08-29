"""Workspace router — zip upload, workspace CRUD, R31 lifecycle."""
import json

from fastapi import APIRouter, HTTPException, UploadFile, File, Request

from app.config import REQUIRE_LOGIN
from app.routers.auth import require_login, SESSION_COOKIE, _client_ip
from app.services.logger import _push
from app.services.workspace_service import (
    create_workspace, get_workspace, delete_workspace,
    get_workspace_dir, is_valid_ws_id,
    read_meta, write_meta_cas, remove_from_my_history, remove_legacy_workspaces,
)
from app.services.auth_service import (
    add_workspace_to_index, get_my_workspaces, index_has_room,
)
from app.services.audit_service import append_activity, read_activity
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


def _session_ctx(request: Request) -> tuple[str, str | None]:
    """Current session's (username, token). 401 when REQUIRE_LOGIN is on and
    there is no valid session. A present, valid session cookie is ALWAYS
    honored (login is not ignored when the gate is off — gate-off merely
    means login is not REQUIRED); with the gate off and no session the
    caller is the synthetic "dev-user" so the existing suite keeps working."""
    token = request.cookies.get(SESSION_COOKIE)
    sess = None
    if token:
        from app.services.auth_service import get_session
        sess = get_session(token)
    if sess is not None:
        return sess["username"], token
    if not REQUIRE_LOGIN:
        return "dev-user", None
    raise HTTPException(status_code=401, detail="Not logged in")


@router.post("/workspace")
async def upload_workspace(request: Request, file: UploadFile):
    """Upload a zip file, create workspace. Auto-scans and returns file tree.

    R31/A-M6: this is the workspace CREATE path. The server generates the
    UUID4 ws_id (A-H4), stamps creator_username in meta.json, and adds it to
    the creator's "my workspaces" index — refused with 409 when the creator's
    list is full (quota, A-M2). Requires a session when REQUIRE_LOGIN is on.
    """
    username, token = _session_ctx(request)
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 100MB)")
    # The quota + per-user index are REAL-session features (A-M2). When the
    # login gate is OFF (dev/test, synthetic "dev-user", token=None) they are
    # skipped entirely — otherwise a long-running dev suite would fill the
    # phantom dev-user index to the cap and every create would 409.
    if token:
        if not index_has_room(username):
            raise HTTPException(status_code=409,
                                detail="Your workspace list is full — remove one from your list first")

    try:
        ws_id = create_workspace(content, creator_username=username)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract zip: {str(e)}")

    if token:
        add_workspace_to_index(username, ws_id, "creator")
        append_activity(ws_id, username, _client_ip(request), "workspace_created",
                        f"{username} created this workspace")

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


@router.delete("/me/workspaces/{ws_id}")
async def remove_from_my_history_endpoint(request: Request, ws_id: str):
    """R31 remove-from-my-history — ONE role-dependent action (A-M1/A-M2).

    - creator → PHYSICAL DELETE: server-global audit entry written BEFORE
      removal (A-H3), then the workspace + files are removed and it drops
      from every user's index (pop-up warning on the frontend).
    - non-creator → link removed from the caller's index only; the action is
      recorded in the workspace's activity log; the workspace survives.

    F2: validate the id first — malformed → 400, valid-format missing → 404.
    """
    username, token = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    if get_workspace(ws_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ok, message, deleted = remove_from_my_history(ws_id, username, _client_ip(request))
    if not ok:
        raise HTTPException(status_code=404, detail=message)
    if deleted:
        # Clean up SSE log queue
        from app.services.logger import remove_queue
        remove_queue(ws_id)
    return {"deleted": deleted, "message": message}


@router.get("/workspaces")
async def my_workspaces(request: Request):
    """R31: the current user's "my workspaces" index + quota meter."""
    username, _ = _session_ctx(request)
    return get_my_workspaces(username)


@router.put("/workspace/{ws_id}/layout")
async def save_layout(request: Request, ws_id: str, body: dict):
    """R31/A-M5: single layout endpoint — autosave node positions into
    meta.json.layouts (key "l1" or "l2:{script}"). Current-state only
    (replaces the entry). Positions for node ids that no longer exist are
    skipped by the reader; stale l2:{script} keys are dropped on resume."""
    username, token = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    meta = read_meta(ws_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only layout editing — only the workspace creator
    # may PUT layout (non-creator session → 403).
    if meta.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may edit the layout")
    level = body.get("level")
    script = body.get("script")
    positions = body.get("node_positions") or {}
    if level not in ("l1", "l2"):
        raise HTTPException(status_code=400, detail="level must be l1 or l2")
    if level == "l2" and not script:
        raise HTTPException(status_code=400, detail="script required for l2 layouts")
    key = "l1" if level == "l1" else f"l2:{script}"
    layouts = dict(meta.get("layouts") or {})
    # R31 (#272): E-H4 — the old opened_l2s prune DROPPED every l2:* key
    # (opened_l2s is never written, so the set was always empty → L2 layout
    # persistence was dead). The filter is removed so L2 positions persist.
    layouts[key] = positions
    meta["layouts"] = layouts
    expected = int(body.get("state_version", meta.get("state_version", 0)))
    if not write_meta_cas(ws_id, meta, expected):
        fresh = read_meta(ws_id)
        raise HTTPException(status_code=409, detail={
            "message": f"state changed by another user — refreshed",
            "fresh": fresh,
        })
    return {"saved": True, "state_version": read_meta(ws_id).get("state_version")}


@router.get("/workspace/{ws_id}/resume")
async def resume_workspace(request: Request, ws_id: str):
    """R31: full current state (L1 + opened L2s + positions + state_version)."""
    username, token = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    meta = read_meta(ws_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if token:
        # R31 §5.5: membership = created + visited — an id-open that isn't
        # already in the opener's index lands there as a participant. §5.6:
        # at the cap (MAX_WORKSPACES_PER_USER) a NEW id-open is blocked with
        # 409 — the existing-entry refresh below never hits the quota branch,
        # so reopening a workspace already on the list always succeeds.
        if not add_workspace_to_index(username, ws_id, "participant"):
            raise HTTPException(
                status_code=409,
                detail="Your workspace list is full — remove one from your list first")
    return {
        "workspace_id": ws_id,
        "creator_username": meta.get("creator_username"),
        "state_version": meta.get("state_version", 0),
        "last_search": meta.get("last_search"),
        "opened_l2s": meta.get("opened_l2s", []),
        "layouts": meta.get("layouts", {}),
        "index_status": get_index_status(ws_id),
    }


# ── #380 (AD2-A, 2026-08-29): participant-readable workspace artifacts ──────
# #380 made POST /scan + POST /index creator-only (correct — both rewrite
# shared workspace state), but they were the ONLY endpoints serving the file
# tree and the table/field indexes, so a participant clicking Open on a
# shared workspace 403'd and the workspace never opened (AD2 verified live:
# /resume, /views, /autocomplete already 200 for a participant). The fix is
# the read-only half: index_scripts persists the tree it covered and the
# derived index report, and the two GETs below serve those artifacts to ANY
# session — same gates as /resume (_session_ctx 401, malformed id 400,
# unknown workspace 404), NO creator check, no state written.

_INDEX_REPORT_KEYS = (
    "script_count", "errors", "orphan_field_count", "orphan_field_samples",
    "resolution_stats", "schema_candidates_summary", "schema_evidence",
)


@router.get("/workspace/{ws_id}/tree")
def get_workspace_tree(request: Request, ws_id: str):
    """Serve the file tree the last index covered (cache/file_tree.json).

    #380 (AD2-A): the participant half of Open — the tree includes the A1
    `file_class` (schema vs script) because index_scripts persists the
    scan_folder result it actually indexed, not a re-scan.

    No membership side effect: /resume is what lands a workspace in the
    opener's index as a participant; these reads are read-only and add
    nothing.
    """
    _username, _token = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    if get_workspace(ws_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    path = get_workspace_dir(ws_id) / "cache" / "file_tree.json"
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail=("This workspace has no stored file tree yet — "
                    "the creator needs to open it once"))
    try:
        tree = json.loads(path.read_text())
    except Exception:
        # corrupt cache — never 500; indistinguishable from "no tree" to a
        # reader, so the same 409 applies.
        raise HTTPException(
            status_code=409,
            detail=("This workspace has no stored file tree yet — "
                    "the creator needs to open it once"))
    return tree


@router.get("/workspace/{ws_id}/index")
def get_workspace_index(request: Request, ws_id: str):
    """Serve the persisted index (cache/table_index.json + field_index.json)
    plus the derived index report (cache/index_report.json).

    #380 (AD2-A): participants read the index instead of triggering a
    re-index. A missing or corrupt index cache reads as {} — never 500 (the
    same convention as /autocomplete); a workspace that was never indexed
    simply reports `indexed.indexed: false` with empty indexes. The report
    fields (resolution_stats, schema_candidates_summary, schema_evidence, …)
    come from index_report.json so a participant's ResolutionReport is not
    blank.

    E4 (item 2): plain `def`, not `async def` — index JSON is large; the
    parse runs in the threadpool, not on the event loop (matches
    /autocomplete and the #380-era convention).
    """
    _username, _token = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    if get_workspace(ws_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    cache_dir = get_workspace_dir(ws_id) / "cache"

    def _read_json(name: str):
        path = cache_dir / name
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except Exception:
            return {}  # corrupt index cache — never 500
        return data if isinstance(data, dict) else {}

    body = {
        "table_index": _read_json("table_index.json"),
        "field_index": _read_json("field_index.json"),
        "indexed": get_index_status(ws_id),
    }
    for key in _INDEX_REPORT_KEYS:
        value = _read_json("index_report.json").get(key)
        if value is not None:
            body[key] = value
    return body


@router.post("/workspace/{ws_id}/close")
async def close_workspace(request: Request, ws_id: str):
    """R31 (#285): per-user visit logging is dropped, so closing a workspace
    is a no-op. The endpoint is KEPT (returns 200) because the frontend calls
    api.closeWorkspace on unmount — no frontend change required."""
    return {"closed": True}


@router.get("/workspace/{ws_id}/activity")
async def get_activity(request: Request, ws_id: str):
    """R31: read the workspace's history (name + IP + ts + action)."""
    username, _ = _session_ctx(request)
    if not is_valid_ws_id(ws_id):
        raise HTTPException(status_code=400, detail="Invalid workspace id")
    if get_workspace(ws_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"activity": read_activity(ws_id)}


@router.post("/workspace/{ws_id}/scan")
def scan_workspace(request: Request, ws_id: str):
    """Scan workspace directory, return file tree.

    E4 (item 2): plain `def`, not `async def` — scan_folder walks the tree
    and parses every .sql file (blocking I/O + CPU); it must run in
    FastAPI's threadpool, never on the event loop (mirrors index_workspace).

    #380 (user ruling 2026-08-28): creator-only, same rule as layout /
    filter-config (#272) — a scan rewrites shared workspace state, and
    read-only participants must not trigger it."""
    username, token = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may rescan the workspace")
    return scan_folder(ws_id)


@router.post("/workspace/{ws_id}/index")
def index_workspace(request: Request, ws_id: str, body: dict):
    """Index the ENTIRE workspace — the index is ALWAYS the complete
    workspace index, never a caller-supplied subset.

    #380 (user ruling 2026-08-28): creator-only — indexing rewrites the
    shared caches (table_index / analysis_*), so participants get 403.

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
    # #380 (user ruling 2026-08-28): creator-only — indexing rewrites the
    # shared caches (table_index / analysis_*), so participants get 403
    # (same rule as layout / filter-config, #272).
    username, token = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may re-index the workspace")

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
async def upload_filter_config(request: Request, ws_id: str,
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
    username, _ = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only mutation — only the workspace creator may
    # update the filter config (non-creator session → 403).
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may update the filter config")
    return await apply_filter_config(ws_id, script_table, table_col, push=_push)


@router.get("/workspace/{ws_id}/export-config")
async def get_export_config_endpoint(ws_id: str):
    """Get current SQL export config (or defaults if none uploaded)."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return get_export_config(ws_id)


@router.put("/workspace/{ws_id}/export-config")
async def update_export_config(request: Request, ws_id: str, body: dict):
    """Save SQL export config. Body: partial or full config dict."""
    username, _ = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only mutation — only the workspace creator may
    # update the export config (non-creator session → 403).
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may update the export config")
    config = save_export_config(ws_id, body)
    return config


@router.delete("/workspace/{ws_id}/export-config")
async def delete_export_config(request: Request, ws_id: str):
    """Reset SQL export config to defaults."""
    username, _ = _session_ctx(request)
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # R31 (#272): creator-only mutation — only the workspace creator may
    # reset the export config (non-creator session → 403).
    if ws.get("creator_username") != username:
        raise HTTPException(status_code=403,
                            detail="Only the workspace creator may reset the export config")
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
