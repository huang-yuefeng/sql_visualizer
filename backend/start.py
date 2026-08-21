"""Production entry point — uses uvicorn.Server API directly.

The uvicorn 0.48.0 CLI entry point (``uvicorn app.main:app ...``) does not
reliably bind a TCP socket when invoked via a shell inside the slim Docker
image.  The programmatic path works correctly, so we explicitly construct a
``Config`` and run the server here.

We use ``server.run()`` rather than ``asyncio.run(server.serve())`` because
``asyncio.run()`` installs its own SIGINT/SIGTERM handler that raises
``KeyboardInterrupt``, which conflicts with uvicorn's built-in
``capture_signals()`` context manager.  The result on ``docker stop`` is
cascading ``KeyboardInterrupt`` + ``CancelledError`` tracebacks instead of a
clean shutdown.  ``server.run()`` manages the event loop internally without
the competing handler.
"""

import os
import uvicorn

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    # R31/A-M7: production enables the login gate. start.py IS the production
    # entry (Dockerfile CMD `python3 -u start.py`); the dev container uses
    # Dockerfile.dev's `uvicorn --reload`, which never runs this file, so the
    # gate stays OFF in dev. The env var is read at app.config import, which
    # happens when uvicorn loads `app.main:app` below — set it first. An
    # explicit REQUIRE_LOGIN=0/1 in the run environment still wins (setdefault).
    os.environ.setdefault("REQUIRE_LOGIN", "true")

    # R31/A-M8: pin ONE worker. The in-memory session/visit stores
    # (auth_service) and the login gate assume a single process; multiple
    # workers would give each its own session table and split the audit
    # log consumers. workers=1 keeps the config explicit even though it is
    # also the default.
    config = uvicorn.Config(
        "app.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        workers=1,
    )
    server = uvicorn.Server(config)
    server.run()
