"""
Tests for modules/pipeline/pivot_enricher.py

Covers:
- _extract_pivots: valid email is extracted
- _extract_pivots: valid phone is extracted
- _extract_pivots: valid full_name is extracted
- _extract_pivots: platform/consent keywords are rejected for full_name
- _extract_pivots: results capped at _MAX_PIVOTS (3)
- _extract_pivots: single-word names are rejected
- pivot_from_result returns 0 when data produces no pivots
- pivot_from_result skips identifiers already known for the person
- pivot_from_result queues jobs for new identifiers
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.pipeline.pivot_enricher import _extract_pivots, pivot_from_result

# ---------------------------------------------------------------------------
# Unit tests for _extract_pivots (pure function, no async)
# ---------------------------------------------------------------------------


def test_extract_pivots_valid_email_from_list():
    data = {"emails": ["alice@example.com", "secondary@test.org"]}
    result = _extract_pivots(data)
    emails = [v for t, v in result if t == "email"]
    assert emails == ["alice@example.com", "secondary@test.org"]


def test_extract_pivots_direct_email_field_extracted():
    # After operator precedence fix, direct "email" key is extracted correctly.
    data = {"email": "alice@example.com"}
    result = _extract_pivots(data)
    emails = [v for t, v in result if t == "email"]
    assert emails == ["alice@example.com"]


def test_extract_pivots_valid_phone():
    data = {"phone": "+1-555-867-5309"}
    result = _extract_pivots(data)
    phones = [v for t, v in result if t == "phone"]
    assert len(phones) == 1
    assert phones[0] == "+1-555-867-5309"


def test_extract_pivots_phone_list_fields():
    data = {
        "phone_numbers": ["+1-555-867-5309", "(212) 555-0100"],
        "associated_phones": ["+1-555-867-5309", "123"],
    }
    result = _extract_pivots(data)
    phones = [v for t, v in result if t == "phone"]
    assert phones == ["+1-555-867-5309", "(212) 555-0100"]


def test_extract_pivots_phone_too_short_rejected():
    data = {"phone": "123"}
    result = _extract_pivots(data)
    phones = [v for t, v in result if t == "phone"]
    assert phones == []


def test_extract_pivots_valid_full_name():
    data = {"full_name": "John Smith"}
    result = _extract_pivots(data)
    names = [v for t, v in result if t == "full_name"]
    assert names == ["John Smith"]


def test_extract_pivots_single_word_name_rejected():
    data = {"full_name": "Madonna"}
    result = _extract_pivots(data)
    names = [v for t, v in result if t == "full_name"]
    assert names == []


def test_extract_pivots_platform_keyword_in_name_rejected():
    data = {"full_name": "Instagram User"}
    result = _extract_pivots(data)
    names = [v for t, v in result if t == "full_name"]
    assert names == []


def test_extract_pivots_consent_keyword_in_name_rejected():
    data = {"full_name": "Continue Privacy"}
    result = _extract_pivots(data)
    names = [v for t, v in result if t == "full_name"]
    assert names == []


def test_extract_pivots_all_returned():
    """All extracted pivot types are returned — no cap inside _extract_pivots."""
    data = {
        "email": "test@example.com",
        "phone": "+27831234567",
        "full_name": "Alice Wonderland",
    }
    result = _extract_pivots(data)
    assert len(result) == 3


def test_extract_pivots_empty_data():
    result = _extract_pivots({})
    assert result == []


def test_email_extraction_operator_precedence():
    """emails list should be used when other email fields absent."""
    data = {"emails": ["test@example.com", "other@example.com"]}
    pivots = _extract_pivots(data)
    emails = [p for p in pivots if p[0] == "email"]
    assert emails == [("email", "test@example.com"), ("email", "other@example.com")]


def test_email_extraction_direct_field_wins():
    """data.get('email') should win over emails list."""
    data = {"email": "direct@example.com", "emails": ["list@example.com"]}
    pivots = _extract_pivots(data)
    emails = [p for p in pivots if p[0] == "email"]
    assert emails[0][1] == "direct@example.com"
    assert ("email", "list@example.com") in emails


def test_extract_pivots_returns_all_types_not_capped():
    """_extract_pivots must not cap results — that's the caller's job."""
    data = {
        "email": "a@b.com",
        "phone": "+15551234567",
        "username": "johndoe",
        "full_name": "John Doe",
    }
    pivots = _extract_pivots(data)
    assert len(pivots) == 3  # email + phone + full_name (username field not a pivot type)


def test_instagram_handle_pivot():
    data = {"instagram": "johndoe"}
    pivots = _extract_pivots(data)
    handles = [p for p in pivots if p[0] == "instagram_handle"]
    assert len(handles) == 1


def test_twitter_handle_pivot():
    data = {"twitter": "@janesmith"}
    pivots = _extract_pivots(data)
    handles = [p for p in pivots if p[0] == "twitter_handle"]
    assert len(handles) == 1
    assert handles[0][1] == "janesmith"  # @ stripped


def test_linkedin_url_pivot():
    data = {"linkedin": "https://linkedin.com/in/johndoe"}
    pivots = _extract_pivots(data)
    links = [p for p in pivots if p[0] == "linkedin_url"]
    assert len(links) == 1


def test_domain_pivot():
    data = {"website": "example.com"}
    pivots = _extract_pivots(data)
    domains = [p for p in pivots if p[0] == "domain"]
    assert len(domains) == 1


def test_max_jobs_per_call_cap_applied_in_caller():
    """The cap must be applied at dispatch level, not in _extract_pivots."""
    import inspect

    import modules.pipeline.pivot_enricher as m

    src = inspect.getsource(m._extract_pivots)
    assert "found[:" not in src


# ---------------------------------------------------------------------------
# Async tests for pivot_from_result
# ---------------------------------------------------------------------------


def _make_mock_session(existing=None):
    """Return an AsyncSessionLocal mock context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing
    mock_session.execute = AsyncMock(return_value=scalar_result)
    return mock_session


@pytest.mark.asyncio
async def test_pivot_from_result_returns_zero_for_empty_data():
    count = await pivot_from_result("00000000-0000-0000-0000-000000000001", "instagram", {})
    assert count == 0


@pytest.mark.asyncio
async def test_pivot_from_result_returns_zero_when_no_valid_pivots():
    data = {"full_name": "Instagram"}  # single word — rejected
    count = await pivot_from_result("00000000-0000-0000-0000-000000000001", "instagram", data)
    assert count == 0


@pytest.mark.asyncio
async def test_pivot_from_result_skips_existing_identifier():
    """If the identifier already exists in DB, no jobs should be dispatched."""
    # Use a list-based emails key so the email is actually extracted
    data = {"emails": ["known@example.com"]}

    mock_session = _make_mock_session(existing=MagicMock())  # simulate existing record
    mock_dispatch = AsyncMock()

    import sys

    fake_registry = MagicMock()
    fake_registry.CRAWLER_REGISTRY = {"email_breach": True}
    fake_dispatcher = MagicMock()
    fake_dispatcher.dispatch_job = mock_dispatch

    with patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=mock_session):
        orig_reg = sys.modules.get("modules.crawlers.registry")
        orig_dis = sys.modules.get("modules.dispatcher.dispatcher")
        sys.modules["modules.crawlers.registry"] = fake_registry
        sys.modules["modules.dispatcher.dispatcher"] = fake_dispatcher
        try:
            count = await pivot_from_result("00000000-0000-0000-0000-000000000002", "twitter", data)
        finally:
            if orig_reg is not None:
                sys.modules["modules.crawlers.registry"] = orig_reg
            else:
                sys.modules.pop("modules.crawlers.registry", None)
            if orig_dis is not None:
                sys.modules["modules.dispatcher.dispatcher"] = orig_dis
            else:
                sys.modules.pop("modules.dispatcher.dispatcher", None)

    # identifier already exists → 0 jobs queued
    assert count == 0
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pivot_from_result_queues_jobs_for_new_identifier():
    """New identifier not in DB → dispatch_job called for each matching platform."""
    data = {"emails": ["new@example.com"]}

    mock_session = _make_mock_session(existing=None)  # not in DB
    mock_dispatch = AsyncMock()

    registry = {"email_breach": True, "email_holehe": True, "email_mx_validator": True}

    import sys

    fake_registry = MagicMock()
    fake_registry.CRAWLER_REGISTRY = registry
    fake_dispatcher = MagicMock()
    fake_dispatcher.dispatch_job = mock_dispatch

    with patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=mock_session):
        orig_reg = sys.modules.get("modules.crawlers.registry")
        orig_dis = sys.modules.get("modules.dispatcher.dispatcher")
        sys.modules["modules.crawlers.registry"] = fake_registry
        sys.modules["modules.dispatcher.dispatcher"] = fake_dispatcher
        try:
            count = await pivot_from_result(
                "00000000-0000-0000-0000-000000000003", "instagram", data
            )
        finally:
            if orig_reg is not None:
                sys.modules["modules.crawlers.registry"] = orig_reg
            else:
                sys.modules.pop("modules.crawlers.registry", None)
            if orig_dis is not None:
                sys.modules["modules.dispatcher.dispatcher"] = orig_dis
            else:
                sys.modules.pop("modules.dispatcher.dispatcher", None)

    assert count == len(registry)
    assert mock_dispatch.await_count == len(registry)
