"""
test_marketing_wave6.py — Coverage for api/routes/marketing.py

Targets:
  lines 196-198: trigger_batch_tagging — exception path raises HTTPException 500
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.marketing import router

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/marketing")
    return app


# ---------------------------------------------------------------------------
# lines 196-198: trigger_batch_tagging exception branch
# ---------------------------------------------------------------------------


def test_trigger_batch_tagging_exception_returns_500():
    """Lines 196-198: _run_batch raises → HTTPException(500)."""
    from api.deps import db_session

    app = _make_app()

    mock_session = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[db_session] = _override

    with patch(
        "api.routes.marketing._commercial_daemon._run_batch",
        new=AsyncMock(side_effect=RuntimeError("tagger exploded")),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/marketing/tags/batch")

    assert response.status_code == 500
    assert "Batch tagging error" in response.text


def test_trigger_batch_tagging_success_returns_triggered():
    """Happy path: _run_batch succeeds → {triggered: true}."""
    from api.deps import db_session

    app = _make_app()

    mock_session = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[db_session] = _override

    with patch(
        "api.routes.marketing._commercial_daemon._run_batch",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(app)
        response = client.post("/marketing/tags/batch")

    assert response.status_code == 200
    assert response.json()["triggered"] is True
