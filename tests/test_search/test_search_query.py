"""Tests for api/routes/search_query.py — mocking meili_indexer."""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from api.main import app


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


_SEARCH_RESULT = {
    "hits": [{"id": "abc123", "full_name": "John Smith"}],
    "estimatedTotalHits": 1,
}


# ─── /search/persons ──────────────────────────────────────────────────────────


def test_search_persons_basic(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        resp = client.get("/query/persons", params={"q": "John Smith"})
    assert resp.status_code == 200
    mock_search.assert_called_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["query"] == "John Smith"


def test_search_persons_risk_tier_filter(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"risk_tier": "high_risk"})
    filters = mock_search.call_args.kwargs.get("filters", "")
    assert "high_risk" in (filters or "")


def test_search_persons_city_filter(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"city": "Austin"})
    filters = mock_search.call_args.kwargs.get("filters", "")
    assert "Austin" in (filters or "")


def test_search_persons_has_darkweb_true(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"has_darkweb": "true"})
    filters = mock_search.call_args.kwargs.get("filters", "")
    assert "has_darkweb = true" in (filters or "")


def test_search_persons_has_darkweb_false(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"has_darkweb": "false"})
    filters = mock_search.call_args.kwargs.get("filters", "")
    assert "has_darkweb = false" in (filters or "")


def test_search_persons_sort_asc(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"sort_by": "created_at", "sort_dir": "asc"})
    sort = mock_search.call_args.kwargs.get("sort", [])
    assert sort == ["created_at:asc"]


def test_search_persons_invalid_sort_field_defaults(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"sort_by": "injected_field"})
    sort = mock_search.call_args.kwargs.get("sort", [])
    assert sort == ["default_risk_score:desc"]


def test_search_persons_pagination(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"limit": 50, "offset": 100})
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["limit"] == 50
    assert call_kwargs["offset"] == 100


def test_search_persons_no_filters_passes_none(client):
    with patch("modules.search.meili_indexer.meili_indexer.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _SEARCH_RESULT
        client.get("/query/persons", params={"q": "test"})
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["filters"] is None


# ─── /search/region ───────────────────────────────────────────────────────────


def test_search_region_no_params_returns_error(client):
    resp = client.get("/query/region")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_search_region_with_city(client):
    with patch("modules.search.meili_indexer.meili_indexer.search_by_region", new_callable=AsyncMock) as mock_region:
        mock_region.return_value = _SEARCH_RESULT
        resp = client.get("/query/region", params={"city": "Dallas"})
    assert resp.status_code == 200
    mock_region.assert_called_once()
    call_kwargs = mock_region.call_args.kwargs
    assert call_kwargs["city"] == "Dallas"


def test_search_region_with_state_and_country(client):
    with patch("modules.search.meili_indexer.meili_indexer.search_by_region", new_callable=AsyncMock) as mock_region:
        mock_region.return_value = _SEARCH_RESULT
        client.get("/query/region", params={"state": "TX", "country": "US"})
    call_kwargs = mock_region.call_args.kwargs
    assert call_kwargs["state"] == "TX"
    assert call_kwargs["country"] == "US"


def test_search_region_sort_validation(client):
    with patch("modules.search.meili_indexer.meili_indexer.search_by_region", new_callable=AsyncMock) as mock_region:
        mock_region.return_value = _SEARCH_RESULT
        client.get("/query/region", params={"city": "Austin", "sort_by": "INVALID"})
    sort = mock_region.call_args.kwargs.get("sort", [])
    assert sort == ["default_risk_score:desc"]
