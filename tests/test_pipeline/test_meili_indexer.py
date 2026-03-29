"""
Tests for modules/search/meili_indexer.py

Covers:
- build_person_doc returns correctly shaped document
- build_person_doc applies sensible defaults for missing fields
- MeiliIndexer.setup_index returns True on success (202)
- MeiliIndexer.index_person returns True on success (202)
- MeiliIndexer.index_many returns True for empty list without HTTP call
- MeiliIndexer.search returns response dict on 200
- MeiliIndexer.search returns empty fallback on non-200
- MeiliIndexer.search_by_region builds correct filter string
- MeiliIndexer.delete_person returns True on 202
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.meili_indexer import MeiliIndexer, build_person_doc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, body: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {}
    return resp


def _make_indexer() -> MeiliIndexer:
    """Return a MeiliIndexer with known base/key (no real settings needed)."""
    with patch("modules.search.typesense_indexer.settings") as mock_settings:
        mock_settings.typesense_url = "http://localhost:7700"
        mock_settings.typesense_api_key = "testkey"
        return MeiliIndexer()


# ---------------------------------------------------------------------------
# build_person_doc — pure function tests
# ---------------------------------------------------------------------------


def test_build_person_doc_minimal():
    doc = build_person_doc(person_id="abc-123")
    assert doc["id"] == "abc-123"
    assert doc["full_name"] == ""
    assert doc["phones"] == []
    assert doc["emails"] == []
    assert doc["platform_count"] == 0
    assert doc["risk_tier"] == "unknown"
    assert doc["wealth_band"] == "unknown"
    assert doc["has_darkweb"] is False
    assert doc["has_sanctions"] is False
    assert doc["verification_status"] == "unverified"


def test_build_person_doc_with_platforms():
    doc = build_person_doc(
        person_id="xyz",
        platforms=["instagram", "twitter", "linkedin"],
        full_name="Alice Smith",
        emails=["alice@example.com"],
        phones=["+1-555-0100"],
        risk_tier="medium",
        has_darkweb=True,
    )
    assert doc["platform_count"] == 3
    assert doc["full_name"] == "Alice Smith"
    assert doc["has_darkweb"] is True
    assert doc["risk_tier"] == "medium"
    assert "alice@example.com" in doc["emails"]


def test_build_person_doc_extra_kwargs_passed_through():
    doc = build_person_doc(person_id="p1", custom_field="custom_value")
    assert doc["custom_field"] == "custom_value"


def test_build_person_doc_risk_score_defaults_to_zero():
    doc = build_person_doc(person_id="p2", default_risk_score=None)
    assert doc["default_risk_score"] == 0.0


# ---------------------------------------------------------------------------
# MeiliIndexer HTTP method tests — all HTTP is mocked via httpx.AsyncClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_index_returns_true_on_202():
    indexer = _make_indexer()
    post_resp = _mock_response(202)
    patch_resp = _mock_response(202)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=post_resp)
    mock_client.patch = AsyncMock(return_value=patch_resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.setup_index()

    assert result is True


@pytest.mark.asyncio
async def test_setup_index_returns_false_on_server_error():
    indexer = _make_indexer()
    post_resp = _mock_response(500)
    patch_resp = _mock_response(500)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=post_resp)
    mock_client.patch = AsyncMock(return_value=patch_resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.setup_index()

    assert result is False


@pytest.mark.asyncio
async def test_index_person_returns_true_on_202():
    indexer = _make_indexer()
    resp = _mock_response(202)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.index_person({"id": "p1", "full_name": "Bob"})

    assert result is True
    # Verify the document was sent (Typesense upserts single documents)
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"] == {"id": "p1", "full_name": "Bob"}


@pytest.mark.asyncio
async def test_index_many_empty_list_returns_true_without_http():
    indexer = _make_indexer()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock()

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.index_many([])

    assert result is True
    mock_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_many_sends_batch():
    indexer = _make_indexer()
    docs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    resp = _mock_response(200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.index_many(docs)

    assert result is True
    # Typesense uses JSONL import, so content is sent as text
    call_kwargs = mock_client.post.call_args.kwargs
    assert "content" in call_kwargs


@pytest.mark.asyncio
async def test_search_returns_response_on_200():
    indexer = _make_indexer()
    # Typesense wraps hits in {"document": ...}
    ts_response = {"hits": [{"document": {"id": "p1"}}], "found": 1}
    resp = _mock_response(200, ts_response)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.search("alice")

    assert result["hits"] == [{"id": "p1"}]
    assert result["estimatedTotalHits"] == 1


@pytest.mark.asyncio
async def test_search_returns_empty_fallback_on_non_200():
    indexer = _make_indexer()
    resp = _mock_response(503)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.search("broken")

    assert result["hits"] == []
    assert result["estimatedTotalHits"] == 0
    assert result["query"] == "broken"


@pytest.mark.asyncio
async def test_search_by_region_builds_filter():
    indexer = _make_indexer()
    ts_response = {"hits": [], "found": 0}
    resp = _mock_response(200, ts_response)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        await indexer.search_by_region(city="Dallas", state="TX", country="US")

    params = mock_client.get.call_args.kwargs["params"]
    assert "filter_by" in params
    assert "city:='Dallas'" in params["filter_by"]
    assert "state_province:='TX'" in params["filter_by"]
    assert "country:='US'" in params["filter_by"]


@pytest.mark.asyncio
async def test_delete_person_returns_true_on_202():
    indexer = _make_indexer()
    resp = _mock_response(202)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.delete = AsyncMock(return_value=resp)

    with patch("modules.search.typesense_indexer.httpx.AsyncClient", return_value=mock_client):
        result = await indexer.delete_person("person-abc")

    assert result is True
    # Confirm the URL includes the person_id
    url = mock_client.delete.call_args.args[0]
    assert "person-abc" in url
