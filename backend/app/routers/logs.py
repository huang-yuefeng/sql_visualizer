"""SSE endpoint for streaming pipeline logs to frontend."""
import asyncio
import json
import queue as thread_queue

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services.logger import register_queue, unregister_queue

router = APIRouter()


@router.get("/workspace/{ws_id}/logs")
async def stream_logs(ws_id: str):
    """SSE stream of pipeline log messages for a workspace."""
    async def event_generator():
        # L2: register as an active consumer; the finally block unregisters
        # on disconnect (generator close / cancellation) so the queue is
        # auto-removed when the last client leaves.
        q = register_queue(ws_id)  # thread-safe queue.Queue
        loop = asyncio.get_event_loop()
        try:
            # Drain existing messages
            while True:
                try:
                    entry = q.get_nowait()
                    yield f"data: {json.dumps(entry)}\n\n"
                except thread_queue.Empty:
                    break

            # Stream new messages via polling (thread-safe)
            while True:
                try:
                    entry = await loop.run_in_executor(None, lambda: q.get(timeout=1.0))
                    yield f"data: {json.dumps(entry)}\n\n"
                except thread_queue.Empty:
                    # Keepalive ping
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        except Exception:
            pass
        finally:
            unregister_queue(ws_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
