"""FastAPI application entry point.

In production, the built frontend (backend/app/static/) is served directly
by the FastAPI app — no Node.js needed at runtime.
"""

import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS, DEBUG, CACHE_DIR, PROVISIONED_USERS

STATIC_DIR = Path(__file__).resolve().parent / "static"
VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"

# J12-8: the purge gate's marker file, kept in the workspace volume so it
# survives container recreation (named volume workspace_data at
# /tmp/workspaces). A dotfile: workspace enumeration (create/cleanup/
# purge) only descends into directories, so the marker is never mistaken
# for a workspace nor swept by the age-based cleanup.
_PURGE_MARKER_NAME = ".cache_purge_marker"


def _read_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "0.0.0"


def _process_start_identity() -> str:
    """Identity of this process start, for the J12-8 purge gate.

    ``hostname | pid-of-process-1 | pid-1 starttime`` — the starttime is
    field 22 of /proc/1/stat (clock ticks since boot). The pid NUMBER of
    process 1 is always 1 inside a container, so the starttime carries the
    instance identity: docker restart / new deploy spawn a NEW pid-1
    process (starttime differs); uvicorn --reload keeps pid 1 — the
    reloader parent — alive across code-save reloads (starttime
    unchanged). Verified 2026-08-11 in the dev container (uvicorn 0.51
    --reload): pid-1 starttime stable across a StatReload, new after
    docker restart. Fallback on platforms without /proc/1 (no reloader
    there): the app's own pid — every process start there is a real
    start.
    """
    try:
        stat = Path("/proc/1/stat").read_text()
        starttime = stat.rsplit(")", 1)[-1].split()[19]
        return f"{socket.gethostname()}|1|{starttime}"
    except Exception:
        try:
            return f"{socket.gethostname()}|{os.getpid()}"
        except Exception:
            return ""


def purge_workspace_caches(root: Path | None = None) -> int:
    """J12-8 (user ruling 2026-08-11): restart-time cache purge — the
    deletion core (called by purge_workspace_caches_if_new_process).

    Removes ALL rebuildable cache files under every workspace's cache dir —
    graph_*.json, analysis_*.json, schemas_*.json. The service does not
    promise to keep user data; caches exist only to save rebuild time, and
    redoing the calculation after a restart is accepted. The existing
    format_version/extractor_version stamps remain the read-time backstop
    for anything that slips through between restarts.

    Never touches views.json (user-created views are data, not cache) and
    never user scripts/samples. Index caches (pair_index/table_index/
    field_index/orphan_fields) are out of scope per the ruling.

    Returns the number of files removed.
    """
    from app.services.workspace_service import WORKSPACE_ROOT
    if root is None:
        root = WORKSPACE_ROOT
    removed = 0
    if not root.is_dir():
        return 0
    for ws_dir in root.iterdir():
        cache_dir = ws_dir / "cache"
        if not cache_dir.is_dir():
            continue
        for pattern in ("graph_*.json", "analysis_*.json", "schemas_*.json"):
            for path in cache_dir.glob(pattern):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    logging.getLogger("uvicorn").warning(
                        "Cache purge: could not remove %s", path)
    return removed


def purge_workspace_caches_if_new_process(root: Path | None = None) -> int:
    """J12-8 gate: purge the rebuildable caches only on a real container
    start, never on a uvicorn --reload code-save restart.

    A marker file in the workspace volume records the pid-1 identity of
    the process start that last purged; only a DIFFERENT identity purges:
    docker restart / deploy = new pid-1 process → marker differs → purge
    (the marker is then rewritten). A code-save reload keeps pid 1 (the
    reloader parent) → marker same → no purge. Without this guard the dev
    container's --reload would wipe every cache on every file save (each
    save re-runs the lifespan; verified 2026-08-11 — StatReload re-runs
    the lifespan with pid-1 starttime unchanged).

    A missing marker (first start after this guard is deployed) purges and
    writes the marker. Returns the number of files removed.
    """
    from app.services.workspace_service import WORKSPACE_ROOT
    if root is None:
        root = WORKSPACE_ROOT
    marker = root / _PURGE_MARKER_NAME
    identity = _process_start_identity()
    if not identity:
        # No usable process-start identity (exotic platform) — skip both
        # the purge and the marker write (an empty marker would match
        # itself and disable all future purges). The format_version/
        # extractor_version stamps remain the read-time backstop.
        return 0
    try:
        if marker.is_file() and marker.read_text().strip() == identity:
            return 0  # same pid-1 start → a reload, not a container start
    except OSError:
        pass
    removed = purge_workspace_caches(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(identity)
    except OSError:
        logging.getLogger("uvicorn").warning(
            "Cache purge: could not write marker %s", marker)
    return removed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # J12-8: every container start wipes the rebuildable workspace caches —
    # stale/corrupt cache carriers were the only source of a served
    # highlight_line: 0 (the hl=0 item); purging at restart removes that
    # source entirely. Guarded by the pid-1 marker so uvicorn --reload
    # code-save restarts (same pid 1) do NOT purge.
    purged = purge_workspace_caches_if_new_process()
    if purged:
        logging.getLogger("uvicorn").info(
            f"Purged {purged} workspace cache file(s) on startup")
    # R31: workspaces are durable user data now — the old >24h auto-cleanup
    # is REMOVED (it would destroy shared workspaces). One-time migration at
    # rollout: pre-feature workspaces (no creator_username) are removed
    # directly (user-confirmed, no backup). Runs on every start but is a
    # no-op once no creator-less workspaces remain.
    from app.services.workspace_service import remove_legacy_workspaces
    migrated = remove_legacy_workspaces()
    if migrated:
        logging.getLogger("uvicorn").info(
            f"R31 migration: removed {migrated} legacy workspace(s) without a creator")
    # R31 (#269): the ONLY account-provisioning path — config-driven. Each
    # deploy force-syncs every PROVISIONED_USERS entry (create-or-reset) so
    # accounts/passwords always match config. No HTTP endpoint provisions
    # users anymore (the gate-exempt /api/admin bootstrap was removed —
    # E-H1/E-H3).
    for _username, _password in PROVISIONED_USERS.items():
        auth_service.provision_user(_username, _password, force=True)
    yield



app = FastAPI(
    title="GPS SQL Data Flow Visualizer",
    description="Extract, classify, and visualize variables from GPS financial SQL scripts",
    version=_read_version(),
    lifespan=lifespan,
    # P1: keep /docs, /redoc and /openapi.json private unless DEBUG — the
    # API schema is disabled in production (the SPA is served from /static).
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
    openapi_url="/openapi.json" if DEBUG else None,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": _read_version()}


# R31 login gate (A-M7): when REQUIRE_LOGIN is on, every /api/* endpoint
# except the public prefixes below (health, login, and the #293 SQL-Analysis
# endpoints) requires a valid session cookie;
# state-changing methods also pass a same-origin check (Origin/Referer must
# match the service host). The static frontend stays public — on a 401 the
# SPA renders the login form in the Data Flow Debugger's left panel (#293).
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import REQUIRE_LOGIN
from app.routers.auth import SESSION_COOKIE
from app.services import auth_service

# #293: SQL Analysis is public (login-gate exempt) — the Data Flow Debugger
# is the only part that requires login. /api/health and /api/auth/login have
# always been exempt. There is NO public provisioning endpoint: accounts are
# provisioned from config (PROVISIONED_USERS) at startup only (R31 #269 — the
# /api/admin bootstrap hole was removed, E-H1/E-H3).
PUBLIC_API_PREFIXES = (
    "/api/health",
    "/api/auth/login",
    "/api/analyze",        # SQL Analysis (public — #293)
    "/api/analyze_multi",  # SQL Analysis (public — #293)
    "/api/scripts",        # SQL Analysis (public — #293)
)


def _path_is_public(path: str) -> bool:
    """Boundary-safe public-prefix match.

    A bare `startswith` would let `/api/scriptsx` wrongly match the public
    `/api/scripts`. A path is public only when it EQUALS a prefix or starts
    with ``prefix + "/"``."""
    for p in PUBLIC_API_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return True
    return False


@app.middleware("http")
async def login_gate(request: Request, call_next):
    if REQUIRE_LOGIN:
        path = request.url.path
        if path.startswith("/api/") and not _path_is_public(path):
            token = request.cookies.get(SESSION_COOKIE)
            if auth_service.get_session(token) is None:
                return JSONResponse({"detail": "Not logged in"}, status_code=401)
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                origin = (request.headers.get("origin")
                          or request.headers.get("referer") or "")
                host = request.headers.get("host", "")
                if origin and host:
                    parsed = urlparse(origin)
                    if parsed.hostname and parsed.netloc != host:
                        return JSONResponse(
                            {"detail": "Cross-origin request rejected"},
                            status_code=403)
    return await call_next(request)


# Import and register routers
from app.routers import analysis, graph, variables, workspace, dataflow, logs, auth  # noqa: E402

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(graph.router, prefix="/api", tags=["graph"])
app.include_router(variables.router, prefix="/api", tags=["variables"])
app.include_router(workspace.router, prefix="/api")
app.include_router(dataflow.router, prefix="/api")
app.include_router(logs.router, prefix="/api", tags=["logs"])

# Serve the built frontend as static files (production mode).
# In dev, use `npm run dev` for hot-reload; this is for offline/deploy use.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
