"""
Standardized CrawlerResult — Pydantic model that all crawlers produce.

This is the spec-compliant output schema. The legacy dataclass CrawlerResult
in modules/crawlers/result.py is preserved for backward compatibility;
BaseCrawler.crawl() converts legacy results into this standard format.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, UTC
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CrawlerResult(BaseModel):
    """Standard output schema for ALL crawlers (spec 09)."""

    source_name: str
    source_url: str = ""
    source_reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    category: str = ""
    entity_type: str = "person"
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    normalized_data: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    data_hash: str = ""
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Backward-compat fields from legacy CrawlerResult
    platform: Optional[str] = None
    identifier: Optional[str] = None
    found: bool = False
    error: Optional[str] = None

    @staticmethod
    def hash_data(data: Dict[str, Any]) -> str:
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
