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
    config = uvicorn.Config(
        "app.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()
