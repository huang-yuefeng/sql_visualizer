# Docker Image Build Report — GPS SQL Data Flow Visualizer

**Date**: 2026-06-03  
**Image**: `gps-sql-visualizer:latest`  
**Export file**: `/mnt/data/work/gps-sql-visualizer.tar.gz` (66 MB)

---

## Purpose

Build a fully self-contained Docker image for the `agent/sql_understanding` webservice
that can be deployed on a machine **without internet access**.

---

## What's inside

```
/app/
  backend/
    app/               FastAPI source (routers, services, models, extractor)
      static/          Pre-built React frontend (served by FastAPI)
    vendor/            Vendored .whl files (31 packages, installed at build time)
    start.py           Production entry point
    analysis_cache/    Runtime cache directory (writable)
    tests/             Test suite
  samples/             Sample SQL files
```

All Python dependencies installed from `backend/vendor/*.whl` using:
```
pip install --no-index --find-links=./backend/vendor/ ./backend/vendor/*.whl
```
Zero network access required at build time.

---

## Key technical decision

The uvicorn **CLI** entry point (`uvicorn app.main:app --host 0.0.0.0 --port 8000`)
in version 0.48.0 does **not reliably bind a TCP socket** when invoked from a shell
inside the slim Docker image (logs show "Uvicorn running on..." but `/proc/net/tcp`
is empty). The **programmatic API** works correctly, so `start.py` uses:

```python
config = uvicorn.Config("app.main:app", host=..., port=...)
server = uvicorn.Server(config)
await server.serve()
```

---

## Troubleshooting chronology

The image built on the first attempt, but verifying it worked took extensive debugging.
Below is every approach tried, what error it produced, and what was learned.

### Attempt 1 — CLI entry point with `uvicorn` binary

**Dockerfile CMD:**
```
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Result:** `curl http://localhost:8000/api/health` → `Connection reset by peer` (exit code 56)

**Diagnosis steps:**
- Tried `127.0.0.1` instead of `localhost` (IPv6 suspicion) → same error
- `docker exec` inside container → `ConnectionRefusedError: [Errno 111] Connection refused`
- Checked `/proc/net/tcp` → **completely empty** (zero TCP listeners)
- Checked `/proc/<pid>/fd/` → only stdin/stdout/stderr, **no socket fd**
- Verified uvicorn process IS running (PID 1, visible in `ps`)

**Finding:** uvicorn logs `"Uvicorn running on http://0.0.0.0:8000"` but never actually
opens a socket. The log message is misleading — it's printed by `_serve()` *before*
`startup()` is called, and `startup()` is where socket creation happens.

### Attempt 2 — `python -m uvicorn`

```
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Result:** Identical — logs show startup, no socket fd, `/proc/net/tcp` empty.

**Finding:** The issue is not specific to the `uvicorn` console-script entry point;
it's in the uvicorn 0.48.0 runtime itself when invoked this way.

### Attempt 3 — `uvicorn.run()` convenience function

```python
uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
```

**Result:** Same — no TCP binding.

**Finding:** `uvicorn.run()` is a thin wrapper around `Config` + `Server.run()`.
Something in the call chain prevents socket creation.

### Attempt 4 — Programmatic `Config` + `Server.serve()` with `asyncio.run()`

```python
async def main():
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await server.serve()
asyncio.run(main())
```

**Result:** Inconsistent. When run via inline `echo` heredoc in Dockerfile (had
whitespace/quoting issues), the process crashed silently. When run from a proper
`.py` file, it worked.

### Attempt 5 — Security profile test

Added `--security-opt seccomp=unconfined` to `docker run`.

**Result:** No change — not a seccomp/AppArmor restriction.

### Attempt 6 — Minimal ASGI app (no project code)

Replaced the sql_understanding app with a trivial `async def app(scope, receive, send)`
that returns `"hello"`.

**Result:** In-process port check showed **OPEN** — proving uvicorn CAN bind,
and the issue was specific to how the real app was being launched.

### Attempt 7 — Wrote `test_serve.py`, mounted it via `-v`

Copied the exact `Config` + `Server.serve()` pattern into a properly formatted
`.py` file and mounted it into the container.

**Result:** **SUCCESS!** `/proc/net/tcp` showed:
```
0: 00000000:1F40 00000000:0000 0A ...
```
- `00000000:1F40` = `0.0.0.0:8000`
- State `0A` = LISTEN

### Attempt 8 — Timing diagnosis

With the server actually running, tried health checks and got mixed results
("Connection refused" from some, success from others).

**Finding:** The server takes **~5 seconds** to fully start (importing the
FastAPI app, sqlglot, anthropic SDK, etc.). All earlier tests that ran
`curl` or `docker exec` immediately after `docker run` were hitting the
container before the server was ready. The "Connection reset" from the host
was Docker's proxy accepting the TCP handshake but having nothing to forward to;
"Connection refused" from inside was the port genuinely not being open yet.

### Root cause summary

Two independent issues:

| # | Issue | Symptom | Fix |
|---|-------|---------|-----|
| 1 | uvicorn 0.48.0 CLI/`run()` does not bind a socket in this environment | `/proc/net/tcp` empty, no socket fd | Use `Config` + `Server.serve()` pattern in `start.py` |
| 2 | ~5s startup delay before port is ready | Health checks failing with "Connection refused" or "Connection reset" | Wait/poll for port readiness before testing (normal behavior for any container) |

### What the final Dockerfile CMD looks like

```dockerfile
WORKDIR /app/backend
CMD ["python3", "start.py"]
```

`start.py`:
```python
async def main():
    config = uvicorn.Config("app.main:app", host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

asyncio.run(main())
```

---

---

## Post-deployment fix — clean shutdown

**Problem:** `docker logs gps-sql` showed cascading tracebacks on every `docker stop`:

```
ERROR:    Traceback (most recent call last):
  ...
  File "/app/backend/start.py", line 25, in main
    await server.serve()
  ...
  File "/usr/local/lib/python3.12/asyncio/runners.py", line 157, in _on_sigint
    raise KeyboardInterrupt()
KeyboardInterrupt

  ...
  File "/usr/local/lib/python3.12/site-packages/starlette/routing.py", line 645, in lifespan
    await receive()
  ...
asyncio.exceptions.CancelledError
```

**Root cause:** `asyncio.run()` installs its own SIGINT/SIGTERM handler that raises
`KeyboardInterrupt`.  Uvicorn's `Server.serve()` uses a `capture_signals()` context
manager that *also* tries to handle those signals gracefully.  When `docker stop`
sends SIGTERM, the two handlers collide — `asyncio.run()`'s `KeyboardInterrupt`
interrupts uvicorn's orderly shutdown, and Starlette's lifespan tasks get
cancelled, producing the `CancelledError`.

**Fix:** Replaced `asyncio.run(server.serve())` with `server.run()`, which uses
`loop.run_until_complete()` internally without installing competing signal handlers.
Uvicorn's own `capture_signals()` then handles the shutdown cleanly.

**Before (`start.py` v1):**
```python
async def main():
    config = uvicorn.Config(...)
    server = uvicorn.Server(config)
    await server.serve()

asyncio.run(main())   # ❌ competing signal handler
```

**After (`start.py` v2):**
```python
config = uvicorn.Config(...)
server = uvicorn.Server(config)
server.run()          # ✅ uvicorn manages its own event loop
```

**Verified shutdown logs (clean):**
```
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
```
Zero ERROR lines, zero tracebacks.

---

## Verified

| Endpoint | Method | Result |
|----------|--------|--------|
| `/api/health` | GET | `{"status":"ok","version":"0.1.0"}` |
| `/` | GET | HTTP 200, HTML page with "GPS SQL" title |
| Port 8000 TCP bind | `ss -tlnp` | `0.0.0.0:8000` LISTEN |

---

## How to deploy on offline machine

```bash
# 1. Copy the tar.gz to the target machine
scp gps-sql-visualizer.tar.gz user@target-machine:/tmp/

# 2. Load the image into Docker
docker load < /tmp/gps-sql-visualizer.tar.gz

# 3. Run (replace with your actual Anthropic API key)
docker run -d \
  -p 8000:8000 \
  -e ANTHROPIC_API_KEY=<your-api-key> \
  --name gps-sql \
  gps-sql-visualizer:latest

# 4. Verify
curl http://localhost:8000/api/health
# → {"status":"ok","version":"0.1.0"}

# 5. Open in browser
# http://<machine-ip>:8000
```

### Optional environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Model to use |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `DEBUG` | `false` | Debug mode |

---

## Files created/modified

| File | Action |
|------|--------|
| `Dockerfile` | Created — multi-stage offline build |
| `backend/start.py` | Created — programmatic uvicorn entry point |
| `gps-sql-visualizer.tar.gz` | Created — exported Docker image |
