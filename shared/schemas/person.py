from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class PersonSummary(BaseModel):
    """Minimal person representation for lists and graph nodes."""

    id: uuid.UUID
    full_name: str | None
    relationship_score: float
    default_risk_score: float
    darkweb_exposure: float
    composite_quality: float

    model_config = {"from_attributes": True}


class PersonResponse(BaseModel):
    """Full person dossier response."""

    id: uuid.UUID
    full_name: str | None
    date_of_birth: date | None
    gender: str | None
    nationality: str | None
    bio: str | None
    profile_image_url: str | None
    relationship_score: float
    behavioural_risk: float
    darkweb_exposure: float
    default_risk_score: float
    composite_quality: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
