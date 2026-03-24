"""Shared serialisation helpers for API route modules."""
import dataclasses
import uuid
from datetime import datetime
from typing import Any


def _model_to_dict(obj) -> dict:
    """Convert a SQLAlchemy ORM model instance to a plain dict."""
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if val is None:
            out[col.name] = None
        elif hasattr(val, "isoformat"):
            out[col.name] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            out[col.name] = str(val)
        else:
            out[col.name] = val
    return out


def _serialize_datetimes(obj):
    """Recursively convert datetime objects to ISO strings within dicts/lists."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_datetimes(i) for i in obj]
    return obj


def _safe_asdict(dc) -> dict:
    """Convert a dataclass to dict, serialising datetime fields."""
    raw = dataclasses.asdict(dc)
    return _serialize_datetimes(raw)


def _serialize(obj: Any) -> Any:
    """Recursively make dicts/lists/datetimes/dataclasses JSON-safe."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _serialize(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    return obj
