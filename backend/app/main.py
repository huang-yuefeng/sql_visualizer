"""FastAPI application entry point.

In production, the built frontend (backend/app/static/) is served directly
by the FastAPI app — no Node.js needed at runtime.
"""

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Auto-cleanup old workspace data (>24h)
    from app.services.workspace_service import cleanup_old_workspaces
    removed = cleanup_old_workspaces(24)
    if removed:
        import logging
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
