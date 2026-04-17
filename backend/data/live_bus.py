"""
Live scores event bus.

The scheduler (sync thread) calls notify() after writing new scores to the DB.
The SSE endpoint (async) waits on the event and immediately pushes to all
connected browsers — no fixed polling interval needed.

Flow:
  scheduler writes DB → calls notify() → all SSE connections wake instantly
  If no update in 60s, SSE sends a heartbeat anyway to keep connection alive.
"""
from __future__ import annotations
import asyncio
import threading

# One asyncio Event shared across all SSE connections in the same process.
# The scheduler thread sets it; SSE coroutines await it and then clear it.
_loop: asyncio.AbstractEventLoop | None = None
_event: asyncio.Event | None = None
_lock = threading.Lock()


def _get_or_create() -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
    """Get (or lazily create) the shared loop+event from the main async context."""
    global _loop, _event
    with _lock:
        if _loop is None or _event is None:
            # This is called from the main async process on first use
            try:
                _loop = asyncio.get_event_loop()
            except RuntimeError:
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)
            _event = asyncio.Event()
    return _loop, _event


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once at app startup to register the running event loop."""
    global _loop, _event
    with _lock:
        _loop = loop
        _event = asyncio.Event()


def notify(updated_count: int = 0) -> None:
    """
    Called from the scheduler (sync thread) when live scores are written to DB.
    Signals all waiting SSE coroutines to push immediately.
    """
    global _loop, _event
    if _loop is None or _event is None:
        return
    if updated_count == 0:
        return  # no changes — don't wake SSE connections unnecessarily
    try:
        # Thread-safe: schedule set() on the event loop from a background thread
        _loop.call_soon_threadsafe(_event.set)
    except Exception:
        pass


async def wait_for_update(timeout: float = 60.0) -> bool:
    """
    Await the next score update signal.
    Returns True if scores were updated, False if timeout elapsed (heartbeat).
    SSE endpoint calls this in a loop.
    """
    _, event = _get_or_create()
    try:
        await asyncio.wait_for(asyncio.shield(event.wait()), timeout=timeout)
        event.clear()
        return True
    except asyncio.TimeoutError:
        return False
