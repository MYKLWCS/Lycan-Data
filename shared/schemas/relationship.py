from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel


class ScoreBreakdown(BaseModel):
    """Individual signal scores contributing to relationship score."""
    shared_identifiers: float = 0.0
    co_location: float = 0.0
    social_interaction: float = 0.0
    financial_link: float = 0.0
    temporal_correlation: float = 0.0


class RelationshipResponse(BaseModel):
    id: uuid.UUID
    person_a_id: uuid.UUID
    person_b_id: uuid.UUID
    rel_type: str
    score: float
    evidence: dict
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
