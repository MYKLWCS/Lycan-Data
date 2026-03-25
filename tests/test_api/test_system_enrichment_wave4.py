"""
test_system_enrichment_wave4.py — Coverage wave 4 for system.py and enrichment.py.

Targets uncovered lines:
  system.py:
    - 71-72  : rate_limiter exception path inside /health
    - 196-198: circuit-breakers endpoint exception path
    - 225-227: rate-limits endpoint exception path

  enrichment.py:
    - 55     : session.rollback() inside _background_enrich exception handler
                (line 55 is the rollback call; wave3 has the test but may not
                 actually cover the async rollback due to mock wiring — this
                 file ensures it is hit)
    - 97-99  : enrich_person_background exception path → HTTP 500
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal app — avoids importing api.main (static files + DB lifespan)
# ---------------------------------------------------------------------------


def _make_app():
    from api.routes import enrichment, system

    app = FastAPI()
    app.include_router(system.router, prefix="/system")
    app.include_router(enrichment.router, prefix="/enrich")
    return app


@pytest.fixture(scope="module")
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# system.py — /health rate-limiter exception (lines 71-72)
# ===========================================================================


class TestHealthRateLimiterException:
    """Rate-limiter probe fails — health still returns 200 with ok=False entry."""

    def test_health_rate_limiter_exception(self, client):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        mock_rl = AsyncMock()
        mock_rl.peek = AsyncMock(side_effect=RuntimeError("rate-limiter exploded"))

        with (
            patch("api.routes.system.event_bus") as mock_bus,
            patch("shared.db.AsyncSessionLocal", return_value=mock_session_cm),
            patch("api.routes.system.tor_manager") as mock_tor,
            patch("api.routes.system.get_rate_limiter", return_value=mock_rl),
        ):
            mock_bus.redis = mock_redis
            mock_tor.status.return_value = {}

            resp = client.get("/system/health")

        assert resp.status_code == 200
        body = resp.json()
        # Lines 71-72: rate_limiter dict with ok=False and error key
        assert body["rate_limiter"]["ok"] is False
        assert "error" in body["rate_limiter"]


# ===========================================================================
# system.py — /circuit-breakers exception path (lines 196-198)
# ===========================================================================


class TestCircuitBreakersException:
    """Redis keys() call raises — endpoint returns error dict, not 500."""

    def test_circuit_breakers_redis_exception(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(side_effect=RuntimeError("redis keys exploded"))

        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.redis = mock_redis

            resp = client.get("/system/circuit-breakers")

        assert resp.status_code == 200
        body = resp.json()
        # Lines 196-198: exception logged, returns {"error": ..., "breakers": {}}
        assert "error" in body
        assert body["breakers"] == {}


# ===========================================================================
# system.py — /rate-limits exception path (lines 225-227)
# ===========================================================================


class TestRateLimitsException:
    """Redis keys() call raises — endpoint returns error dict, not 500."""

    def test_rate_limits_redis_exception(self, client):
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(side_effect=RuntimeError("redis keys exploded"))

        with patch("api.routes.system.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.redis = mock_redis

            resp = client.get("/system/rate-limits")

        assert resp.status_code == 200
        body = resp.json()
        # Lines 225-227: exception logged, returns {"error": ..., "buckets": {}}
        assert "error" in body
        assert body["buckets"] == {}


# ===========================================================================
# enrichment.py — _background_enrich rollback (line 55)
# ===========================================================================


@pytest.mark.asyncio
async def test_background_enrich_rollback_called():
    """Line 55: session.rollback() is called when _orchestrator raises."""
    from api.routes.enrichment import _background_enrich

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    pid = str(uuid.uuid4())

    with (
        patch("api.routes.enrichment._orchestrator") as mock_orch,
        patch("shared.db.AsyncSessionLocal", return_value=mock_cm),
    ):
        mock_orch.enrich_person = AsyncMock(side_effect=RuntimeError("pipeline crash"))
        # Must not raise — the function swallows the exception
        await _background_enrich(pid)

    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_not_called()


# ===========================================================================
# enrichment.py — enrich_person_background exception path (lines 97-99)
# ===========================================================================


class TestEnrichBackgroundException:
    """Lines 97-99: background_tasks.add_task raises → HTTP 500."""

    def test_enrich_background_add_task_raises(self, client):
        pid = str(uuid.uuid4())

        # Patch BackgroundTasks.add_task to raise so we hit the except block
        with patch(
            "fastapi.BackgroundTasks.add_task",
            side_effect=RuntimeError("background tasks broken"),
        ):
            resp = client.post(f"/enrich/{pid}/enrich/background")

        assert resp.status_code == 500
        assert "Failed to queue enrichment" in resp.json()["detail"]
