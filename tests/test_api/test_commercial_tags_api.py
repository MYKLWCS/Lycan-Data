"""API tests for Phase 4 commercial tags endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import db_session
from api.main import app


def _make_session():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


@pytest.mark.asyncio
async def test_tags_summary_returns_dict():
    """GET /marketing/tags/summary returns {tag: count} dict."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_rows = [
        MagicMock(tag="auto_loan_candidate", cnt=5),
        MagicMock(tag="insurance_auto", cnt=3),
    ]
    mock_result = MagicMock()
    mock_result.all.return_value = mock_rows
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/marketing/tags/summary")
    finally:
        app.dependency_overrides.pop(db_session, None)

    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert isinstance(data["summary"], dict)


@pytest.mark.asyncio
async def test_tags_batch_triggers_run():
    """POST /marketing/tags/batch triggers daemon batch and returns processed count."""
    mock_session = _make_session()

    async def override():
        yield mock_session

    app.dependency_overrides[db_session] = override

    try:
        with patch(
            "api.routes.marketing._commercial_daemon._run_batch",
            new_callable=AsyncMock,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/marketing/tags/batch")
    finally:
        app.dependency_overrides.pop(db_session, None)

    assert resp.status_code == 200
    assert "triggered" in resp.json()
