"""
FastAPI route tests — no running infrastructure required.

All DB sessions and external services are mocked via FastAPI dependency overrides
and unittest.mock.patch. The tests verify routing, request/response shapes, and
status codes only — full business logic is covered by unit tests elsewhere.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app


# ---------------------------------------------------------------------------
# Shared mock session factory
# ---------------------------------------------------------------------------

def _make_session(execute_return=None, scalars_return=None, get_return=None):
    """Build an AsyncMock session with sensible defaults for all common call patterns."""
    session = AsyncMock()

    # Default execute result: scalar_one=0, scalars().all()=[], scalar_one_or_none=None
    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
        mappings=MagicMock(
            return_value=MagicMock(
                one=MagicMock(return_value={"total_logs": 0, "found_count": 0, "total": 0})
            )
        ),
    )
    session.execute.return_value = execute_return if execute_return is not None else default_exec

    # db.scalars(q).all() — used by alerts route
    default_scalars = MagicMock(all=MagicMock(return_value=[]))
    session.scalars.return_value = scalars_return if scalars_return is not None else default_scalars

    # session.get(Model, pk) — used by get_person, mark_read, etc.
    session.get.return_value = get_return  # None => 404 by default

    return session


# ---------------------------------------------------------------------------
# Dependency override helpers
# ---------------------------------------------------------------------------

def _override_db(session):
    """Return a FastAPI dependency override that yields the given mock session."""
    async def _dep():
        yield session
    return _dep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_overrides():
    """Ensure dependency overrides are cleared after every test."""
    yield
    app.dependency_overrides.clear()


# ===========================================================================
# SYSTEM routes  (/system/...)
# ===========================================================================

class TestSystemHealth:
    def test_health_simple_returns_ok(self):
        """Lightweight liveness probe must always return 200 with status=ok."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/system/health/simple")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "crawlers_registered" in data

    def test_health_full_returns_200(self):
        """Full health check returns 200 even when Redis/DB are unavailable (reports degraded)."""
        # Patch the connections so the handler does not hang waiting for real infra
        with (
            patch("shared.events.event_bus") as mock_bus,
            patch("shared.db.AsyncSessionLocal") as mock_session_local,
            patch("shared.rate_limiter.get_rate_limiter") as mock_rl,
        ):
            mock_bus.redis.ping = AsyncMock(side_effect=ConnectionRefusedError("no redis"))
            mock_rl.return_value.peek = AsyncMock(return_value=10.0)

            # Make AsyncSessionLocal().__aenter__ raise so db_ok stays False
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("no db"))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_local.return_value = mock_ctx

            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/health")

        assert r.status_code == 200
        data = r.json()
        # status is either "ok" or "degraded" — both are valid responses
        assert data["status"] in ("ok", "degraded")
        assert "redis" in data
        assert "db" in data
        assert "total_check_ms" in data

    def test_stats_returns_crawler_info(self):
        """Stats endpoint must return a dict with crawlers count and platforms list."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/system/stats")
        assert r.status_code == 200
        data = r.json()
        assert "crawlers" in data
        assert "platforms" in data
        assert isinstance(data["platforms"], list)

    def test_registry_returns_count(self):
        """Registry endpoint returns platform list and a count integer."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/system/registry")
        assert r.status_code == 200
        data = r.json()
        assert "platforms" in data
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_circuit_breakers_without_redis(self):
        """Circuit breakers endpoint returns graceful error when Redis is offline."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.is_connected = False
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/circuit-breakers")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "breakers" in data

    def test_rate_limits_without_redis(self):
        """Rate limits endpoint returns graceful error when Redis is offline."""
        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.is_connected = False
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/rate-limits")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "buckets" in data

    def test_queues_endpoint_with_mock_db(self):
        """Queue stats endpoint aggregates queue lengths and DB counters."""
        session = AsyncMock()
        call_state = {"count": 0}

        async def mock_execute(query, *args, **kwargs):
            call_state["count"] += 1
            m = MagicMock()
            if call_state["count"] == 1:
                m.mappings.return_value.one.return_value = {"total_logs": 5, "found_count": 3}
            else:
                m.mappings.return_value.one.return_value = {"total": 7}
            return m

        session.execute.side_effect = mock_execute
        app.dependency_overrides[db_session] = _override_db(session)

        with patch("shared.events.event_bus") as mock_bus:
            mock_bus.queue_length = AsyncMock(return_value=0)
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/system/queues")

        assert r.status_code == 200
        data = r.json()
        assert "queues" in data
        assert "total_pending" in data
        assert data["crawls_total"] == 5
        assert data["crawls_found"] == 3
        assert data["persons_total"] == 7


# ===========================================================================
# PERSONS routes  (/persons/...)
# ===========================================================================

class TestPersonsList:
    def test_list_persons_empty(self):
        """GET /persons returns empty list when DB has no rows."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons")
        assert r.status_code == 200
        data = r.json()
        assert data["persons"] == []
        assert data["total"] == 0
        assert "limit" in data
        assert "offset" in data

    def test_list_persons_pagination_params(self):
        """Pagination params are echoed back in the response."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons?limit=5&offset=10")
        assert r.status_code == 200
        data = r.json()
        assert data["limit"] == 5
        assert data["offset"] == 10

    def test_list_persons_sort_params(self):
        """Sort params are echoed back correctly."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons?sort_by=full_name&sort_dir=asc")
        assert r.status_code == 200
        data = r.json()
        assert data["sort_by"] == "full_name"
        assert data["sort_dir"] == "asc"

    def test_list_persons_with_query_filter(self):
        """Name search filter is accepted without error."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons?q=smith")
        assert r.status_code == 200

    def test_list_persons_with_risk_tier_filter(self):
        """Risk tier filter parameter is accepted."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons?risk_tier=high_risk")
        assert r.status_code == 200

    def test_list_persons_with_region_filter(self):
        """Region (country) filter is accepted without error."""
        # Execute is called multiple times; provide side_effect to handle subquery
        session = _make_session()
        m = MagicMock(
            scalar_one=MagicMock(return_value=0),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        )
        session.execute.return_value = m
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons?country=US")
        assert r.status_code == 200


class TestGetPerson:
    def test_get_person_not_found(self):
        """GET /persons/{uuid} returns 404 when person does not exist."""
        session = _make_session(get_return=None)
        # scalars for identifiers/profiles/addresses returns empty
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_get_person_invalid_uuid(self):
        """GET /persons/bad-id returns 400 for malformed UUID."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/persons/not-a-valid-uuid")
        assert r.status_code == 400
        assert "Invalid UUID" in r.json()["detail"]

    def test_get_person_found(self):
        """GET /persons/{uuid} returns full person payload when person exists."""
        person_id = uuid.uuid4()
        mock_person = MagicMock()
        mock_person.id = person_id
        mock_person.full_name = "Jane Doe"
        mock_person.date_of_birth = None
        mock_person.gender = None
        mock_person.nationality = None
        mock_person.primary_language = None
        mock_person.bio = None
        mock_person.profile_image_url = None
        mock_person.relationship_score = 0.0
        mock_person.behavioural_risk = 0.0
        mock_person.darkweb_exposure = 0.0
        mock_person.default_risk_score = 0.0
        mock_person.source_reliability = 0.0
        mock_person.freshness_score = 0.0
        mock_person.corroboration_count = 0
        mock_person.composite_quality = 0.0
        mock_person.verification_status = None
        mock_person.conflict_flag = False
        mock_person.created_at = None
        mock_person.updated_at = None

        session = AsyncMock()
        session.get.return_value = mock_person
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[db_session] = _override_db(session)

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{person_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == str(person_id)
        assert data["full_name"] == "Jane Doe"
        assert "identifiers" in data
        assert "social_profiles" in data
        assert "addresses" in data


class TestPersonSubRoutes:
    """Tests for /persons/{id}/identifiers, /social, /addresses, etc."""

    def _person_session(self, person_id):
        mock_person = MagicMock()
        mock_person.id = person_id
        session = AsyncMock()
        session.get.return_value = mock_person
        session.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        return session

    def test_identifiers_found(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/identifiers")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == str(pid)
        assert isinstance(data["identifiers"], list)

    def test_social_profiles_found(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/social")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == str(pid)
        assert isinstance(data["social_profiles"], list)

    def test_addresses_found(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/addresses")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == str(pid)
        assert isinstance(data["addresses"], list)

    def test_identifiers_404_for_missing_person(self):
        session = AsyncMock()
        session.get.return_value = None
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{uuid.uuid4()}/identifiers")
        assert r.status_code == 404

    def test_criminal_records_empty(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/criminal")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == str(pid)
        assert data["criminal_records"] == []
        assert data["total"] == 0
        assert data["has_sex_offender"] is False

    def test_documents_empty(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/documents")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0

    def test_credit_profile_empty(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/credit")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["has_bankruptcy"] is False

    def test_history_empty(self):
        pid = uuid.uuid4()
        app.dependency_overrides[db_session] = _override_db(self._person_session(pid))
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get(f"/persons/{pid}/history")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["phones"] == []
        assert data["emails"] == []


class TestPersonMutation:
    def test_patch_person_not_found(self):
        """PATCH /persons/{uuid} returns 404 when person does not exist."""
        session = AsyncMock()
        session.get.return_value = None
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.patch(f"/persons/{uuid.uuid4()}", json={"full_name": "New Name"})
        assert r.status_code == 404

    def test_patch_person_found(self):
        """PATCH /persons/{uuid} updates allowed fields and returns success."""
        pid = uuid.uuid4()
        mock_person = MagicMock()
        mock_person.id = pid
        session = AsyncMock()
        session.get.return_value = mock_person
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.patch(f"/persons/{pid}", json={"full_name": "Updated Name"})
        assert r.status_code == 200
        assert r.json()["message"] == "Person updated"

    def test_delete_person_not_found(self):
        """DELETE /persons/{uuid} returns 404 when person does not exist."""
        session = AsyncMock()
        session.get.return_value = None
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.delete(f"/persons/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_merge_same_ids_returns_400(self):
        """POST /persons/merge with identical IDs returns 400."""
        app.dependency_overrides[db_session] = _override_db(_make_session())
        client = TestClient(app, raise_server_exceptions=False)
        same_id = str(uuid.uuid4())
        r = client.post("/persons/merge", json={"canonical_id": same_id, "duplicate_id": same_id})
        assert r.status_code == 400


# ===========================================================================
# SEARCH routes  (/search/...)
# ===========================================================================

class TestSearchRoutes:
    def _search_session(self):
        session = AsyncMock()
        session.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )
        # session.add() is synchronous in SQLAlchemy — use MagicMock to avoid
        # "coroutine never awaited" warnings from AsyncMock's default behaviour
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session

    def test_search_email_auto_detect(self):
        """POST /search auto-detects email seed type and returns person_id."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "test@example.com"})
        assert r.status_code == 200
        data = r.json()
        assert "person_id" in data
        assert data["seed_type"] == "email"
        assert "platforms_queued" in data
        assert "job_count" in data

    def test_search_phone_auto_detect(self):
        """POST /search auto-detects phone seed type."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "+12125551234"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "phone"

    def test_search_username_auto_detect(self):
        """POST /search auto-detects username seed type for single-word values."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "johndoe123"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "username"

    def test_search_full_name_auto_detect(self):
        """POST /search auto-detects full_name for multi-word values."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "John Smith"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "full_name"

    def test_search_explicit_seed_type(self):
        """POST /search accepts an explicit seed_type override."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/search", json={"value": "somehandle", "seed_type": "username"})
        assert r.status_code == 200
        assert r.json()["seed_type"] == "username"

    def test_search_batch(self):
        """POST /search/batch processes multiple seeds and returns aggregated total_jobs."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        with patch("api.routes.search.dispatch_job", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(
                "/search/batch",
                json={
                    "seeds": [
                        {"value": "user@example.com"},
                        {"value": "anotheruser"},
                    ]
                },
            )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert len(data["results"]) == 2
        assert "total_jobs" in data

    def test_search_missing_value_returns_422(self):
        """POST /search without required 'value' field returns 422."""
        app.dependency_overrides[db_session] = _override_db(self._search_session())
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/search", json={})
        assert r.status_code == 422


# ===========================================================================
# ALERTS routes  (/alerts/...)
# ===========================================================================

class TestAlertRoutes:
    def test_list_alerts_empty(self):
        """GET /alerts/ returns empty list when DB has no alert rows."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/alerts/")
        assert r.status_code == 200
        data = r.json()
        assert data["alerts"] == []
        assert data["count"] == 0

    def test_list_alerts_unread_only_param(self):
        """GET /alerts/?unread_only=true is accepted without error."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/alerts/?unread_only=true")
        assert r.status_code == 200

    def test_list_alerts_limit_param(self):
        """GET /alerts/?limit=10 is accepted without error."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/alerts/?limit=10")
        assert r.status_code == 200

    def test_mark_read_not_found(self):
        """POST /alerts/{uuid}/read returns 404 when alert does not exist."""
        session = AsyncMock()
        session.get.return_value = None
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/alerts/{uuid.uuid4()}/read")
        assert r.status_code == 404

    def test_mark_read_success(self):
        """POST /alerts/{uuid}/read marks is_read=True and returns message."""
        alert_id = uuid.uuid4()
        mock_alert = MagicMock()
        mock_alert.id = alert_id
        mock_alert.is_read = False
        session = AsyncMock()
        session.get.return_value = mock_alert
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(f"/alerts/{alert_id}/read")
        assert r.status_code == 200
        assert r.json()["message"] == "Marked as read"
        # Verify the flag was set
        assert mock_alert.is_read is True

    def test_mark_all_read(self):
        """POST /alerts/mark-all-read returns success message."""
        session = AsyncMock()
        app.dependency_overrides[db_session] = _override_db(session)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/alerts/mark-all-read")
        assert r.status_code == 200
        assert "read" in r.json()["message"].lower()


# ===========================================================================
# SPA / root routes
# ===========================================================================

class TestRootRoutes:
    def test_root_returns_spa(self):
        """GET / returns the SPA index.html."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/")
        assert r.status_code == 200

    def test_ui_redirect(self):
        """GET /ui/* redirects to SPA hash router."""
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        r = client.get("/ui/persons")
        # Either a 307/308 redirect or a 200 if follow_redirects kicks in
        assert r.status_code in (200, 307, 308)
