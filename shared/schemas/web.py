from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class WebConfig(BaseModel):
    """Configuration for a web crawl."""

    max_depth: int = 3
    enable_darkweb: bool = True
    enable_social: bool = True
    enable_enrichment: bool = True
    min_relationship_score: float = 0.3


class WebResponse(BaseModel):
    id: uuid.UUID
    name: str
    seed_type: str
    seed_value: str
    status: str
    depth: int
    max_depth: int
    person_count: int
    edge_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
