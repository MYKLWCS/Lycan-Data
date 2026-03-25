"""
Final wave-4 API/shared coverage tests.

Targets:
  api/routes/export.py:76, 78
  api/serializers.py:15, 17
  api/routes/enrichment.py:55
  shared/data_quality.py:28
  shared/transport_registry.py:83-84
  shared/circuit_breaker.py:123
  modules/dispatcher/growth_daemon.py:122-123
  modules/pipeline/ingestion_daemon.py:99-100
  modules/search/index_daemon.py:76-77
  modules/graph/company_intel.py:222
  modules/graph/entity_graph.py:89
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# api/serializers.py — lines 15, 17
# ===========================================================================


class TestApiSerializers:
    def test_model_to_dict_none_value(self):
        """Line 15: None value → stored as None in dict."""
        from api.serializers import _model_to_dict

        col1 = MagicMock()
        col1.name = "field_a"
        col2 = MagicMock()
        col2.name = "field_b"

        obj = MagicMock()
        obj.__table__ = MagicMock()
        obj.__table__.columns = [col1, col2]
        obj.field_a = None
        obj.field_b = "hello"

        result = _model_to_dict(obj)
        assert result["field_a"] is None
        assert result["field_b"] == "hello"

    def test_model_to_dict_isoformat_value(self):
        """Line 17: datetime value → .isoformat() called."""
        from api.serializers import _model_to_dict

        col = MagicMock()
        col.name = "created_at"

        obj = MagicMock()
        obj.__table__ = MagicMock()
        obj.__table__.columns = [col]
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        obj.created_at = dt

        result = _model_to_dict(obj)
        assert result["created_at"] == dt.isoformat()

    def test_model_to_dict_uuid_value(self):
        """UUID value → str representation."""
        from api.serializers import _model_to_dict

        col = MagicMock()
        col.name = "id"

        obj = MagicMock()
        obj.__table__ = MagicMock()
        obj.__table__.columns = [col]
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        obj.id = uid

        result = _model_to_dict(obj)
        assert result["id"] == str(uid)

    def test_serialize_datetimes_nested(self):
        """_serialize_datetimes handles nested dicts and lists."""
        from api.serializers import _serialize_datetimes

        dt = datetime(2024, 1, 1, tzinfo=UTC)
        data = {
            "created_at": dt,
            "nested": {"ts": dt},
            "items": [dt, "plain_string"],
        }
        result = _serialize_datetimes(data)
        assert result["created_at"] == dt.isoformat()
        assert result["nested"]["ts"] == dt.isoformat()
        assert result["items"][0] == dt.isoformat()
        assert result["items"][1] == "plain_string"


# ===========================================================================
# api/routes/enrichment.py — line 55 (_background_enrich exception handling)
# ===========================================================================


class TestApiEnrichmentLine55:
    @pytest.mark.asyncio
    async def test_background_enrich_exception_rolled_back(self):
        """Line 55-58: exception during enrich → rollback called."""
        from api.routes.enrichment import _background_enrich

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with (
            patch("shared.db.AsyncSessionLocal", return_value=mock_session),
            patch("api.routes.enrichment._orchestrator") as mock_orch,
        ):
            mock_orch.enrich_person = AsyncMock(side_effect=RuntimeError("boom"))
            await _background_enrich("00000000-0000-0000-0000-000000000001")

        mock_session.rollback.assert_called_once()


# ===========================================================================
# shared/data_quality.py — line 28
# ===========================================================================


class TestDataQualityLine28:
    def test_compute_composite_quality_with_conflict(self):
        """conflict_flag=True applies -CONFLICT_PENALTY (line 64-65)."""
        from shared.data_quality import compute_composite_quality

        score_no_conflict = compute_composite_quality(0.8, 0.9, 0.7, conflict_flag=False)
        score_with_conflict = compute_composite_quality(0.8, 0.9, 0.7, conflict_flag=True)
        assert score_with_conflict < score_no_conflict

    def test_compute_composite_quality_clamped_to_one(self):
        """Score is clamped to [0, 1]."""
        from shared.data_quality import compute_composite_quality

        result = compute_composite_quality(1.0, 1.0, 1.0, conflict_flag=False)
        assert result <= 1.0

    def test_corroboration_score_count_zero(self):
        """count <= 0 → 0.0 (line 77-78)."""
        from shared.data_quality import corroboration_score_from_count

        assert corroboration_score_from_count(0) == 0.0

    def test_corroboration_score_count_positive(self):
        """count=1 → ~0.50, count=5 → ~0.98."""
        from shared.data_quality import corroboration_score_from_count

        assert 0.4 < corroboration_score_from_count(1) < 0.6
        assert corroboration_score_from_count(5) > 0.9

    def test_get_source_reliability_known_source(self):
        """Line 28: fuzzy match returns a float for a known source."""
        from shared.data_quality import get_source_reliability

        val = get_source_reliability("gov_fda")
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0

    def test_get_source_reliability_unknown_source(self):
        """Unknown source returns a default float."""
        from shared.data_quality import get_source_reliability

        val = get_source_reliability("totally_unknown_xyz")
        assert isinstance(val, float)


# ===========================================================================
# shared/transport_registry.py — lines 83-84 (redis.delete exception)
# ===========================================================================


class TestTransportRegistryLines83_84:
    @pytest.mark.asyncio
    async def test_record_blocked_redis_delete_exception_is_swallowed(self):
        """
        After promotion, redis.delete raises → exception swallowed (lines 83-84).
        """
        from shared.transport_registry import TransportRegistry

        reg = TransportRegistry(threshold=1)

        # Mock redis with incr returning >= threshold, delete raising
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.get = AsyncMock(return_value=None)  # domain starts at httpx
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("redis error"))

        reg._redis = mock_redis

        # Should not raise despite delete failing
        await reg.record_blocked("example.com")
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_blocked_already_at_top_tier_no_promotion(self):
        """When domain is already at 'flaresolverr', no further promotion occurs."""
        from shared.transport_registry import TransportRegistry

        reg = TransportRegistry(threshold=1)
        reg._memory["example.com"] = "flaresolverr"

        # No redis
        reg._redis = None

        await reg.record_blocked("example.com")
        # Still at flaresolverr — no error
        assert reg._memory["example.com"] == "flaresolverr"


# ===========================================================================
# shared/circuit_breaker.py — line 123 (final return False)
# ===========================================================================


class TestCircuitBreakerLine123:
    @pytest.mark.asyncio
    async def test_is_open_closed_state_returns_false(self):
        """CLOSED state → False immediately (line 102-103)."""
        from shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker()
        with patch.object(cb, "_get", new=AsyncMock(return_value={"state": "CLOSED"})):
            result = await cb.is_open("test-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_open_unknown_state_returns_false(self):
        """Unknown state string → defaults to CLOSED → False (line 123)."""
        from shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker()
        with patch.object(cb, "_get", new=AsyncMock(return_value={"state": "UNKNOWN_XYZ"})):
            result = await cb.is_open("test-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_open_half_open_within_timeout_allows_probe(self):
        """HALF_OPEN within timeout → allows probe (line 121 return False)."""
        import time

        from shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(half_open_timeout_s=60)
        # half_opened_at is recent (within timeout)
        state_data = {"state": "HALF_OPEN", "half_opened_at": str(time.time())}
        with patch.object(cb, "_get", new=AsyncMock(return_value=state_data)):
            result = await cb.is_open("test-key")
        assert result is False


# ===========================================================================
# modules/dispatcher/growth_daemon.py — lines 122-123 (_get_person_identifiers)
# ===========================================================================


class TestGrowthDaemonLines122_123:
    @pytest.mark.asyncio
    async def test_get_person_identifiers_returns_list(self):
        """_get_person_identifiers executes select and returns scalars."""
        from modules.dispatcher.growth_daemon import GrowthDaemon

        daemon = GrowthDaemon()

        mock_ident = MagicMock()
        mock_ident.type = "email"
        mock_ident.value = "test@example.com"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_ident]

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await daemon._get_person_identifiers(session, "test-person-id")
        assert len(result) == 1
        assert result[0].type == "email"


# ===========================================================================
# modules/pipeline/ingestion_daemon.py — lines 99-100 (pivot exception)
# ===========================================================================


class TestIngestionDaemonLines99_100:
    @pytest.mark.asyncio
    async def test_process_one_pivot_exception_logged(self):
        """lines 99-100: pivot_from_result raises → warning logged, not re-raised."""
        from modules.pipeline.ingestion_daemon import IngestionDaemon

        daemon = IngestionDaemon()

        payload = {
            "platform": "test_platform",
            "identifier": "test@example.com",
            "found": True,
            "data": {"email": "test@example.com"},
            "person_id": "00000000-0000-0000-0000-000000000001",
        }

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        written = {"person_id": "00000000-0000-0000-0000-000000000001"}

        with (
            patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
            patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
            patch(
                "modules.pipeline.ingestion_daemon.aggregate_result",
                new=AsyncMock(return_value=written),
            ),
            patch(
                "modules.pipeline.ingestion_daemon.pivot_from_result",
                new=AsyncMock(side_effect=RuntimeError("pivot error")),
            ),
            patch("modules.pipeline.ingestion_daemon._orchestrator") as mock_orch,
        ):
            mock_bus.dequeue = AsyncMock(return_value=payload)
            mock_bus.enqueue = AsyncMock()
            mock_orch.enrich_person = AsyncMock()
            # Second call: enrich session
            mock_session2 = AsyncMock()
            mock_session2.__aenter__ = AsyncMock(return_value=mock_session2)
            mock_session2.__aexit__ = AsyncMock(return_value=False)

            await daemon._process_one()

        # If we reach here, exception was swallowed as intended


# ===========================================================================
# modules/search/index_daemon.py — lines 76-77 (_index_person exception)
# ===========================================================================


class TestIndexDaemonLines76_77:
    @pytest.mark.asyncio
    async def test_process_one_index_person_exception_logged(self):
        """lines 76-77: _index_person raises → error logged, not re-raised."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()

        payload = {"person_id": "00000000-0000-0000-0000-000000000001"}

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("modules.search.index_daemon.event_bus") as mock_bus,
            patch("modules.search.index_daemon.AsyncSessionLocal", return_value=mock_session),
        ):
            mock_bus.dequeue = AsyncMock(return_value=payload)

            with patch.object(
                daemon, "_index_person", new=AsyncMock(side_effect=RuntimeError("index error"))
            ):
                await daemon._process_one()

        # Exception was caught and logged


# ===========================================================================
# modules/graph/company_intel.py — line 222 (pid is None → continue)
# ===========================================================================


class TestCompanyIntelLine222:
    def test_build_record_skips_emp_row_with_no_person_id(self):
        """
        Row with person_id=None → pid is None → `if not pid: continue` (line 63-64).
        Also covers the same pattern at line 222 in get_company_network().
        """
        from modules.graph.company_intel import _build_record_from_rows

        # emp_row with no person_id
        emp_row = MagicMock()
        emp_row.person_id = None
        emp_row.job_title = "Engineer"
        emp_row.is_current = True
        emp_row.started_at = None
        emp_row.location = "Austin, TX"
        emp_row.meta = {}

        record = _build_record_from_rows("Test Corp", [emp_row], [])
        # Should not raise, and should produce a record with 0 officers (pid skipped)
        assert record is not None
        assert record.officers == []

    def test_build_record_person_not_in_map(self):
        """Person row not in person_map → name falls back to pid string."""
        from modules.graph.company_intel import _build_record_from_rows

        pid = uuid.UUID("00000000-0000-0000-0000-000000000099")
        emp_row = MagicMock()
        emp_row.person_id = pid
        emp_row.job_title = None  # triggers "Employee" title
        emp_row.is_current = False
        emp_row.started_at = None
        emp_row.location = "NY"
        emp_row.meta = {}

        record = _build_record_from_rows("Acme Corp", [emp_row], [])
        assert record is not None
        assert len(record.officers) == 1

    @pytest.mark.asyncio
    async def test_get_company_network_emp_row_with_no_person_id(self):
        """
        get_company_network line 222: emp row with person_id=None → `if not pid: continue`.
        """
        from modules.graph.company_intel import CompanyIntelligenceEngine

        engine = CompanyIntelligenceEngine()

        emp_row = MagicMock()
        emp_row.person_id = None  # triggers the if not pid: continue at line 222
        emp_row.job_title = "CEO"
        emp_row.is_current = True

        def _scalars_all(items):
            s = MagicMock()
            s.all.return_value = list(items)
            return s

        session = MagicMock()
        call_count = [0]

        async def fake_execute(stmt):
            r = MagicMock()
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                r.scalars.return_value = _scalars_all([emp_row])  # emp rows
            elif c == 1:
                r.scalars.return_value = _scalars_all([])  # person rows
            else:
                r.scalars.return_value = _scalars_all([])  # rel rows
            return r

        session.execute = fake_execute

        result = await engine.get_company_network("Test Corp", session)
        # nodes_dict only has the company node since no valid pids
        assert "nodes" in result
        assert "edges" in result
        assert result["edges"] == []


# ===========================================================================
# modules/graph/entity_graph.py — line 89 (visited_persons check)
# ===========================================================================


class TestEntityGraphLine89:
    @pytest.mark.asyncio
    async def test_build_person_graph_dedup_visited(self):
        """
        Line 89: `if pid in visited_persons: continue` is exercised when the same
        person appears in multiple results for consecutive hops.
        """
        from modules.graph.entity_graph import EntityGraphBuilder

        builder = EntityGraphBuilder()

        pid = uuid.UUID("00000000-0000-0000-0000-000000000001")

        person = MagicMock()
        person.id = pid
        person.full_name = "John Doe"
        person.default_risk_score = 0.1

        def _scalars_all(items):
            s = MagicMock()
            s.all.return_value = list(items)
            return s

        session = MagicMock()
        call_count = [0]

        async def fake_execute(stmt):
            r = MagicMock()
            c = call_count[0]
            call_count[0] += 1
            # First call: persons → return the person
            # All subsequent: return empty
            if c == 0:
                r.scalars.return_value = _scalars_all([person])
            else:
                r.scalars.return_value = _scalars_all([])
            return r

        session.execute = fake_execute

        result = await builder.build_person_graph(str(pid), session, depth=2)
        # Node should be present once despite depth=2
        node_ids = [n["id"] for n in result["nodes"]]
        assert str(pid) in node_ids
        assert node_ids.count(str(pid)) == 1
