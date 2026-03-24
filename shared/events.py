import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis
from shared.config import settings

logger = logging.getLogger(__name__)


class EventBus:
    """
    Pub/sub and queue wrapper over Dragonfly (Redis-compatible).

    Channels:
        lycan:crawl_jobs    — new crawl jobs dispatched
        lycan:enrichment    — enrichment tasks
        lycan:alerts        — alert triggers
        lycan:freshness     — freshness check requests
        lycan:graph         — graph update events

    Queues (Redis lists, LPUSH/BRPOP pattern):
        lycan:queue:high    — priority 1-3 jobs
        lycan:queue:normal  — priority 4-7 jobs
        lycan:queue:low     — priority 8-10 jobs
        lycan:queue:ingest  — raw crawler results waiting for DB insertion
        lycan:queue:index   — parsed person states waiting for MeiliSearch
    """

    CHANNELS = {
        "crawl": "lycan:crawl_jobs",
        "enrichment": "lycan:enrichment",
        "alerts": "lycan:alerts",
        "freshness": "lycan:freshness",
        "graph": "lycan:graph",
    }

    QUEUES = {
        "high": "lycan:queue:high",
        "normal": "lycan:queue:normal",
        "low": "lycan:queue:low",
        "ingest": "lycan:queue:ingest",
        "index": "lycan:queue:index",
    }

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.dragonfly_url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        await self._redis.ping()
        logger.info("EventBus connected to Dragonfly at %s", self._url)

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def is_connected(self) -> bool:
        """Return True if the EventBus has an active Redis/Dragonfly connection."""
        return self._redis is not None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("EventBus not connected. Call connect() first.")
        return self._redis

    # --- Pub/Sub ---

    async def publish(self, channel: str, event: dict[str, Any]) -> int:
        """Publish an event. Returns subscriber count."""
        payload = _serialize(event)
        ch = self.CHANNELS.get(channel, channel)
        return await self.redis.publish(ch, payload)

    async def subscribe(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Subscribe to a channel and call handler for each message. Runs until cancelled."""
        ch = self.CHANNELS.get(channel, channel)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(ch)
        logger.info("Subscribed to channel: %s", ch)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = _deserialize(message["data"])
                        await _call(handler, data)
                    except Exception:
                        logger.exception("Error in event handler for channel %s", ch)
        finally:
            await pubsub.unsubscribe(ch)
            await pubsub.aclose()

    # --- Job Queue ---

    async def enqueue(self, job: dict[str, Any], priority: str = "normal") -> None:
        """Push a job to the appropriate priority queue."""
        job.setdefault("enqueued_at", datetime.now(timezone.utc).isoformat())
        queue = self.QUEUES.get(priority, self.QUEUES["normal"])
        await self.redis.lpush(queue, _serialize(job))

    async def dequeue(self, priority: str = "normal", timeout: int = 5) -> dict[str, Any] | None:
        """Pop a job from the queue. Blocks for up to `timeout` seconds."""
        queue = self.QUEUES.get(priority, self.QUEUES["normal"])
        result = await self.redis.brpop([queue], timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return _deserialize(raw)

    async def dequeue_any(self, timeout: int = 5) -> dict[str, Any] | None:
        """Pop from high → normal → low, whichever has a job first."""
        queues = [self.QUEUES["high"], self.QUEUES["normal"], self.QUEUES["low"]]
        result = await self.redis.brpop(queues, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return _deserialize(raw)

    async def queue_length(self, priority: str = "normal") -> int:
        queue = self.QUEUES.get(priority, self.QUEUES["normal"])
        return await self.redis.llen(queue)

    # --- Cache helpers ---

    async def cache_set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        await self.redis.setex(key, ttl_seconds, _serialize(value))

    async def cache_get(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        return _deserialize(raw) if raw else None

    async def cache_delete(self, key: str) -> None:
        await self.redis.delete(key)


def _serialize(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)


def _deserialize(raw: str) -> Any:
    return json.loads(raw)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def _call(handler: Callable, data: Any) -> None:
    if asyncio.iscoroutinefunction(handler):
        await handler(data)
    else:
        handler(data)


@asynccontextmanager
async def get_event_bus() -> AsyncGenerator[EventBus, None]:
    """Context manager that yields a connected EventBus."""
    bus = EventBus()
    await bus.connect()
    try:
        yield bus
    finally:
        await bus.disconnect()


# Module-level singleton (connect explicitly before use)
event_bus = EventBus()
