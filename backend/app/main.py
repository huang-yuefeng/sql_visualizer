"""FastAPI application entry point.

In production, the built frontend (backend/app/static/) is served directly
by the FastAPI app — no Node.js needed at runtime.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS, DEBUG, CACHE_DIR

STATIC_DIR = Path(__file__).resolve().parent / "static"
VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"

def _read_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "0.0.0"


def purge_workspace_caches(root: Path | None = None) -> int:
    """J12-8 (user ruling 2026-08-11): restart-time cache purge.

    Removes ALL rebuildable cache files under every workspace's cache dir —
    graph_*.json, analysis_*.json, schemas_*.json. Runs on every process
    start: the service does not promise to keep user data; caches exist
    only to save rebuild time, and redoing the calculation after a restart
    is accepted. No version marker, no gating; the existing
    format_version/extractor_version stamps remain the read-time backstop
    for anything that slips through between restarts.

    Never touches views.json (user-created views are data, not cache) and
    never user scripts/samples. Index caches (pair_index/table_index/
    field_index/orphan_fields) are out of scope per the ruling.

    Dev note: the dev compose runs uvicorn --reload (docker-compose.yml),
    which re-runs the lifespan on every code save → purge on every dev
    save. Accepted by the ruling (dev workspaces are small, caches rebuild
    lazily on the next request); production (release.sh image) has no
    reload, so it purges exactly on restarts/deploys as intended.

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # J12-8: every process start wipes the rebuildable workspace caches —
    # stale/corrupt cache carriers were the only source of a served
    # highlight_line: 0 (the hl=0 item); purging at restart removes that
    # source entirely.
    purged = purge_workspace_caches()
    if purged:
        logging.getLogger("uvicorn").info(
            f"Purged {purged} workspace cache file(s) on startup")
    # Auto-cleanup old workspace data (>24h)
    from app.services.workspace_service import cleanup_old_workspaces
    removed = cleanup_old_workspaces(24)
    if removed:
        logging.getLogger("uvicorn").info(f"Cleaned up {removed} old workspace(s)")
    yield



app = FastAPI(
    title="GPS SQL Data Flow Visualizer",
    description="Extract, classify, and visualize variables from GPS financial SQL scripts",
    version=_read_version(),
    lifespan=lifespan,
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


# Import and register routers
from app.routers import analysis, graph, variables, workspace, dataflow, logs  # noqa: E402

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
