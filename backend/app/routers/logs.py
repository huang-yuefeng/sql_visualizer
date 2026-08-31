"""SSE endpoint for streaming pipeline logs to frontend."""
import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.logger import ConsumerQueue, register_queue, unregister_queue

router = APIRouter()

# SSE comment ping so idle proxies do not reap a quiet stream. Log lines are
# bursty (a pipeline emits a block, then silence), so the ping doubles as a
# cheap liveness signal for the frontend. 15s sits far inside the usual
# 60s proxy read timeout; the stream no longer needs a 1s ping because it
# no longer polls on that cadence.
_KEEPALIVE_EVERY = 15.0


def _drain_one(q: ConsumerQueue) -> Optional[dict]:
    """Pop one buffered entry, or None when the queue is empty."""
    try:
        return q.get_nowait()
    except Exception:
        return None


@router.get("/workspace/{ws_id}/logs")
async def stream_logs(ws_id: str):
    """SSE stream of pipeline log messages for a workspace.

    MSC-6: every stream registers its OWN queue, so N subscribers on the
    same workspace each get the FULL stream (the old single per-workspace
    queue split it: each pushed line went to exactly one reader).

    The generator waits on a per-consumer asyncio.Event that producer
    threads set via loop.call_soon_threadsafe — no executor thread is held
    while the stream idles (the previous `run_in_executor(q.get)` parked one
    default-executor thread per open stream indefinitely).
    """
    async def event_generator():
        # Register as an active consumer; the finally block unregisters THIS
        # queue on disconnect (generator close / cancellation) so the
        # workspace's fan-out is released when the last client leaves.
        q = register_queue(ws_id, loop=asyncio.get_running_loop())
        last_beat = time.monotonic()
        try:
            while True:
                entry = _drain_one(q)
                if entry is not None:
                    last_beat = time.monotonic()
                    yield f"data: {json.dumps(entry)}\n\n"
                    continue

                # Sleep until the next line OR the next keepalive, whichever
                # comes first — never occupying a thread while waiting.
                delay = _KEEPALIVE_EVERY - (time.monotonic() - last_beat)
                if delay <= 0:
                    last_beat = time.monotonic()
                    yield ": keepalive\n\n"
                    continue
                await q.wait_ready(timeout=delay)
        finally:
            unregister_queue(ws_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
