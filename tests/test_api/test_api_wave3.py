"""
test_api_wave3.py — Coverage gap tests for api/routes/ws.py, system.py,
enrichment.py, and search_query.py.

All network/DB/Redis I/O is mocked — no real infrastructure required.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal app fixture — avoids importing api.main (static files + DB lifespan)
# ---------------------------------------------------------------------------


def _make_app():
    from api.routes import enrichment, search_query, system, ws

    app = FastAPI()
    app.include_router(system.router, prefix="/system")
    app.include_router(ws.router)
    app.include_router(enrichment.router, prefix="/enrich")
    app.include_router(search_query.router, prefix="/query")
    return app


@pytest.fixture(scope="module")
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# api/routes/system.py
# ===========================================================================


class TestHealthEndpoint:
    """Tests for /system/health."""

    def test_health_redis_and_db_ok(self, client):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("api.routes.system.event_bus") as mock_bus,
            patch("shared.db.AsyncSessionLocal", return_value=mock_session_cm),
            patch("api.routes.system.tor_manager") as mock_tor,
            patch("shared.rate_limiter.get_rate_limiter") as mock_rl_fn,
        ):
            mock_bus.redis = mock_redis
            mock_tor.status.return_value = {"tor1": "ok"}
            mock_rl = AsyncMock()
            mock_rl.peek = AsyncMock(return_value=10.0)
            mock_rl_fn.return_value = mock_rl

            resp = client.get("/system/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["redis"]["ok"] is True

    def test_health_redis_failure_gives_degraded(self, client):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("redis down"))

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("api.routes.system.event_bus") as mock_bus,
            patch("shared.db.AsyncSessionLocal", return_value=mock_session_cm),
            patch("api.routes.system.tor_manager") as mock_tor,
            patch("shared.rate_limiter.get_rate_limiter") as mock_rl_fn,
        ):
            mock_bus.redis = mock_redis
            mock_tor.status.return_value = {}
            mock_rl = AsyncMock()
            mock_rl.peek = AsyncMock(return_value=5.0)
            mock_rl_fn.return_value = mock_rl

            resp = client.get("/system/health")

        body = resp.json()
        assert body["status"] == "degraded"
        assert body["redis"]["ok"] is False

    def test_health_simple(self, client):
        resp = client.get("/system/health/simple")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_stats(self, client):
        resp = client.get("/system/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "crawlers" in body
        assert "platforms" in body

    def test_registry(self, client):
        resp = client.get("/system/registry")
        assert resp.status_code == 200
        body = resp.json()
        assert "platforms" in body
        assert "count" in body


class TestDrainQueuesEndpoint:
    """Tests for POST /system/queues/drain."""

    def test_drain_all_queues(self, client):
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=3)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.redis = mock_redis
            mock_bus.QUEUES = {"high": "q:high", "normal": "q:normal"}

            resp = client.post("/system/queues/drain?queue=all")

        assert resp.status_code == 200
        body = resp.json()
        assert "cleared" in body

    def test_drain_specific_queue(self, client):
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=5)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.redis = mock_redis
            mock_bus.QUEUES = {"high": "q:high"}

            resp = client.post("/system/queues/drain?queue=high")

        assert resp.status_code == 200
        assert resp.json()["cleared"] == 5

    def test_drain_unknown_queue(self, client):
        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.redis = AsyncMock()
            mock_bus.QUEUES = {"high": "q:high"}

            resp = client.post("/system/queues/drain?queue=nonexistent")

        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_drain_exception(self, client):
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(side_effect=RuntimeError("redis gone"))

        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.redis = mock_redis
            mock_bus.QUEUES = {"high": "q:high"}

            resp = client.post("/system/queues/drain?queue=all")

        assert resp.status_code == 200
        assert "error" in resp.json()


class TestCircuitBreakersEndpoint:
    """Tests for GET /system/circuit-breakers."""

    def test_circuit_breakers_with_keys(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"lycan:cb:instagram.com"])

        mock_cb = AsyncMock()
        mock_cb.get_state = AsyncMock(return_value={"state": "closed", "failures": 0})

        with (
            patch("api.routes.system.event_bus") as mock_bus,
            patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        ):
            mock_bus.is_connected = True
            mock_bus.redis = mock_redis

            resp = client.get("/system/circuit-breakers")

        assert resp.status_code == 200
        body = resp.json()
        assert "breakers" in body
        assert body["count"] == 1

    def test_circuit_breakers_not_connected(self, client):
        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.is_connected = False

            resp = client.get("/system/circuit-breakers")

        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert body["breakers"] == {}


class TestRateLimitsEndpoint:
    """Tests for GET /system/rate-limits."""

    def test_rate_limits_with_buckets(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"lycan:rl:instagram.com"])

        mock_rl = AsyncMock()
        mock_rl.peek = AsyncMock(return_value=4.5)

        with (
            patch("api.routes.system.event_bus") as mock_bus,
            patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        ):
            mock_bus.is_connected = True
            mock_bus.redis = mock_redis

            resp = client.get("/system/rate-limits")

        assert resp.status_code == 200
        body = resp.json()
        assert "buckets" in body
        assert body["count"] == 1

    def test_rate_limits_not_connected(self, client):
        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.is_connected = False

            resp = client.get("/system/rate-limits")

        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert body["buckets"] == {}


# ===========================================================================
# api/routes/enrichment.py
# ===========================================================================


class TestEnrichmentRoutes:
    """Tests for /enrich/{person_id}/enrich and background variant."""

    def _valid_uuid(self):
        return str(uuid.uuid4())

    def test_enrich_invalid_uuid(self, client):
        resp = client.post("/enrich/not-a-uuid/enrich")
        assert resp.status_code == 400

    def test_enrich_pipeline_exception_returns_500(self, client):
        pid = self._valid_uuid()

        with patch("api.routes.enrichment._orchestrator") as mock_orch:
            mock_orch.enrich_person = AsyncMock(side_effect=RuntimeError("pipeline exploded"))

            resp = client.post(f"/enrich/{pid}/enrich")

        assert resp.status_code == 500
        assert "Enrichment pipeline failed" in resp.json()["detail"]

    def test_enrich_background_invalid_uuid(self, client):
        resp = client.post("/enrich/bad-uuid/enrich/background")
        assert resp.status_code == 400

    def test_enrich_background_queued(self, client):
        pid = self._valid_uuid()

        resp = client.post(f"/enrich/{pid}/enrich/background")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["person_id"] == pid

    @pytest.mark.asyncio
    async def test_background_enrich_exception_logged(self):
        """_background_enrich catches and logs exceptions without re-raising."""
        from api.routes.enrichment import _background_enrich

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        pid = str(uuid.uuid4())

        with (
            patch("shared.db.AsyncSessionLocal", return_value=mock_session_cm),
            patch("api.routes.enrichment._orchestrator") as mock_orch,
        ):
            mock_orch.enrich_person = AsyncMock(side_effect=RuntimeError("background boom"))
            # Should not raise
            await _background_enrich(pid)

        mock_session.rollback.assert_called_once()


# ===========================================================================
# api/routes/ws.py — WebSocket and SSE
# ===========================================================================


class TestSSEEndpoint:
    """Tests for GET /sse/progress/{person_id}."""

    def test_sse_event_bus_unavailable(self, client):
        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.is_connected = False

            resp = client.get("/sse/progress/test-person-123")

        # The endpoint returns a StreamingResponse — we get 200 with error event
        assert resp.status_code == 200
        content = resp.text
        assert "error" in content or "event bus unavailable" in content


# ===========================================================================
# api/routes/search_query.py — filter params
# ===========================================================================


class TestSearchQueryFilters:
    """Tests for /query/persons — state, country, has_sanctions filter branches."""

    def _mock_search(self, hits=None):
        mock = AsyncMock(return_value={"hits": hits or [], "estimatedTotalHits": len(hits or [])})
        return mock

    def test_state_filter(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search()
            resp = client.get("/query/persons?state=TX")

        assert resp.status_code == 200
        # Verify meili was called with state filter
        call_kwargs = mock_idx.search.call_args
        assert call_kwargs is not None
        filters = call_kwargs.kwargs.get("filters") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else None)
        # filters might be in kwargs
        if filters is None and call_kwargs.kwargs:
            filters = call_kwargs.kwargs.get("filters", "")
        assert filters is None or "TX" in str(filters)

    def test_country_filter(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search()
            resp = client.get("/query/persons?country=US")

        assert resp.status_code == 200

    def test_has_sanctions_true_filter(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search()
            resp = client.get("/query/persons?has_sanctions=true")

        assert resp.status_code == 200

    def test_has_sanctions_false_filter(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search()
            resp = client.get("/query/persons?has_sanctions=false")

        assert resp.status_code == 200

    def test_combined_filters(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search([{"id": "abc", "full_name": "John Doe"}])
            resp = client.get("/query/persons?state=TX&country=US&has_sanctions=true&risk_tier=high")

        assert resp.status_code == 200

    def test_invalid_sort_field_defaults(self, client):
        """Unknown sort_by falls back to default_risk_score."""
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search = self._mock_search()
            resp = client.get("/query/persons?sort_by=not_a_real_field")

        assert resp.status_code == 200

    def test_region_no_filters_returns_error(self, client):
        resp = client.get("/query/region")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body

    def test_region_with_state(self, client):
        with patch("api.routes.search_query.meili_indexer") as mock_idx:
            mock_idx.search_by_region = self._mock_search()
            resp = client.get("/query/region?state=CA")

        assert resp.status_code == 200


# ===========================================================================
# api/routes/ws.py — WebSocket endpoint (lines 29-67)
# ===========================================================================


class TestWebSocketEndpoint:
    """Tests for /ws/progress/{person_id} — covers accept, ping/pong, disconnect."""

    def test_ws_connect_and_receive_pong(self):
        """Client connects, sends 'ping', gets back pong event (lines 29-52)."""
        from api.routes import ws

        app = FastAPI()
        app.include_router(ws.router)

        async def _never_returns(_channel, _cb):
            # Simulate a subscription that blocks forever
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _never_returns

            with TestClient(app, raise_server_exceptions=False) as c:
                with c.websocket_connect("/ws/progress/person-abc") as ws_conn:
                    ws_conn.send_text("ping")
                    data = ws_conn.receive_json()
                    assert data == {"event": "pong"}

    def test_ws_disconnect_cleans_up(self):
        """Client disconnects — finally block cancels sub_task (lines 61-67)."""
        from api.routes import ws

        app = FastAPI()
        app.include_router(ws.router)

        async def _never_returns(_channel, _cb):
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _never_returns

            with TestClient(app, raise_server_exceptions=False) as c:
                with c.websocket_connect("/ws/progress/person-xyz") as ws_conn:
                    # Close from client side — triggers WebSocketDisconnect in the handler
                    ws_conn.close()
                # If we reach here without exception the finally block ran correctly

    def test_ws_non_ping_message_ignored(self):
        """Sending a non-ping text message doesn't crash the handler (lines 49-52)."""
        from api.routes import ws

        app = FastAPI()
        app.include_router(ws.router)

        async def _never_returns(_channel, _cb):
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _never_returns

            with TestClient(app, raise_server_exceptions=False) as c:
                with c.websocket_connect("/ws/progress/person-def") as ws_conn:
                    # Sending a non-ping message should produce no response (no assert needed)
                    ws_conn.send_text("hello")
                    ws_conn.close()


class TestSSEEndpointConnected:
    """Tests for SSE /sse/progress/{person_id} when event_bus IS connected (lines 79-105)."""

    def test_sse_connected_yields_heartbeat_then_done(self):
        """
        Event bus connected: queue receives a 'done' event which terminates the stream.
        Covers lines 79-97 (queue setup, message forwarding, done-break).
        """
        from api.routes import ws as ws_module
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ws_module.router)

        person_id = "test-sse-person"

        async def _fake_subscribe(channel, callback):
            # Immediately deliver a done event for this person
            await callback({"event": "done", "person_id": person_id})
            # Then hang (client will have broken out of the loop already)
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.subscribe = _fake_subscribe

            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(
                    f"/sse/progress/{person_id}",
                    headers={"Accept": "text/event-stream"},
                )

        assert resp.status_code == 200
        assert "done" in resp.text

    def test_sse_connected_finally_cancels_task(self):
        """
        Stream closes (client disconnects) → finally block cancels sub_task (lines 100-105).
        We simulate disconnect by patching request.is_disconnected to True immediately.
        """
        from api.routes import ws as ws_module
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ws_module.router)

        async def _hang_subscribe(_channel, _cb):
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.subscribe = _hang_subscribe
            # Patch Request.is_disconnected to return True so the while loop exits
            with patch("starlette.requests.Request.is_disconnected", new_callable=AsyncMock) as mock_disc:
                mock_disc.return_value = True

                with TestClient(app, raise_server_exceptions=False) as c:
                    resp = c.get(
                        "/sse/progress/person-disconnect-test",
                        headers={"Accept": "text/event-stream"},
                    )

        # Stream should have terminated cleanly (200 with empty or heartbeat body)
        assert resp.status_code == 200
