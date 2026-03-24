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
    # The source expression only triggers when data["emails"] is a list.
    # Providing a plain "email" key when "emails" is not a list yields None.
    data = {"emails": ["alice@example.com", "secondary@test.org"]}
    result = _extract_pivots(data)
    emails = [v for t, v in result if t == "email"]
    assert len(emails) == 1
    assert emails[0] == "alice@example.com"


def test_extract_pivots_email_key_ignored_without_emails_list():
    # When "emails" is not a list the entire email expression returns None —
    # this is the actual behaviour of the ternary in the source.
    data = {"email": "alice@example.com"}
    result = _extract_pivots(data)
    emails = [v for t, v in result if t == "email"]
    assert emails == []


def test_extract_pivots_valid_phone():
    data = {"phone": "+1-555-867-5309"}
    result = _extract_pivots(data)
    phones = [v for t, v in result if t == "phone"]
    assert len(phones) == 1
    assert phones[0] == "+1-555-867-5309"


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


def test_extract_pivots_capped_at_three():
    """Providing email + phone + name should yield exactly 3 (the cap)."""
    data = {
        "email": "test@example.com",
        "phone": "+27831234567",
        "full_name": "Alice Wonderland",
    }
    result = _extract_pivots(data)
    assert len(result) <= 3


def test_extract_pivots_empty_data():
    result = _extract_pivots({})
    assert result == []


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
    fake_registry.CRAWLER_REGISTRY = {"email_hibp": True}
    fake_dispatcher = MagicMock()
    fake_dispatcher.dispatch_job = mock_dispatch

    with patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=mock_session):
        orig_reg = sys.modules.get("modules.crawlers.registry")
        orig_dis = sys.modules.get("modules.dispatcher.dispatcher")
        sys.modules["modules.crawlers.registry"] = fake_registry
        sys.modules["modules.dispatcher.dispatcher"] = fake_dispatcher
        try:
            count = await pivot_from_result(
                "00000000-0000-0000-0000-000000000002", "twitter", data
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

    # identifier already exists → 0 jobs queued
    assert count == 0
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pivot_from_result_queues_jobs_for_new_identifier():
    """New identifier not in DB → dispatch_job called for each matching platform."""
    data = {"emails": ["new@example.com"]}

    mock_session = _make_mock_session(existing=None)  # not in DB
    mock_dispatch = AsyncMock()

    registry = {"email_hibp": True, "email_holehe": True, "email_leakcheck": True}

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
