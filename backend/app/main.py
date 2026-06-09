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
from app.routers import analysis, graph, variables  # noqa: E402

app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(graph.router, prefix="/api", tags=["graph"])
app.include_router(variables.router, prefix="/api", tags=["variables"])

# Serve the built frontend as static files (production mode).
# In dev, use `npm run dev` for hot-reload; this is for offline/deploy use.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
