"""Progress event models for real-time search tracking via SSE."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    SEARCH_STARTED = "search_started"
    SCRAPER_QUEUED = "scraper_queued"
    SCRAPER_RUNNING = "scraper_running"
    SCRAPER_DONE = "scraper_done"
    SCRAPER_FAILED = "scraper_failed"
    DEDUP_RUNNING = "dedup_running"
    ENRICHMENT_RUNNING = "enrichment_running"
    SEARCH_COMPLETE = "search_complete"
    HEARTBEAT = "heartbeat"


class Phase(str, Enum):
    COLLECTING = "collecting"
    DEDUPLICATING = "deduplicating"
    ENRICHING = "enriching"
    FINALIZING = "finalizing"
    COMPLETE = "complete"


class ProgressEvent(BaseModel):
    """Raw progress event published by workers to the progress channel."""

    search_id: str
    event_type: EventType
    scraper_name: str | None = None
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    results_found: int = 0
    total_scrapers: int = 0
    completed_scrapers: int = 0
    failed_scrapers: int = 0
    current_phase: Phase = Phase.COLLECTING
    estimated_seconds_remaining: float = 0.0
    partial_results: list[dict] | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DiscoveredAccount(BaseModel):
    """An account link discovered by a crawler."""

    platform: str = ""
    url: str | None = None
    handle: str | None = None


class CrawlerProgress(BaseModel):
    """Per-crawler status with discovered accounts."""

    status: str = "queued"  # queued | running | done | failed
    results_found: int = 0
    discovered_accounts: list[DiscoveredAccount] = []


class ProgressState(BaseModel):
    """Aggregated progress state streamed to the frontend via SSE."""

    search_id: str
    current_phase: Phase
    progress_pct: float
    results_found: int
    scrapers_total: int
    scrapers_completed: int
    scrapers_failed: int
    scrapers_running: int
    estimated_seconds_remaining: float
    elapsed_seconds: float
    scraper_statuses: dict[str, str]  # {name: "queued"|"running"|"done"|"failed"}
    all_discovered_accounts: list[DiscoveredAccount] = []
    last_update: datetime
