"""A bounded, in-process live stream of decision traces."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
import json
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/v1/graph", tags=["Decision Graph"])


class GraphEvents:
    def __init__(self, capacity: int = 128, heartbeat_seconds: float = 15):
        self._events: deque[tuple[int, str]] = deque(maxlen=capacity)
        self._generation = uuid4().hex
        self._sequence = 0
        self._heartbeat_seconds = heartbeat_seconds
        self._lock = Lock()
        self._listeners: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}

    def publish(self, trace: dict) -> None:
        payload = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._sequence += 1
            self._events.append((self._sequence, payload))
            for event, loop in self._listeners.items():
                if not loop.is_closed():
                    loop.call_soon_threadsafe(event.set)

    async def stream(self, last_id: str | None = None) -> AsyncIterator[str]:
        wakeup = asyncio.Event()
        with self._lock:
            self._listeners[wakeup] = asyncio.get_running_loop()
            cursor = self._sequence
        try:
            if last_id is not None:
                generation, _, position = last_id.partition(":")
                if generation == self._generation and position.isascii() and position.isdigit() and len(position) < 20:
                    position = int(position)
                    if position <= cursor:
                        cursor = position
                    else:
                        yield "id:\nevent: reset\ndata: {}\n\n"
                else:
                    yield "id:\nevent: reset\ndata: {}\n\n"
            yield ": connected\n\n"

            while True:
                with self._lock:
                    wakeup.clear()
                    expired = bool(self._events and cursor < self._events[0][0] - 1)
                    pending = [(seq, data) for seq, data in self._events if seq > cursor]
                if expired:
                    yield "id:\nevent: reset\ndata: {}\n\n"
                if pending:
                    for cursor, payload in pending:
                        yield f"id: {self._generation}:{cursor}\nevent: decision\ndata: {payload}\n\n"
                    continue
                try:
                    await asyncio.wait_for(wakeup.wait(), timeout=self._heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            with self._lock:
                self._listeners.pop(wakeup, None)


@router.get("/events", response_class=StreamingResponse)
async def graph_events(request: Request):
    return StreamingResponse(
        request.app.state.graph_events.stream(request.headers.get("last-event-id")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
