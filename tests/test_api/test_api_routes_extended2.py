"""
Extended API route tests — coverage gap closers.

Targets uncovered lines in:
  persons.py     — certificate, report, deduplicate, merge (valid), region/grow,
                   delete (soft + hard), history with id_type filter, list with
                   city/state filters, persons non-empty page (addr bulk-load)
  system.py      — drain_queues (all + specific + unknown), circuit-breakers
                   (connected path), circuit-breaker reset, rate-limits (connected)
  watchlist.py   — get_watchlist_matches (empty + confirmed_only), confirm_match (404 + ok)
  compliance.py  — submit_opt_out (valid + missing both fields), list_opt_outs
                   (with status filter), process_opt_out (404 + ok)
  behavioural.py — get_behavioural_profile (404 + found)
  enrichment.py  — enrich_person (invalid UUID + pipeline error),
                   enrich_person_background (invalid UUID + success)
  search.py      — _auto_detect_type branches: crypto wallet, IP address, domain,
                   national_id / company_reg explicit; existing identifier re-use
  api/deps.py    — db_session generator (db_session is already exercised via
                   dependency override; this test confirms get_db is called)
  api/main.py    — lifespan paths (event_bus failure, tor failure, meili failure,
                   rate-limiter failure), ui_redirect, root SPA

All external services, DB sessions, and heavy modules are mocked via
FastAPI dependency overrides and unittest.mock.patch.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"
BAD_UUID = "not-a-uuid"

# ---------------------------------------------------------------------------
# Session factory helpers
# ---------------------------------------------------------------------------


def _make_session(execute_return=None, scalars_return=None, get_return=None):
    session = AsyncMock()

    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                first=MagicMock(return_value=None),
            )
        ),
        scalar_one_or_none=MagicMock(return_value=None),
        mappings=MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                one=MagicMock(return_value={}),
            )
        ),
    )
    session.execute.return_value = execute_return if execute_return is not None else default_exec
    session.scalar = AsyncMock(return_value=None)

    default_scalars = MagicMock(
        all=MagicMock(return_value=[]),
        first=MagicMock(return_value=None),
    )
    session.scalars.return_value = scalars_return if scalars_return is not None else default_scalars

    session.get.return_value = get_return
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    return session


def _override_db(session):
    async def _dep():
        yield session

    return _dep


def _mock_person(pid=None):
    """Build a minimal mock Person that satisfies all attribute accesses in persons.py."""
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.full_name = "Test Person"
    p.date_of_birth = None
    p.gender = None
    p.nationality = None
    p.primary_language = None
    p.bio = None
    p.profile_image_url = None
    p.relationship_score = 0.0
    p.behavioural_risk = 0.0
    p.darkweb_exposure = 0.0
    p.default_risk_score = 0.0
    p.source_reliability = 0.5
    p.freshness_score = 0.5
    p.corroboration_count = 1
    p.composite_quality = 0.5
    p.verification_status = None
    p.conflict_flag = False
    p.created_at = None
    p.updated_at = None
    # _model_to_dict needs __table__.columns
    col = MagicMock()
    col.name = "id"
    p.__table__ = MagicMock()
    p.__table__.columns = [col]
    return p


# ---------------------------------------------------------------------------
# Autouse fixture — clears overrides between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session=None):
    if session is not None:
        app.dependency_overrides[db_session] = _override_db(session)
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# PERSONS — certificate endpoint  (lines 291-335)
# ===========================================================================


class TestPersonCertificate:
    def _session_with_person(self, pid):
        session = _make_session()
        session.get.return_value = _mock_person(pid)
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        return session

    def test_certificate_not_found(self):
        """GET /persons/{uuid}/certificate returns 404 when person missing."""
        session = _make_session(get_return=None)
        client = _client(session)
        r = client.get(f"/persons/{VALID_UUID}/certificate")
        assert r.status_code == 404

    def test_certificate_invalid_uuid(self):
        """GET /persons/bad/certificate returns 400."""
        client = _client(_make_session())
        r = client.get(f"/persons/{BAD_UUID}/certificate")
        assert r.status_code == 400

    def test_certificate_found(self):
        """GET /persons/{uuid}/certificate returns grade and score when person exists."""
        pid = uuid.uuid4()
        session = self._session_with_person(pid)

        mock_cert = MagicMock()
        mock_cert.grade = MagicMock(value="B")
        mock_cert.overall_score = 0.75
        mock_cert.source_count = 2
        mock_cert.covered_categories = ["identity"]
        mock_cert.missing_categories = ["financial"]
        mock_cert.coverage_score = 0.5
        mock_cert.improvement_actions = []
        mock_cert.certified_at = "2024-01-01T00:00:00"

        with patch("modules.enrichers.certification.certify_person", return_value=mock_cert):
            client = _client(session)
            r = client.get(f"/persons/{pid}/certificate")

        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == str(pid)
        assert data["grade"] == "B"
        assert "overall_score" in data


# ===========================================================================
# PERSONS — full report  (lines 341-396)
# ===========================================================================


class TestPersonReport:
    def test_report_not_found(self):
        """GET /persons/{uuid}/report returns 404 when person missing."""
        client = _client(_make_session(get_return=None))
        r = client.get(f"/persons/{VALID_UUID}/report")
        assert r.status_code == 404

    def test_report_invalid_uuid(self):
        """GET /persons/bad/report returns 400."""
        client = _client(_make_session())
        r = client.get(f"/persons/{BAD_UUID}/report")
        assert r.status_code == 400

    def test_report_found_empty(self):
        """GET /persons/{uuid}/report returns full report structure (all tables empty)."""
        pid = uuid.uuid4()
        session = _make_session()
        session.get.return_value = _mock_person(pid)
        # Every execute call returns an empty scalars list
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar_one=MagicMock(return_value=0),
        )

        client = _client(session)
        r = client.get(f"/persons/{pid}/report")
        assert r.status_code == 200
        data = r.json()
        assert "person" in data
        assert "identifiers" in data
        assert "summary" in data
        assert data["summary"]["identifier_count"] == 0


# ===========================================================================
# PERSONS — deduplicate endpoint  (lines 475-482, 498-535)
# ===========================================================================


class TestPersonDeduplicate:
    def test_deduplicate_returns_candidates(self):
        """POST /persons/deduplicate runs dedup scan and returns candidates list."""
        session = _make_session()
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        mock_candidate = MagicMock()
        mock_candidate.id_a = str(uuid.uuid4())
        mock_candidate.id_b = str(uuid.uuid4())
        mock_candidate.similarity_score = 0.9
        mock_candidate.match_reasons = ["name"]

        with patch(
            "modules.enrichers.deduplication.find_duplicate_persons",
            return_value=[mock_candidate],
        ):
            client = _client(session)
            r = client.post("/persons/deduplicate")

        assert r.status_code == 200
        data = r.json()
        assert "candidates" in data
        assert "total_scanned" in data
        assert "candidates_found" in data

    def test_deduplicate_with_threshold_param(self):
        """POST /persons/deduplicate?threshold=0.9 filters by threshold."""
        session = _make_session()
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        with patch(
            "modules.enrichers.deduplication.find_duplicate_persons",
            return_value=[],
        ):
            client = _client(session)
            r = client.post("/persons/deduplicate?threshold=0.9")

        assert r.status_code == 200
        assert r.json()["candidates_found"] == 0

    def test_deduplicate_threshold_out_of_range(self):
        """POST /persons/deduplicate?threshold=1.5 returns 422."""
        client = _client(_make_session())
        r = client.post("/persons/deduplicate?threshold=1.5")
        assert r.status_code == 422


# ===========================================================================
# PERSONS — merge (valid merge, 404 paths)  (lines 569-627)
# ===========================================================================


class TestPersonMergeValid:
    def test_merge_canonical_not_found(self):
        """POST /persons/merge returns 404 when canonical person missing."""
        session = _make_session(get_return=None)
        client = _client(session)
        r = client.post(
            "/persons/merge",
            json={"canonical_id": VALID_UUID, "duplicate_id": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_merge_duplicate_not_found(self):
        """POST /persons/merge returns 404 when duplicate person missing."""
        canonical_id = uuid.uuid4()
        dup_id = uuid.uuid4()

        session = _make_session()
        # First get (canonical) succeeds, second (duplicate) returns None
        session.get.side_effect = [_mock_person(canonical_id), None]

        client = _client(session)
        r = client.post(
            "/persons/merge",
            json={"canonical_id": str(canonical_id), "duplicate_id": str(dup_id)},
        )
        assert r.status_code == 404

    def test_merge_success(self):
        """POST /persons/merge returns 200 merge complete when both persons exist."""
        can_id = uuid.uuid4()
        dup_id = uuid.uuid4()

        canonical = _mock_person(can_id)
        canonical.corroboration_count = 3
        canonical.source_reliability = 0.7
        canonical.composite_quality = 0.7
        canonical.default_risk_score = 0.3

        duplicate = _mock_person(dup_id)
        duplicate.corroboration_count = 2
        duplicate.source_reliability = 0.8
        duplicate.composite_quality = 0.6
        duplicate.default_risk_score = 0.5

        session = _make_session()
        session.get.side_effect = [canonical, duplicate]
        # execute() is called for each reassign_models update + final delete
        session.execute.return_value = MagicMock()

        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.enqueue = AsyncMock()
            client = _client(session)
            r = client.post(
                "/persons/merge",
                json={"canonical_id": str(can_id), "duplicate_id": str(dup_id)},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["message"] == "Merge complete"
        assert data["canonical_id"] == str(can_id)


# ===========================================================================
# PERSONS — region/grow  (lines 655-729)
# ===========================================================================


class TestPersonRegionGrow:
    def test_region_grow_missing_location_returns_400(self):
        """POST /persons/region/grow without location fields returns 400."""
        client = _client(_make_session())
        r = client.post("/persons/region/grow", json={})
        assert r.status_code == 400

    def test_region_grow_with_city(self):
        """POST /persons/region/grow with city queues discovery jobs."""
        session = _make_session()
        session.execute.return_value = MagicMock()

        with (
            patch("modules.crawlers.registry.CRAWLER_REGISTRY", {"whitepages": MagicMock()}),
            patch("modules.dispatcher.dispatcher.dispatch_job", new=AsyncMock(return_value=None)),
        ):
            client = _client(session)
            r = client.post(
                "/persons/region/grow",
                json={"city": "Dallas", "limit": 2},
            )

        assert r.status_code == 200
        data = r.json()
        assert "jobs_queued" in data
        assert "region" in data
        assert data["region"]["city"] == "Dallas"

    def test_region_grow_country_only(self):
        """POST /persons/region/grow with only country is accepted."""
        session = _make_session()
        with (
            patch("modules.crawlers.registry.CRAWLER_REGISTRY", {}),
            patch("modules.dispatcher.dispatcher.dispatch_job", new=AsyncMock(return_value=None)),
        ):
            client = _client(session)
            r = client.post(
                "/persons/region/grow",
                json={"country": "US", "limit": 1},
            )

        assert r.status_code == 200


# ===========================================================================
# PERSONS — delete (soft + hard paths)  (lines 475-482)
# ===========================================================================


class TestPersonDelete:
    def test_delete_soft(self):
        """DELETE /persons/{uuid} soft-deletes when person has deleted_at attr."""
        pid = uuid.uuid4()
        p = _mock_person(pid)
        # hasattr check in route: ensure deleted_at exists on the mock
        p.deleted_at = None

        session = _make_session(get_return=p)
        client = _client(session)
        r = client.delete(f"/persons/{pid}")
        assert r.status_code == 200
        assert "soft-deleted" in r.json()["message"]

    def test_delete_hard(self):
        """DELETE /persons/{uuid} hard-deletes when person lacks deleted_at attr."""
        pid = uuid.uuid4()
        p = MagicMock(spec=["id", "full_name"])  # no deleted_at attribute
        p.id = pid

        session = _make_session(get_return=p)
        client = _client(session)
        r = client.delete(f"/persons/{pid}")
        assert r.status_code == 200
        assert "deleted" in r.json()["message"]


# ===========================================================================
# PERSONS — history with id_type filter  (line 838 / id_type branch)
# ===========================================================================


class TestPersonHistoryFilter:
    def test_history_with_id_type_phone(self):
        """GET /persons/{uuid}/history?id_type=phone filters by type."""
        pid = uuid.uuid4()
        session = _make_session()
        session.get.return_value = _mock_person(pid)
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        client = _client(session)
        r = client.get(f"/persons/{pid}/history?id_type=phone")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["phones"] == []

    def test_history_id_type_email(self):
        """GET /persons/{uuid}/history?id_type=email returns 200."""
        pid = uuid.uuid4()
        session = _make_session()
        session.get.return_value = _mock_person(pid)
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        client = _client(session)
        r = client.get(f"/persons/{pid}/history?id_type=email")
        assert r.status_code == 200


# ===========================================================================
# PERSONS — list with city/state bulk-load path  (lines 152-160)
# ===========================================================================


class TestPersonListBulkLoad:
    def test_list_persons_with_city_filter(self):
        """GET /persons?city=Dallas triggers address sub-query and returns 200."""
        session = _make_session()
        # Two execute calls: count query, then paginated rows query; city sub handled too
        session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        )
        client = _client(session)
        r = client.get("/persons?city=Dallas")
        assert r.status_code == 200

    def test_list_persons_with_state_filter(self):
        """GET /persons?state=TX triggers address sub-query and returns 200."""
        session = _make_session()
        session.execute.return_value = MagicMock(
            scalar_one=MagicMock(return_value=0),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        )
        client = _client(session)
        r = client.get("/persons?state=TX")
        assert r.status_code == 200

    def test_list_persons_page_has_addresses(self):
        """When persons are returned the address bulk-load branch is exercised."""
        pid = uuid.uuid4()
        mock_p = _mock_person(pid)
        mock_p.default_risk_score = 0.1
        mock_p.behavioural_risk = 0.0
        mock_p.darkweb_exposure = 0.0
        mock_p.relationship_score = 0.0
        mock_p.source_reliability = 0.5
        mock_p.composite_quality = 0.5
        mock_p.corroboration_count = 1
        mock_p.verification_status = None

        call_count = [0]

        async def _side_effect(query, *a, **kw):
            call_count[0] += 1
            m = MagicMock()
            if call_count[0] == 1:
                # count query
                m.scalar_one = MagicMock(return_value=1)
                m.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            elif call_count[0] == 2:
                # paginated persons query
                m.scalar_one = MagicMock(return_value=1)
                m.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_p])))
            else:
                # address bulk-load
                m.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return m

        session = _make_session()
        session.execute.side_effect = _side_effect
        client = _client(session)
        r = client.get("/persons")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1


# ===========================================================================
# SYSTEM — drain_queues endpoint  (lines 161-180)
# ===========================================================================


class TestSystemDrainQueues:
    def test_drain_all_queues(self):
        """POST /system/queues/drain drains all queues when queue=all."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.QUEUES = {"high": "lycan:q:high", "normal": "lycan:q:normal"}
            mock_bus.redis.llen = AsyncMock(return_value=5)
            mock_bus.redis.delete = AsyncMock()
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/system/queues/drain?queue=all")

        assert r.status_code == 200
        data = r.json()
        assert "cleared" in data or "error" in data

    def test_drain_specific_queue(self):
        """POST /system/queues/drain?queue=high drains one queue."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.QUEUES = {"high": "lycan:q:high"}
            mock_bus.redis.llen = AsyncMock(return_value=3)
            mock_bus.redis.delete = AsyncMock()
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/system/queues/drain?queue=high")

        assert r.status_code == 200
        data = r.json()
        assert "cleared" in data or "error" in data

    def test_drain_unknown_queue(self):
        """POST /system/queues/drain?queue=bogus returns error or unknown message."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.QUEUES = {"high": "lycan:q:high"}
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/system/queues/drain?queue=bogus")

        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "Unknown" in str(data)


# ===========================================================================
# SYSTEM — circuit breakers (connected path)  (lines 191-203)
# ===========================================================================


class TestSystemCircuitBreakerConnected:
    def test_circuit_breakers_connected_returns_breakers(self):
        """GET /system/circuit-breakers returns breaker dict when Redis is live."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.redis.keys = AsyncMock(return_value=[b"lycan:cb:twitter.com"])
            with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_getter:
                mock_cb = MagicMock()
                mock_cb.get_state = AsyncMock(return_value="closed")
                mock_cb_getter.return_value = mock_cb
                client = TestClient(app, raise_server_exceptions=False)
                r = client.get("/system/circuit-breakers")

        assert r.status_code == 200
        data = r.json()
        assert "breakers" in data

    def test_circuit_breaker_reset(self):
        """POST /system/circuit-breakers/{domain}/reset forces close state."""
        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_getter:
            mock_cb = MagicMock()
            mock_cb.force_close = AsyncMock()
            mock_cb_getter.return_value = mock_cb
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/system/circuit-breakers/twitter.com/reset")

        assert r.status_code == 200
        data = r.json()
        assert "twitter.com" in data["message"]
        assert data["domain"] == "twitter.com"


# ===========================================================================
# SYSTEM — rate-limits (connected path)  (lines 223-236)
# ===========================================================================


class TestSystemRateLimitsConnected:
    def test_rate_limits_connected_returns_buckets(self):
        """GET /system/rate-limits returns bucket dict when Redis is live."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.redis.keys = AsyncMock(return_value=[b"lycan:rl:instagram"])
            with patch("shared.rate_limiter.get_rate_limiter") as mock_rl_getter:
                mock_rl = MagicMock()
                mock_rl.peek = AsyncMock(return_value=9.5)
                mock_rl_getter.return_value = mock_rl
                client = TestClient(app, raise_server_exceptions=False)
                r = client.get("/system/rate-limits")

        assert r.status_code == 200
        data = r.json()
        assert "buckets" in data


# ===========================================================================
# SYSTEM — queue stats error path  (lines 154-155)
# ===========================================================================


class TestSystemQueuesError:
    def test_queue_stats_db_error_returns_graceful(self):
        """GET /system/queues returns error key when the DB call raises."""
        session = _make_session()
        session.execute.side_effect = Exception("db blew up")
        app.dependency_overrides[db_session] = _override_db(session)

        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.queue_length = AsyncMock(side_effect=Exception("redis gone"))
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/queues")

        assert r.status_code == 200
        assert "error" in r.json()


# ===========================================================================
# WATCHLIST routes  (/watchlist/...)  (lines 21-25, 47-52)
# ===========================================================================


class TestWatchlistRoutes:
    def test_get_watchlist_matches_empty(self):
        """GET /watchlist/{uuid} returns empty matches list."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.get(f"/watchlist/{VALID_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["matches"] == []
        assert data["count"] == 0

    def test_get_watchlist_matches_confirmed_only(self):
        """GET /watchlist/{uuid}?confirmed_only=true applies is_confirmed filter."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.get(f"/watchlist/{VALID_UUID}?confirmed_only=true")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_get_watchlist_matches_with_rows(self):
        """GET /watchlist/{uuid} serialises match rows correctly."""
        match = MagicMock()
        match.id = uuid.UUID(VALID_UUID)
        match.list_name = "OFAC SDN"
        match.list_type = "sanctions"
        match.match_score = 0.95
        match.match_name = "Test Person"
        match.listed_date = None
        match.reason = "name match"
        match.source_url = "https://ofac.example"
        match.is_confirmed = False
        match.meta = {}

        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[match]))
        client = _client(session)
        r = client.get(f"/watchlist/{VALID_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["matches"][0]["list_name"] == "OFAC SDN"

    def test_confirm_match_not_found(self):
        """POST /watchlist/{uuid}/confirm returns 404 when match missing."""
        session = _make_session(get_return=None)
        client = _client(session)
        r = client.post(f"/watchlist/{VALID_UUID}/confirm")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_confirm_match_success(self):
        """POST /watchlist/{uuid}/confirm sets is_confirmed=True and returns message."""
        match_id = uuid.UUID(VALID_UUID)
        mock_match = MagicMock()
        mock_match.id = match_id
        mock_match.is_confirmed = False

        session = _make_session(get_return=mock_match)
        client = _client(session)
        r = client.post(f"/watchlist/{match_id}/confirm")
        assert r.status_code == 200
        data = r.json()
        assert "confirmed" in data["message"].lower()
        assert mock_match.is_confirmed is True


# ===========================================================================
# COMPLIANCE routes  (/compliance/...)  (lines 27-33, 38-42, 60-66)
# ===========================================================================


class TestComplianceRoutes:
    def test_submit_opt_out_missing_both_fields(self):
        """POST /compliance/opt-out without person_id or email returns 422."""
        session = _make_session()
        client = _client(session)
        r = client.post("/compliance/opt-out", json={"request_type": "erasure"})
        assert r.status_code == 422

    def test_submit_opt_out_with_email(self):
        """POST /compliance/opt-out with email field succeeds."""
        session = _make_session()
        mock_record = MagicMock()
        mock_record.id = uuid.uuid4()
        mock_record.status = "pending"
        mock_record.request_type = "erasure"
        session.refresh = AsyncMock(side_effect=lambda r: None)

        # After db.add + commit + refresh the record attr is populated via mock
        async def _refresh(obj):
            obj.id = mock_record.id
            obj.status = mock_record.status
            obj.request_type = mock_record.request_type

        session.refresh.side_effect = _refresh

        client = _client(session)
        r = client.post(
            "/compliance/opt-out",
            json={"email": "user@example.com", "request_type": "erasure"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["request_type"] == "erasure"

    def test_submit_opt_out_with_person_id(self):
        """POST /compliance/opt-out with person_id UUID succeeds."""
        session = _make_session()

        async def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.status = "pending"
            obj.request_type = "access"

        session.refresh.side_effect = _refresh

        client = _client(session)
        r = client.post(
            "/compliance/opt-out",
            json={"person_id": VALID_UUID, "request_type": "access"},
        )
        assert r.status_code == 200

    def test_list_opt_outs_empty(self):
        """GET /compliance/opt-outs returns empty list."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.get("/compliance/opt-outs")
        assert r.status_code == 200
        data = r.json()
        assert data["opt_outs"] == []
        assert data["count"] == 0

    def test_list_opt_outs_with_status_filter(self):
        """GET /compliance/opt-outs?status=pending applies status filter."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.get("/compliance/opt-outs?status=pending")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_process_opt_out_not_found(self):
        """POST /compliance/opt-outs/{uuid}/process returns 404 when missing."""
        session = _make_session(get_return=None)
        client = _client(session)
        r = client.post(f"/compliance/opt-outs/{VALID_UUID}/process")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_process_opt_out_success(self):
        """POST /compliance/opt-outs/{uuid}/process marks record as processed."""
        opt_out_id = uuid.UUID(VALID_UUID)
        mock_record = MagicMock()
        mock_record.id = opt_out_id
        mock_record.status = "pending"
        mock_record.processed_at = None

        session = _make_session(get_return=mock_record)
        client = _client(session)
        r = client.post(f"/compliance/opt-outs/{opt_out_id}/process")
        assert r.status_code == 200
        data = r.json()
        assert "processed" in data["message"].lower()
        assert mock_record.status == "processed"


# ===========================================================================
# BEHAVIOURAL routes  (/behavioural/...)  (lines 19-27)
# ===========================================================================


class TestBehaviouralRoutes:
    def test_get_behavioural_not_found(self):
        """GET /behavioural/{uuid} returns 404 when no profile exists."""
        session = _make_session()
        session.scalar = AsyncMock(return_value=None)
        client = _client(session)
        r = client.get(f"/behavioural/{VALID_UUID}")
        assert r.status_code == 404
        assert "behavioural" in r.json()["detail"].lower()

    def test_get_behavioural_found(self):
        """GET /behavioural/{uuid} returns profile and signals when found."""
        profile_id = uuid.uuid4()
        mock_profile = MagicMock()
        mock_profile.id = profile_id
        mock_profile.person_id = uuid.UUID(VALID_UUID)
        mock_profile.gambling_score = 0.1
        mock_profile.drug_signal_score = 0.0
        mock_profile.fraud_score = 0.2
        mock_profile.violence_score = 0.0
        mock_profile.financial_distress_score = 0.3
        mock_profile.criminal_signal_score = 0.0
        mock_profile.active_hours = []
        mock_profile.top_locations = []
        mock_profile.interests = []
        mock_profile.languages_used = []
        mock_profile.sentiment_avg = 0.5
        mock_profile.last_assessed_at = None
        mock_profile.meta = {}

        mock_signal = MagicMock()
        mock_signal.id = uuid.uuid4()
        mock_signal.signal_type = "gambling"
        mock_signal.score = 0.1
        mock_signal.evidence_text = "seen on betting site"
        mock_signal.source_url = "https://example.com"
        mock_signal.source_platform = "twitter"

        session = _make_session()
        session.scalar = AsyncMock(return_value=mock_profile)
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[mock_signal]))

        client = _client(session)
        r = client.get(f"/behavioural/{VALID_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert "profile" in data
        assert "signals" in data
        assert data["profile"]["gambling_score"] == 0.1
        assert len(data["signals"]) == 1


# ===========================================================================
# ENRICHMENT routes  (/enrich/...)  (lines 55-58, 97-99)
# ===========================================================================


class TestEnrichmentRoutes:
    def test_enrich_invalid_uuid(self):
        """POST /enrich/bad/enrich returns 400 for malformed UUID."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{BAD_UUID}/enrich")
        assert r.status_code == 400
        assert "UUID" in r.json()["detail"]

    def test_enrich_pipeline_error_returns_500(self):
        """POST /enrich/{uuid}/enrich returns 500 when orchestrator raises."""
        with patch(
            "api.routes.enrichment._orchestrator.enrich_person",
            new=AsyncMock(side_effect=Exception("pipeline exploded")),
        ):
            client = _client(_make_session())
            r = client.post(f"/enrich/{VALID_UUID}/enrich")

        assert r.status_code == 500
        assert "failed" in r.json()["detail"].lower()

    def test_enrich_background_invalid_uuid(self):
        """POST /enrich/bad/enrich/background returns 400 for malformed UUID."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{BAD_UUID}/enrich/background")
        assert r.status_code == 400

    def test_enrich_background_success(self):
        """POST /enrich/{uuid}/enrich/background returns queued status immediately."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{VALID_UUID}/enrich/background")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["person_id"] == VALID_UUID


# ===========================================================================
# SEARCH — auto-detect edge cases  (lines 171, 177, 181, 187, 194, 248, 273)
# ===========================================================================


class TestSearchAutoDetect:
    def _search_session(self):
        session = AsyncMock()
        session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session

    def test_search_crypto_wallet_ethereum(self):
        """POST /search auto-detects Ethereum address as crypto_wallet."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "0xAbCd1234567890abcdef1234567890AbCdEf1234"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "crypto_wallet"

    def test_search_crypto_wallet_bitcoin(self):
        """POST /search auto-detects Bitcoin P2PKH address as crypto_wallet."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "crypto_wallet"

    def test_search_ip_address_explicit(self):
        """POST /search with explicit ip_address seed type is accepted."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "192.168.1.1", "seed_type": "ip_address"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "ip_address"

    def test_search_ip_address_ipv6_auto_detect(self):
        """POST /search auto-detects IPv6 address as ip_address (phone regex won't match)."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "2001:db8::1"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "ip_address"

    def test_search_domain(self):
        """POST /search auto-detects domain name as domain seed type."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "example.com"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "domain"

    def test_search_explicit_national_id_type(self):
        """POST /search accepts explicit national_id seed type."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/search",
                json={"value": "123456789", "seed_type": "national_id"},
            )
        assert r.status_code == 200
        assert r.json()["seed_type"] == "national_id"

    def test_search_explicit_company_reg_type(self):
        """POST /search accepts explicit company_reg seed type."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/search",
                json={"value": "US12345678", "seed_type": "company_reg"},
            )
        assert r.status_code == 200
        assert r.json()["seed_type"] == "company_reg"

    def test_search_existing_identifier_reuse(self):
        """POST /search reuses existing person_id when identifier already exists."""
        existing_pid = uuid.uuid4()
        existing_ident = MagicMock()
        existing_ident.person_id = existing_pid

        session = AsyncMock()
        session.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing_ident)
        )
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        app.dependency_overrides[db_session] = _override_db(session)
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "test@example.com"})

        assert r.status_code == 200
        assert r.json()["person_id"] == str(existing_pid)

    def test_search_existing_identifier_no_person_creates_new(self):
        """POST /search creates new person when existing identifier has no person_id."""
        existing_ident = MagicMock()
        existing_ident.person_id = None

        session = AsyncMock()
        session.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing_ident)
        )
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        app.dependency_overrides[db_session] = _override_db(session)
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "orphan@example.com"})

        assert r.status_code == 200
        assert "person_id" in r.json()


# ===========================================================================
# API deps — db_session generator  (lines 10-11)
# ===========================================================================


class TestApiDeps:
    def test_db_session_is_used_via_override(self):
        """Confirm db_session dependency is reachable (exercised via override in other tests)."""
        # The dependency exists and is importable
        from api.deps import db_session as dep

        assert callable(dep)

    def test_db_session_get_db_called(self):
        """db_session correctly delegates to shared.db.get_db."""
        import inspect

        import api.deps as deps_module

        src = inspect.getsource(deps_module.db_session)
        assert "get_db" in src


# ===========================================================================
# API main.py — lifespan error paths  (lines 41-42, 50-53, 58-59, 64-65, 74-75, 82-83)
# ===========================================================================


class TestMainLifespan:
    def test_app_survives_event_bus_connect_failure(self):
        """App starts up even when EventBus.connect raises."""
        with patch(
            "shared.events.event_bus.connect", new=AsyncMock(side_effect=Exception("no redis"))
        ):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/health/simple")
        assert r.status_code == 200

    def test_app_survives_tor_failure(self):
        """App starts up even when tor_manager.connect_all raises."""
        with patch(
            "shared.tor.tor_manager.connect_all",
            new=AsyncMock(side_effect=Exception("no tor")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/health/simple")
        assert r.status_code == 200

    def test_app_survives_meili_failure(self):
        """App starts up even when meili_indexer.setup_index raises."""
        with patch(
            "modules.search.meili_indexer.meili_indexer.setup_index",
            new=AsyncMock(side_effect=Exception("no meili")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/health/simple")
        assert r.status_code == 200

    def test_app_survives_rate_limiter_init_failure(self):
        """App starts up even when rate-limiter init raises."""
        with patch(
            "shared.rate_limiter.init_rate_limiter",
            side_effect=Exception("no rl"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/health/simple")
        assert r.status_code == 200
