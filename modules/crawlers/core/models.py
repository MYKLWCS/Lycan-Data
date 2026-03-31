"""
Shared enums and models used across the crawler framework.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class CrawlerCategory(str, Enum):
    PEOPLE = "people"
    SOCIAL_MEDIA = "social_media"
    PUBLIC_RECORDS = "public_records"
    FINANCIAL = "financial"
    BUSINESS = "business"
    DARK_WEB = "dark_web"
    PHONE_EMAIL = "phone_email"
    PROPERTY = "property"
    VEHICLE = "vehicle"
    IDENTITY = "identity"
    SANCTIONS_AML = "sanctions_aml"
    NEWS_MEDIA = "news_media"
    GEOSPATIAL = "geospatial"
    CYBER = "cyber"
    MONITORING = "monitoring"
    OTHER = "other"


class RateLimit(BaseModel):
    requests_per_second: float = 1.0
    burst_size: int = 5
    cooldown_seconds: float = 0.0


class CrawlerHealth(BaseModel):
    healthy: bool
    last_check: datetime
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    last_error: str | None = None
