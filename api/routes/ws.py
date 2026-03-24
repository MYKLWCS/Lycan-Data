"""WebSocket endpoint for real-time scrape progress."""
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.events import event_bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/progress/{person_id}")
async def scrape_progress(websocket: WebSocket, person_id: str):
    """
    Subscribe to real-time progress for a person's scrape jobs.
    Client receives JSON messages as scrapers complete.

    Message format:
    {
        "event": "crawl_complete",
        "platform": "instagram",
        "found": true,
        "person_id": "...",
        "timestamp": "..."
    }
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for person {person_id}")

    try:
        # Subscribe to the enrichment channel and forward relevant events
        async def _handler(message: dict):
            if message.get("person_id") == person_id:
                await websocket.send_json(message)

        # Use a task to subscribe — this is a blocking loop
        sub_task = asyncio.create_task(
            event_bus.subscribe("enrichment", _handler)
        )

        # Keep alive — wait for client disconnect
        try:
            while True:
                # Ping every 30s to keep connection alive
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
        except asyncio.TimeoutError:
            await websocket.send_json({"event": "ping"})
        except WebSocketDisconnect:
            pass
        finally:
            sub_task.cancel()
            try:
                await sub_task
            except asyncio.CancelledError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"WebSocket error for {person_id}: {exc}")
    finally:
        logger.info(f"WebSocket disconnected for person {person_id}")
