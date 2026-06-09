# Build & Deploy Guide

## Quick Start (Development)

```bash
# Terminal 1 — Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --no-index --find-links=vendor/ -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend (optional, for hot-reload)
cd frontend
npm install
npm run dev
# → opens http://localhost:5173
```

## Docker Build

### 1. Update version (optional)

```bash
echo "1.26.0" > VERSION
```

### 2. Build frontend (if changed)

```bash
cd frontend
npm install
npx vite build --outDir ../backend/app/static --emptyOutDir
```

### 3. Build Docker image

```bash
docker build -t gps-sql-visualizer .
```

### 4. Run container

```bash
docker run -p 8000:8000 gps-sql-visualizer
```

Open `http://localhost:8000`

### 5. Verify

```bash
curl http://localhost:8000/api/health
# → {"status":"ok","version":"1.25.0"}
```

## File Layout (What Gets Copied Into Docker)

```
VERSION              ← version number (NEW — was missing before)
backend/
  app/               ← FastAPI source + pre-built frontend static/
  tests/             ← test suite
  vendor/            ← Python wheels (build-time only)
  start.py           ← production entry point
samples/             ← SQL test files + TPC-DS + IO CSVs
```

## Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| Version shows `v0.0.0` | `VERSION` file not copied into Docker | Added `COPY VERSION ./VERSION` to Dockerfile |
| Frontend shows old UI | Browser cache or stale Docker image | Ctrl+Shift+R in browser, or `docker build --no-cache` |
| `pip install` fails in Docker | Vendor wheels missing or wrong platform | Re-run `pip download -r requirements.txt -d vendor/` on same platform |
| Port 8000 already in use | Another process using the port | `docker run -p 8001:8000 ...` or kill existing process |
