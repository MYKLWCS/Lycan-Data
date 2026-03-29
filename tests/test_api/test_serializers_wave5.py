"""
test_serializers_wave5.py — Coverage gap tests for api/serializers.py.

Targets:
  - Line 15: out[col.name] = None when val is None
  - Line 17: out[col.name] = val.isoformat() when val has isoformat (datetime)
"""

from __future__ import annotations

import uuid
from datetime import timezone, date, datetime
from unittest.mock import MagicMock

import pytest

from api.serializers import _model_to_dict

# ---------------------------------------------------------------------------
# Minimal SQLAlchemy-like model fake that provides __table__.columns
# ---------------------------------------------------------------------------


def _make_col(name: str) -> MagicMock:
    col = MagicMock()
    col.name = name
    return col


def _make_model(cols_and_values: dict) -> MagicMock:
    """Build a fake ORM instance whose __table__.columns yields named columns."""
    obj = MagicMock()
    columns = [_make_col(name) for name in cols_and_values]
    obj.__table__ = MagicMock()
    obj.__table__.columns = columns
    for name, val in cols_and_values.items():
        setattr(obj, name, val)
    return obj


# ---------------------------------------------------------------------------
# Line 15: val is None → out[col.name] = None
# ---------------------------------------------------------------------------


def test_model_to_dict_none_value_serialized_as_none():
    """When a column value is None, _model_to_dict must store None (line 15)."""
    obj = _make_model({"full_name": None, "score": 0.5})
    result = _model_to_dict(obj)
    assert result["full_name"] is None
    assert result["score"] == 0.5


def test_model_to_dict_all_none_values():
    """All-None model: every key maps to None."""
    obj = _make_model({"a": None, "b": None})
    result = _model_to_dict(obj)
    assert result == {"a": None, "b": None}


# ---------------------------------------------------------------------------
# Line 17: val has isoformat → out[col.name] = val.isoformat()
# ---------------------------------------------------------------------------


def test_model_to_dict_datetime_value_serialized_via_isoformat():
    """When val has .isoformat(), _model_to_dict calls it (line 17)."""
    dt = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    obj = _make_model({"created_at": dt, "name": "Alice"})
    result = _model_to_dict(obj)
    assert isinstance(result["created_at"], str)
    assert "2025-06-15" in result["created_at"]
    assert result["name"] == "Alice"


def test_model_to_dict_date_value_serialized_via_isoformat():
    """date objects also have .isoformat() — line 17 also covers Python date."""
    d = date(2024, 3, 20)
    obj = _make_model({"dob": d})
    result = _model_to_dict(obj)
    assert result["dob"] == "2024-03-20"


def test_model_to_dict_uuid_serialized_as_str():
    """UUID values fall through to isinstance(val, uuid.UUID) branch → str."""
    uid = uuid.uuid4()
    obj = _make_model({"id": uid})
    result = _model_to_dict(obj)
    assert result["id"] == str(uid)


def test_model_to_dict_mixed_columns():
    """Combined: None col + datetime col + UUID col + plain string col."""
    uid = uuid.uuid4()
    dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
    obj = _make_model(
        {
            "id": uid,
            "created_at": dt,
            "full_name": None,
            "score": 0.9,
        }
    )
    result = _model_to_dict(obj)
    assert result["id"] == str(uid)
    assert isinstance(result["created_at"], str)
    assert result["full_name"] is None
    assert result["score"] == 0.9
