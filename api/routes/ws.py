"""WebSocket and SSE endpoints for real-time scrape progress."""
import asyncio
import json
import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from shared.events import event_bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/progress/{person_id}")
async def scrape_progress(websocket: WebSocket, person_id: str):
    """
    Subscribe to real-time progress for a person's scrape jobs.

    Message format:
    {
        "event": "crawl_complete" | "job_started" | "done" | "ping",
        "platform": "instagram",
        "found": true,
        "person_id": "...",
    }
    """
    await websocket.accept()
    logger.info("WebSocket connected for person %s", person_id)

    async def _forward(message: dict) -> None:
        if message.get("person_id") == person_id:
            try:
                await websocket.send_json(message)
            except Exception:
                pass

    sub_task = asyncio.create_task(
        event_bus.subscribe("enrichment", _forward),
        name=f"ws-sub-{person_id}",
    )

    # Keepalive: send pings and wait for client disconnect
    try:
        while True:
            try:
                # Wait for a client message or timeout
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
                # Echo pings back (browser keepalive pattern)
                if msg == "ping":
                    await websocket.send_json({"event": "pong"})
            except asyncio.TimeoutError:
                # Send a server-side ping
                try:
                    await websocket.send_json({"event": "ping"})
                except Exception:
                    break  # Client gone
            except WebSocketDisconnect:
                break
    finally:
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass
        logger.info("WebSocket disconnected for person %s", person_id)


@router.get("/sse/progress/{person_id}")
async def sse_progress(person_id: str, request: Request):
    """SSE stream for real-time scrape progress updates."""

    async def event_stream():
        if not event_bus.is_connected:
            yield f"data: {json.dumps({'event': 'error', 'detail': 'event bus unavailable'})}\n\n"
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def _forward(message: dict) -> None:
            if message.get("person_id") == person_id:
                await queue.put(message)

        sub_task = asyncio.create_task(
            event_bus.subscribe("enrichment", _forward),
            name=f"sse-sub-{person_id}",
        )
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                    if msg.get("event") == "done":
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
        finally:
            sub_task.cancel()
            try:
                await sub_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")
