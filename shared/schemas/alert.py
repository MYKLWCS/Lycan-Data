from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel
from shared.constants import AlertSeverity, AlertType


class AlertResponse(BaseModel):
    id: uuid.UUID
    web_id: uuid.UUID | None
    person_id: uuid.UUID | None
    alert_type: str
    severity: str
    title: str
    body: str | None
    payload: dict
    is_read: bool
    is_sent: bool
    sent_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
