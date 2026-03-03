"""WebSocket endpoint for real-time Centurion event streaming."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from centurion.core.engine import Centurion


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream engine events over a WebSocket connection.

    Route: ``/api/centurion/events``

    The client receives JSON-encoded :class:`CenturionEvent` objects as they
    are emitted by the engine's event bus.
    """
    await websocket.accept()

    engine: Centurion = websocket.app.state.centurion
    queue = engine.event_bus.subscribe()

    try:
        while True:
            event = await queue.get()
            await websocket.send_text(event.to_json())
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        engine.event_bus.unsubscribe(queue)
