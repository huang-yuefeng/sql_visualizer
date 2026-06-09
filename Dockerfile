# =============================================================================
# GPS SQL Data Flow Visualizer — fully offline Docker image
#
# Build:   docker build -t gps-sql-visualizer .
# Run:     docker run -p 8000:8000 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY gps-sql-visualizer
#
# All Python dependencies are installed from vendored wheels — no PyPI access
# is required at build time, and no Node.js is needed at runtime (the frontend
# is pre-built static assets served directly by FastAPI).
# =============================================================================

FROM python:3.12-slim

# -- Project layout inside the container ----------------------------------
# /app/
#   backend/
#     app/            <-- FastAPI source
#       static/       <-- built frontend (served by FastAPI in production)
#     vendor/         <-- vendored wheels (used at build time, not at runtime)
#     analysis_cache/ <-- created at build, writable at runtime
#     tests/          <-- available but not run at startup
#   samples/          <-- sample SQL files

WORKDIR /app

# -------------------------------------------------------------------
# 1. Install Python dependencies entirely from vendored wheels (no network)
# -------------------------------------------------------------------
COPY backend/vendor/ ./backend/vendor/
RUN pip install --no-index --find-links=./backend/vendor/ ./backend/vendor/*.whl

# -------------------------------------------------------------------
# 2. Copy backend source code
# -------------------------------------------------------------------
COPY backend/app/         ./backend/app/
COPY backend/tests/       ./backend/tests/

# -------------------------------------------------------------------
# 3. Pre-built frontend is already at backend/app/static/
#    (included by the backend source COPY above — no separate copy needed)
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# 4. Copy sample SQL files (optional, useful for demos)
# -------------------------------------------------------------------
COPY samples/             ./samples/

# -------------------------------------------------------------------
# 5. Create writable cache directory
# -------------------------------------------------------------------
RUN mkdir -p /app/backend/analysis_cache && chmod 777 /app/backend/analysis_cache

# -------------------------------------------------------------------
# 6. Startup script (uses uvicorn.Server programmatic API — the CLI
#    entry point in uvicorn 0.48.0 does not bind a socket reliably)
# -------------------------------------------------------------------
COPY backend/start.py      ./backend/start.py

# -------------------------------------------------------------------
# 7. Runtime configuration
# -------------------------------------------------------------------
EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEBUG=false

WORKDIR /app/backend
CMD ["python3", "start.py"]
