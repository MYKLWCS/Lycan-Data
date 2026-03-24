"""WebSocket endpoint for real-time scrape progress."""
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
