"""WebSocket and SSE endpoints for real-time scrape progress."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from modules.pipeline.progress_tracker import ProgressAggregator
from shared.config import settings
from shared.events import event_bus
from shared.schemas.progress import EventType

router = APIRouter()
logger = logging.getLogger(__name__)


def _platform_from_meta(meta: object) -> str | None:
    if isinstance(meta, dict):
        platform = meta.get("platform")
        if platform:
            return str(platform)
    return None


def _valid_keys() -> set[str]:
    """Parse API keys from config."""
    raw = settings.api_keys.strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def _validate_stream_token(request: Request, token: str | None = None) -> None:
    """Validate auth for SSE endpoints via Authorization header or ?token= query param."""
    if not settings.api_auth_enabled:
        return
    valid = _valid_keys()
    if not valid:
        raise HTTPException(status_code=503, detail="API keys not configured")
    # Check query param first, then Authorization header
    if token and token in valid:
        return
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] in valid:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")


async def _validate_ws_token(websocket: WebSocket) -> bool:
    """Validate auth for WebSocket via ?token= query param. Returns False if invalid."""
    if not settings.api_auth_enabled:
        return True
    valid = _valid_keys()
    if not valid:
        await websocket.close(code=4001, reason="API keys not configured")
        return False
    token = websocket.query_params.get("token", "")
    if token in valid:
        return True
    await websocket.close(code=4001, reason="Invalid or missing authentication token")
    return False


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

    Auth: pass ?token=<api_key> in the WebSocket URL.
    """
    if not await _validate_ws_token(websocket):
        return
    await websocket.accept()
    logger.info("WebSocket connected for person %s", person_id)

    async def _forward(message: dict) -> None:
        if message.get("person_id") == person_id:
            try:
                await websocket.send_json(message)
            except Exception:
                logger.debug("WebSocket send failed for person %s", person_id, exc_info=True)

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
            except TimeoutError:
                # Send a server-side ping
                try:
                    await websocket.send_json({"event": "ping"})
                except Exception:
                    break  # Client gone
            except WebSocketDisconnect:  # pragma: no cover
                break
    finally:
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass
        logger.info("WebSocket disconnected for person %s", person_id)


@router.get("/sse/progress/{person_id}")
async def sse_progress(person_id: str, request: Request, token: str | None = Query(default=None)):
    """SSE stream for real-time scrape progress updates.

    Auth: pass Authorization: Bearer <key> header or ?token=<key> query param.
    """
    _validate_stream_token(request, token)

    async def event_stream():
        if not event_bus.is_connected:
            yield f"data: {json.dumps({'event': 'error', 'detail': 'event bus unavailable'})}\n\n"
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def _forward(message: dict) -> None:
            if message.get("person_id") == person_id:  # pragma: no branch
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
                    if msg.get("event") == "done":  # pragma: no branch
                        break
                except TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
        finally:
            sub_task.cancel()
            try:
                await sub_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/search/{person_id}/progress")
async def search_progress(
    person_id: str, request: Request, token: str | None = Query(default=None)
):
    """
    SSE stream of rich phase-based progress for a running search.

    Auth: pass Authorization: Bearer <key> header or ?token=<key> query param.

    Events emit a ProgressState JSON payload:
      { search_id, current_phase, progress_pct, results_found,
        scrapers_total, scrapers_completed, scrapers_failed, scrapers_running,
        estimated_seconds_remaining, elapsed_seconds, scraper_statuses }

    Phases: collecting (0-60%) → deduplicating (60-75%) →
            enriching (75-95%) → finalizing (95-100%) → complete
    """
    _validate_stream_token(request, token)

    async def event_stream():
        if not event_bus.is_connected:
            yield f"data: {json.dumps({'event_type': 'error', 'detail': 'event bus unavailable'})}\n\n"
            return

        # Recover scraper count from DB to avoid SEARCH_STARTED race condition
        scraper_count = 1
        scraper_names = []
        try:
            import uuid as _uuid

            from sqlalchemy import func, select

            from shared.db import AsyncSessionLocal
            from shared.models.crawl import CrawlJob

            async with AsyncSessionLocal() as _session:
                _cnt = await _session.execute(
                    select(func.count())
                    .select_from(CrawlJob)
                    .where(CrawlJob.person_id == _uuid.UUID(person_id))
                )
                scraper_count = max(_cnt.scalar() or 1, 1)
                _names = await _session.execute(
                    select(CrawlJob.meta).where(CrawlJob.person_id == _uuid.UUID(person_id))
                )
                scraper_names = [
                    platform for row in _names.all() if (platform := _platform_from_meta(row[0]))
                ]
        except Exception:
            logger.debug("Failed to recover scraper metadata for %s", person_id, exc_info=True)

        aggregator = ProgressAggregator(search_id=person_id, scraper_count=scraper_count)
        for _name in scraper_names:
            aggregator.scraper_statuses[_name] = "queued"

        queue: asyncio.Queue = asyncio.Queue()

        async def _forward(message: dict) -> None:
            if message.get("search_id") == person_id:
                await queue.put(message)

        sub_task = asyncio.create_task(
            event_bus.subscribe("progress", _forward),
            name=f"progress-sse-{person_id}",
        )

        # Emit initial state with correct scraper count
        initial = aggregator.to_state()
        yield f"data: {initial.model_dump_json()}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    raw = await asyncio.wait_for(queue.get(), timeout=20.0)
                    state = aggregator.process(raw)
                    if state:
                        yield f"data: {state.model_dump_json()}\n\n"
                    # Close stream when search is complete
                    if raw.get("event_type") == EventType.SEARCH_COMPLETE:
                        break
                except TimeoutError:
                    # Heartbeat keeps the connection alive
                    state = aggregator.to_state()
                    yield f"data: {state.model_dump_json()}\n\n"
        finally:
            sub_task.cancel()
            try:
                await sub_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{person_id}")
async def search_progress_legacy(
    person_id: str,
    request: Request,
    token: str | None = Query(default=None),
):
    """Backward-compatible alias for older `/ws/{person_id}` clients."""
    return await search_progress(person_id=person_id, request=request, token=token)
