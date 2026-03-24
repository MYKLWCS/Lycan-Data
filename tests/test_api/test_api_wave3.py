"""Wave-3 API tests.

Covers:
  - ws.py        WebSocket ping-pong, server keepalive ping, cleanup, SSE endpoint
  - system.py    Full health (redis+db ok), drain exception, circuit-breakers keys,
                 rate-limits keys
  - enrichment.py  _background_enrich exception path, route exception path
  - search_query.py  state filter, country filter, has_sanctions filter
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.main import app


# ─── Shared fixture ──────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ══════════════════════════════════════════════════════════════════════════════
# ws.py — WebSocket tests
# ══════════════════════════════════════════════════════════════════════════════


class TestWebSocketPingPong:
    """Client sends 'ping', server echoes {'event': 'pong'}."""

    def test_client_ping_receives_pong(self, client):
        person_id = str(uuid.uuid4())

        # Patch event_bus.subscribe so it never resolves (blocks naturally)
        async def _noop_subscribe(channel, callback):
            await asyncio.sleep(999)

        with patch("shared.events.event_bus.subscribe", side_effect=_noop_subscribe):
            with client.websocket_connect(f"/ws/progress/{person_id}") as ws:
                ws.send_text("ping")
                msg = ws.receive_json()
                assert msg == {"event": "pong"}


class TestWebSocketServerTimeout:
    """When receive_text times out the server sends {'event': 'ping'} to client."""

    def test_server_sends_ping_on_timeout(self, client):
        person_id = str(uuid.uuid4())

        async def _noop_subscribe(channel, callback):
            await asyncio.sleep(999)

        # Patch asyncio.wait_for so the first call raises TimeoutError,
        # causing the server to emit a server-side ping; the second call
        # raises WebSocketDisconnect so the loop exits cleanly.
        from fastapi import WebSocketDisconnect as _WSD

        call_count = 0

        async def _patched_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            coro.close()  # prevent ResourceWarning
            if call_count == 1:
                raise TimeoutError
            raise _WSD(code=1000)

        with patch("shared.events.event_bus.subscribe", side_effect=_noop_subscribe):
            with patch("asyncio.wait_for", side_effect=_patched_wait_for):
                with client.websocket_connect(f"/ws/progress/{person_id}") as ws:
                    msg = ws.receive_json()
                    assert msg == {"event": "ping"}


class TestWebSocketCleanupOnDisconnect:
    """sub_task is cancelled when the WebSocket closes."""

    def test_sub_task_cancelled_on_disconnect(self, client):
        person_id = str(uuid.uuid4())

        cancelled = []

        async def _noop_subscribe(channel, callback):
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        with patch("shared.events.event_bus.subscribe", side_effect=_noop_subscribe):
            with client.websocket_connect(f"/ws/progress/{person_id}") as ws:
                # Close from client side — triggers cleanup in finally block
                ws.close()

        # The subscribe coroutine should have been cancelled
        assert cancelled == [True]


# ══════════════════════════════════════════════════════════════════════════════
# ws.py — SSE endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestSSEEndpoint:
    """GET /sse/progress/{person_id} with Accept: text/event-stream."""

    def test_sse_returns_streaming_response_when_bus_disconnected(self, client):
        person_id = str(uuid.uuid4())

        with patch("shared.events.event_bus.is_connected", False):
            resp = client.get(
                f"/sse/progress/{person_id}",
                headers={"Accept": "text/event-stream"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # First chunk must be an error event because bus is unavailable
        raw = resp.text
        assert "event bus unavailable" in raw

    def test_sse_content_type_header(self, client):
        person_id = str(uuid.uuid4())

        with patch("shared.events.event_bus.is_connected", False):
            resp = client.get(f"/sse/progress/{person_id}")

        assert "text/event-stream" in resp.headers.get("content-type", "")


# ══════════════════════════════════════════════════════════════════════════════
# system.py — health endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    def _mock_redis(self):
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        return redis

    def test_health_redis_ok_db_ok(self, client):
        mock_redis = self._mock_redis()

        mock_rl = MagicMock()
        mock_rl.peek = AsyncMock(return_value=99.0)

        with (
            patch("shared.events.event_bus.redis", mock_redis),
            patch("shared.events.event_bus.is_connected", True),
            patch(
                "shared.db.AsyncSessionLocal",
                return_value=_async_session_ctx(),
            ),
            patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
            patch(
                "shared.tor.tor_manager.status",
                return_value={"connected": False, "circuits": 0},
            ),
        ):
            resp = client.get("/system/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["redis"]["ok"] is True
        assert data["db"]["ok"] is True
        assert data.get("status") in ("ok", "degraded")

    def test_health_redis_failure_marks_degraded(self, client):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("redis down"))

        mock_rl = MagicMock()
        mock_rl.peek = AsyncMock(return_value=10.0)

        with (
            patch("shared.events.event_bus.redis", mock_redis),
            patch("shared.events.event_bus.is_connected", True),
            patch(
                "shared.db.AsyncSessionLocal",
                return_value=_async_session_ctx(),
            ),
            patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
            patch(
                "shared.tor.tor_manager.status",
                return_value={"connected": False},
            ),
        ):
            resp = client.get("/system/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["redis"]["ok"] is False
        assert data["status"] == "degraded"

    def test_health_rate_limiter_included(self, client):
        mock_redis = self._mock_redis()
        mock_rl = MagicMock()
        mock_rl.peek = AsyncMock(return_value=42.5)

        with (
            patch("shared.events.event_bus.redis", mock_redis),
            patch("shared.events.event_bus.is_connected", True),
            patch("shared.db.AsyncSessionLocal", return_value=_async_session_ctx()),
            patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
            patch("shared.tor.tor_manager.status", return_value={}),
        ):
            resp = client.get("/system/health")

        data = resp.json()
        assert "rate_limiter" in data
        assert data["rate_limiter"]["ok"] is True
        assert data["rate_limiter"]["probe_tokens"] == 42.5


# ══════════════════════════════════════════════════════════════════════════════
# system.py — drain exception path
# ══════════════════════════════════════════════════════════════════════════════


class TestDrainQueues:
    def test_drain_exception_returns_error_json(self, client):
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(side_effect=RuntimeError("redis exploded"))
        mock_redis.delete = AsyncMock()

        mock_bus = MagicMock()
        mock_bus.QUEUES = {"high": "lycan:q:high"}
        mock_bus.redis = mock_redis

        with patch("shared.events.event_bus", mock_bus):
            resp = client.post("/system/queues/drain?queue=all")

        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert "redis exploded" in data["error"]

    def test_drain_unknown_queue_returns_error(self, client):
        mock_bus = MagicMock()
        mock_bus.QUEUES = {"high": "lycan:q:high"}
        mock_bus.redis = AsyncMock()

        with patch("shared.events.event_bus", mock_bus):
            resp = client.post("/system/queues/drain?queue=nonexistent")

        data = resp.json()
        assert "error" in data
        assert "Unknown queue" in data["error"]


# ══════════════════════════════════════════════════════════════════════════════
# system.py — circuit-breakers keys
# ══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreakers:
    def test_circuit_breakers_returns_domain_states(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"lycan:cb:example.com", b"lycan:cb:foo.io"])

        mock_cb = MagicMock()
        mock_cb.get_state = AsyncMock(return_value={"state": "closed", "failures": 0})

        with (
            patch("shared.events.event_bus.is_connected", True),
            patch("shared.events.event_bus.redis", mock_redis),
            patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        ):
            resp = client.get("/system/circuit-breakers")

        assert resp.status_code == 200
        data = resp.json()
        assert "breakers" in data
        assert data["count"] == 2
        assert "example.com" in data["breakers"]
        assert "foo.io" in data["breakers"]

    def test_circuit_breakers_redis_disconnected(self, client):
        with patch("shared.events.event_bus.is_connected", False):
            resp = client.get("/system/circuit-breakers")

        data = resp.json()
        assert "error" in data
        assert data["breakers"] == {}


# ══════════════════════════════════════════════════════════════════════════════
# system.py — rate-limits keys
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimits:
    def test_rate_limits_returns_buckets(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(
            return_value=[b"lycan:rl:instagram.com", b"lycan:rl:twitter.com"]
        )

        mock_rl = MagicMock()
        mock_rl.peek = AsyncMock(return_value=7.5)

        with (
            patch("shared.events.event_bus.is_connected", True),
            patch("shared.events.event_bus.redis", mock_redis),
            patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        ):
            resp = client.get("/system/rate-limits")

        assert resp.status_code == 200
        data = resp.json()
        assert "buckets" in data
        assert data["count"] == 2
        assert "instagram.com" in data["buckets"]
        assert data["buckets"]["instagram.com"]["tokens"] == 7.5

    def test_rate_limits_redis_disconnected(self, client):
        with patch("shared.events.event_bus.is_connected", False):
            resp = client.get("/system/rate-limits")

        data = resp.json()
        assert "error" in data
        assert data["buckets"] == {}


# ══════════════════════════════════════════════════════════════════════════════
# enrichment.py — _background_enrich exception path
# ══════════════════════════════════════════════════════════════════════════════


class TestBackgroundEnrich:
    @pytest.mark.asyncio
    async def test_background_enrich_exception_triggers_rollback(self):
        """When enrich_person raises, _background_enrich calls rollback and swallows."""
        from api.routes.enrichment import _background_enrich

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("shared.db.AsyncSessionLocal", return_value=mock_ctx),
            patch(
                "modules.pipeline.enrichment_orchestrator.EnrichmentOrchestrator.enrich_person",
                new_callable=AsyncMock,
                side_effect=RuntimeError("enrich boom"),
            ),
        ):
            # Must not raise
            await _background_enrich("some-person-id")

        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# enrichment.py — route exception path → HTTP 500
# ══════════════════════════════════════════════════════════════════════════════


class TestEnrichRouteException:
    def test_enrich_person_500_on_exception(self, client):
        person_id = str(uuid.uuid4())

        with patch(
            "api.routes.enrichment._orchestrator.enrich_person",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pipeline broke"),
        ):
            resp = client.post(f"/enrich/{person_id}/enrich")

        assert resp.status_code == 500
        assert "Enrichment pipeline failed" in resp.json()["detail"]

    def test_enrich_person_400_on_bad_uuid(self, client):
        resp = client.post("/enrich/not-a-uuid/enrich")
        assert resp.status_code == 400
        assert "Invalid UUID" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# search_query.py — state, country, has_sanctions filters
# (these are missing from the existing test_search_query.py)
# ══════════════════════════════════════════════════════════════════════════════

_SEARCH_RESULT = {
    "hits": [{"id": "abc123", "full_name": "Jane Doe"}],
    "estimatedTotalHits": 1,
}


class TestSearchQueryFilters:
    def test_state_filter_appended(self, client):
        with patch(
            "modules.search.meili_indexer.meili_indexer.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = _SEARCH_RESULT
            client.get("/query/persons", params={"state": "TX"})

        filters = mock_search.call_args.kwargs.get("filters", "")
        assert "TX" in (filters or "")
        assert "state_province" in (filters or "")

    def test_country_filter_appended(self, client):
        with patch(
            "modules.search.meili_indexer.meili_indexer.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = _SEARCH_RESULT
            client.get("/query/persons", params={"country": "US"})

        filters = mock_search.call_args.kwargs.get("filters", "")
        assert "US" in (filters or "")
        assert "country" in (filters or "")

    def test_has_sanctions_true_filter(self, client):
        with patch(
            "modules.search.meili_indexer.meili_indexer.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = _SEARCH_RESULT
            client.get("/query/persons", params={"has_sanctions": "true"})

        filters = mock_search.call_args.kwargs.get("filters", "")
        assert "has_sanctions = true" in (filters or "")

    def test_has_sanctions_false_filter(self, client):
        with patch(
            "modules.search.meili_indexer.meili_indexer.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = _SEARCH_RESULT
            client.get("/query/persons", params={"has_sanctions": "false"})

        filters = mock_search.call_args.kwargs.get("filters", "")
        assert "has_sanctions = false" in (filters or "")

    def test_state_and_country_combined(self, client):
        with patch(
            "modules.search.meili_indexer.meili_indexer.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = _SEARCH_RESULT
            client.get("/query/persons", params={"state": "CA", "country": "US"})

        filters = mock_search.call_args.kwargs.get("filters", "")
        assert "CA" in (filters or "")
        assert "US" in (filters or "")
        # Both parts joined with AND
        assert " AND " in (filters or "")


# ─── Internal helper — fake async context manager for AsyncSessionLocal ───────


class _FakeSession:
    """Minimal async session that records calls and supports `async with`."""

    def __init__(self):
        self._execute_result = MagicMock()
        self._execute_result.mappings = MagicMock(
            return_value=MagicMock(one=MagicMock(return_value={"total_logs": 0, "found_count": 0}))
        )

    async def execute(self, *a, **kw):
        return self._execute_result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _async_session_ctx():
    """Return an object usable as `async with AsyncSessionLocal() as session`."""

    class _Ctx:
        def __init__(self):
            self._s = _FakeSession()

        def __call__(self, *a, **kw):
            return self

        async def __aenter__(self):
            return self._s

        async def __aexit__(self, *a):
            return False

    return _Ctx()
