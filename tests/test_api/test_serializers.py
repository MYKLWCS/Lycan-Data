"""Tests for api/serializers.py — pure logic, no DB required."""

import dataclasses
import uuid
from datetime import UTC, datetime

from api.serializers import _safe_asdict, _serialize, _serialize_datetimes


@dataclasses.dataclass
class _SampleDC:
    name: str
    score: float
    created_at: datetime


# ─── _serialize_datetimes ─────────────────────────────────────────────────────


def test_serialize_datetimes_converts_datetime():
    dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    result = _serialize_datetimes(dt)
    assert isinstance(result, str)
    assert "2024-01-15" in result


def test_serialize_datetimes_nested_dict():
    dt = datetime(2024, 1, 15, tzinfo=UTC)
    data = {"created": dt, "name": "Alice"}
    result = _serialize_datetimes(data)
    assert isinstance(result["created"], str)
    assert result["name"] == "Alice"


def test_serialize_datetimes_list():
    dt = datetime(2024, 6, 1, tzinfo=UTC)
    result = _serialize_datetimes([dt, "plain string", 42])
    assert isinstance(result[0], str)
    assert result[1] == "plain string"
    assert result[2] == 42


def test_serialize_datetimes_passthrough_primitives():
    assert _serialize_datetimes(42) == 42
    assert _serialize_datetimes("hello") == "hello"
    assert _serialize_datetimes(None) is None


# ─── _safe_asdict ─────────────────────────────────────────────────────────────


def test_safe_asdict_converts_dataclass():
    dt = datetime(2024, 3, 10, tzinfo=UTC)
    dc = _SampleDC(name="test", score=0.9, created_at=dt)
    result = _safe_asdict(dc)
    assert result["name"] == "test"
    assert result["score"] == 0.9
    assert isinstance(result["created_at"], str)
    assert "2024-03-10" in result["created_at"]


# ─── _serialize ───────────────────────────────────────────────────────────────


def test_serialize_datetime():
    dt = datetime(2024, 1, 15, tzinfo=UTC)
    result = _serialize(dt)
    assert isinstance(result, str)
    assert "2024-01-15" in result


def test_serialize_dataclass():
    dt = datetime(2024, 5, 20, tzinfo=UTC)
    dc = _SampleDC(name="Alice", score=0.75, created_at=dt)
    result = _serialize(dc)
    assert isinstance(result, dict)
    assert result["name"] == "Alice"
    assert isinstance(result["created_at"], str)


def test_serialize_nested_dict():
    dt = datetime(2024, 6, 1, tzinfo=UTC)
    data = {"key": {"nested_date": dt, "value": 42}}
    result = _serialize(data)
    assert isinstance(result["key"]["nested_date"], str)
    assert result["key"]["value"] == 42


def test_serialize_list():
    dt = datetime(2024, 7, 4, tzinfo=UTC)
    result = _serialize([dt, "string", 99])
    assert isinstance(result[0], str)
    assert result[1] == "string"


def test_serialize_passthrough_primitives():
    assert _serialize(42) == 42
    assert _serialize("hello") == "hello"
    assert _serialize(None) is None
    assert _serialize(3.14) == 3.14


def test_serialize_tuple_becomes_list():
    result = _serialize((1, 2, 3))
    assert result == [1, 2, 3]
