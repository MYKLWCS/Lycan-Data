"""Tests for modules/patterns/temporal.py — TemporalPatternAnalyzer.

All DB calls are mocked — no live PostgreSQL required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.patterns.temporal import TemporalPatternAnalyzer


def _mock_session(rows: list[dict]) -> AsyncMock:
    """Build a minimal AsyncSession mock that returns `rows` from any execute."""
    mapping_rows = [MagicMock(**{"__iter__": lambda s: iter(row.items()), **row}) for row in rows]

    mappings_mock = MagicMock()
    mappings_mock.all.return_value = mapping_rows

    result_mock = MagicMock()
    result_mock.mappings.return_value = mappings_mock

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    return session


def _row_as_dict(row):
    """Convert the MagicMock row back to a plain dict for assertions."""
    return dict(row)


# ---------------------------------------------------------------------------
# detect_change_velocity
# ---------------------------------------------------------------------------


async def test_detect_change_velocity_returns_list():
    rows = [{"date": "2024-01-01", "jobs_per_day": 3, "platforms_per_day": 2, "velocity": "LOW"}]
    session = _mock_session(rows)
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.detect_change_velocity("person-uuid-1", session)
    assert isinstance(result, list)
    assert len(result) == 1


async def test_detect_change_velocity_db_error_returns_empty():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB down"))
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.detect_change_velocity("person-uuid-1", session)
    assert result == []


# ---------------------------------------------------------------------------
# find_address_change_patterns
# ---------------------------------------------------------------------------


async def test_find_address_change_patterns_returns_list():
    rows = [
        {
            "person_id": "abc",
            "address_count": 5,
            "distinct_cities": 3,
            "distinct_states": 2,
            "first_seen": "2023-01-01",
            "last_seen": "2024-01-01",
        }
    ]
    session = _mock_session(rows)
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_address_change_patterns(session)
    assert isinstance(result, list)
    assert len(result) == 1


async def test_find_address_change_patterns_db_error_returns_empty():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("timeout"))
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_address_change_patterns(session)
    assert result == []


# ---------------------------------------------------------------------------
# find_identifier_change_patterns
# ---------------------------------------------------------------------------


async def test_find_identifier_change_patterns_returns_list():
    rows = [
        {"person_id": "xyz", "type": "phone", "identifier_count": 4, "distinct_values": 3}
    ]
    session = _mock_session(rows)
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_identifier_change_patterns(session)
    assert isinstance(result, list)
    assert len(result) == 1


async def test_find_identifier_change_patterns_db_error_returns_empty():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("connection refused"))
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_identifier_change_patterns(session)
    assert result == []


# ---------------------------------------------------------------------------
# find_co_occurring_risk_flags
# ---------------------------------------------------------------------------


async def test_find_co_occurring_risk_flags_returns_list():
    rows = [
        {
            "person_id": "p1",
            "full_name": "Alice",
            "watchlist_hits": 1,
            "darkweb_hits": 2,
            "breach_hits": 0,
            "total_flags": 3,
        }
    ]
    session = _mock_session(rows)
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_co_occurring_risk_flags(session)
    assert isinstance(result, list)
    assert len(result) == 1


async def test_find_co_occurring_risk_flags_db_error_returns_empty():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("query failed"))
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_co_occurring_risk_flags(session)
    assert result == []


# ---------------------------------------------------------------------------
# find_network_anomalies
# ---------------------------------------------------------------------------


async def test_find_network_anomalies_returns_list():
    rows = [{"person_id": "p99", "connection_count": 15, "relationship_types": 4}]
    session = _mock_session(rows)
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_network_anomalies(session)
    assert isinstance(result, list)
    assert len(result) == 1


async def test_find_network_anomalies_db_error_returns_empty():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB unavailable"))
    analyzer = TemporalPatternAnalyzer()
    result = await analyzer.find_network_anomalies(session)
    assert result == []
