"""
test_pivot_enricher_wave3.py — Targeted coverage for pivot_enricher.py lines
139-140, 146-149, 154-224.

Lines breakdown:
  139-140  Instagram handle extraction (ig branch)
  144-146  Twitter handle extraction (tw branch)
  148-151  LinkedIn URL extraction (li branch)
  154-156  Domain extraction (domain branch)
  161-224  pivot_from_result async body:
           – 182-183  _MAX_JOBS_PER_CALL cap → break
           – 197-198  existing identifier → continue
           – 200-212  platforms loop (registry miss → continue; dispatch called)
           – 214-222  logger.info when queued_for_this > 0

All DB operations mocked with AsyncMock. No real DB connection required.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.pipeline.pivot_enricher import _extract_pivots, pivot_from_result

# ---------------------------------------------------------------------------
# _extract_pivots — lines 139-156
# ---------------------------------------------------------------------------


def test_extract_pivots_instagram_field():
    """Line 139-140: ig = data.get('instagram') path."""
    pivots = _extract_pivots({"instagram": "testuser"})
    handles = [v for t, v in pivots if t == "instagram_handle"]
    assert handles == ["testuser"]


def test_extract_pivots_instagram_handle_field():
    """Line 139: instagram_handle alternate key."""
    pivots = _extract_pivots({"instagram_handle": "@testuser"})
    handles = [v for t, v in pivots if t == "instagram_handle"]
    assert handles == ["testuser"]  # @ stripped, lowercased


def test_extract_pivots_instagram_username_field():
    """Line 139: instagram_username alternate key."""
    pivots = _extract_pivots({"instagram_username": "TESTUSER"})
    handles = [v for t, v in pivots if t == "instagram_handle"]
    assert handles == ["testuser"]


def test_extract_pivots_no_instagram():
    """Line 140: ig is falsy — no instagram_handle appended."""
    pivots = _extract_pivots({"email": "x@example.com"})
    handles = [v for t, v in pivots if t == "instagram_handle"]
    assert handles == []


def test_extract_pivots_twitter_field():
    """Line 144-146: tw = data.get('twitter') path."""
    pivots = _extract_pivots({"twitter": "@jdoe"})
    handles = [v for t, v in pivots if t == "twitter_handle"]
    assert handles == ["jdoe"]


def test_extract_pivots_twitter_handle_field():
    """Line 144: twitter_handle alternate key."""
    pivots = _extract_pivots({"twitter_handle": "JDOE"})
    handles = [v for t, v in pivots if t == "twitter_handle"]
    assert handles == ["jdoe"]


def test_extract_pivots_twitter_username_field():
    """Line 144: twitter_username alternate key."""
    pivots = _extract_pivots({"twitter_username": "@JDoe"})
    handles = [v for t, v in pivots if t == "twitter_handle"]
    assert handles == ["jdoe"]


def test_extract_pivots_no_twitter():
    """Line 145: tw is falsy — no twitter_handle appended."""
    pivots = _extract_pivots({"phone": "+15551234567"})
    handles = [v for t, v in pivots if t == "twitter_handle"]
    assert handles == []


def test_extract_pivots_linkedin_field():
    """Line 148-151: li = data.get('linkedin') path."""
    pivots = _extract_pivots({"linkedin": "https://linkedin.com/in/jdoe"})
    links = [v for t, v in pivots if t == "linkedin_url"]
    assert links == ["https://linkedin.com/in/jdoe"]


def test_extract_pivots_linkedin_url_field():
    """Line 148: linkedin_url alternate key."""
    pivots = _extract_pivots({"linkedin_url": "https://linkedin.com/in/foo"})
    links = [v for t, v in pivots if t == "linkedin_url"]
    assert len(links) == 1


def test_extract_pivots_linkedin_profile_field():
    """Line 148: linkedin_profile alternate key."""
    pivots = _extract_pivots({"linkedin_profile": "https://linkedin.com/in/bar"})
    links = [v for t, v in pivots if t == "linkedin_url"]
    assert len(links) == 1


def test_extract_pivots_no_linkedin():
    """Line 149: li is falsy — no linkedin_url appended."""
    pivots = _extract_pivots({"email": "x@example.com"})
    links = [v for t, v in pivots if t == "linkedin_url"]
    assert links == []


def test_extract_pivots_domain_field():
    """Line 154-156: domain = data.get('domain') with dot present."""
    pivots = _extract_pivots({"domain": "example.com"})
    domains = [v for t, v in pivots if t == "domain"]
    assert domains == ["example.com"]


def test_extract_pivots_website_field():
    """Line 154: website alternate key."""
    pivots = _extract_pivots({"website": "https://example.com"})
    domains = [v for t, v in pivots if t == "domain"]
    assert len(domains) == 1


def test_extract_pivots_url_field():
    """Line 154: url alternate key."""
    pivots = _extract_pivots({"url": "https://example.org/path"})
    domains = [v for t, v in pivots if t == "domain"]
    assert len(domains) == 1


def test_extract_pivots_domain_no_dot_rejected():
    """Line 155: domain without '.' is not appended."""
    pivots = _extract_pivots({"domain": "localhost"})
    domains = [v for t, v in pivots if t == "domain"]
    assert domains == []


def test_extract_pivots_domain_lowercased():
    """Line 156: domain value is lowercased."""
    pivots = _extract_pivots({"domain": "EXAMPLE.COM"})
    domains = [v for t, v in pivots if t == "domain"]
    assert domains == ["example.com"]


def test_extract_pivots_all_seven_types():
    """All seven pivot types returned from a single data dict."""
    data = {
        "email": "a@b.com",
        "phone": "+15551234567",
        "full_name": "John Smith",
        "instagram": "jsmith",
        "twitter": "jsmith",
        "linkedin": "https://linkedin.com/in/jsmith",
        "domain": "jsmith.com",
    }
    pivots = _extract_pivots(data)
    types = [t for t, _ in pivots]
    assert "email" in types
    assert "phone" in types
    assert "full_name" in types
    assert "instagram_handle" in types
    assert "twitter_handle" in types
    assert "linkedin_url" in types
    assert "domain" in types
    assert len(pivots) == 7


# ---------------------------------------------------------------------------
# Helpers for pivot_from_result
# ---------------------------------------------------------------------------


def _make_session(existing=None):
    """Build a mock AsyncSessionLocal context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=scalar_result)
    return session


def _sys_modules_patch(registry_dict, dispatch_mock):
    """Return dict for patch.dict(sys.modules, ...) with fake registry + dispatcher."""
    fake_reg = MagicMock()
    fake_reg.CRAWLER_REGISTRY = registry_dict
    fake_dis = MagicMock()
    fake_dis.dispatch_job = dispatch_mock
    return {
        "modules.crawlers.registry": fake_reg,
        "modules.dispatcher.dispatcher": fake_dis,
    }


# ---------------------------------------------------------------------------
# pivot_from_result — lines 161-224
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pivot_no_pivots_returns_zero():
    """Lines 173-175: no pivots → returns 0 immediately (no DB hit)."""
    count = await pivot_from_result("00000000-0000-0000-0000-000000000001", "instagram", {})
    assert count == 0


@pytest.mark.asyncio
async def test_pivot_person_id_as_uuid_string():
    """Line 177: person_id str → uuid.UUID conversion."""
    data = {"domain": "new-domain.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"domain_whois": True}, mock_dispatch),
        ),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000002", "test_platform", data
        )

    assert count >= 1


@pytest.mark.asyncio
async def test_pivot_existing_identifier_skipped():
    """Lines 197-198: existing identifier in DB → continue, no dispatch."""
    data = {"email": "known@example.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=MagicMock())  # record exists

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"email_hibp": True}, mock_dispatch),
        ),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000003", "test_platform", data
        )

    assert count == 0
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pivot_platform_not_in_registry_skipped():
    """Lines 203-204: platform not in CRAWLER_REGISTRY → continue."""
    # email platforms list includes email_hibp, email_holehe, etc.
    # We only put email_hibp in registry — rest are skipped
    data = {"email": "new@example.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"email_hibp": True}, mock_dispatch),
        ),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000004", "test_platform", data
        )

    # Only email_hibp is in registry; email_holehe, etc. are skipped
    assert count == 1
    mock_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_pivot_queues_all_registered_platforms():
    """Lines 200-212: all platforms in registry get dispatched, count returned."""
    data = {"email": "fresh@example.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    registry = {
        "email_hibp": True,
        "email_holehe": True,
        "email_leakcheck": True,
        "email_emailrep": True,
        "darkweb_ahmia": True,
        "paste_pastebin": True,
    }

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict("sys.modules", _sys_modules_patch(registry, mock_dispatch)),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000005", "test_platform", data
        )

    assert count == 6
    assert mock_dispatch.await_count == 6


@pytest.mark.asyncio
async def test_pivot_logs_info_when_jobs_queued(caplog):
    """Lines 214-222: logger.info fires when queued_for_this > 0."""
    import logging

    data = {"email": "log@example.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"email_hibp": True}, mock_dispatch),
        ),
        caplog.at_level(logging.INFO, logger="modules.pipeline.pivot_enricher"),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000006", "test_platform", data
        )

    assert count >= 1
    assert any("Pivot" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_pivot_no_platforms_for_type_queues_zero():
    """Lines 200-201: id_type has no entry in _PIVOT_PLATFORMS → 0 dispatched.

    We inject an unknown id_type by returning a fake pivot tuple via a patched
    _extract_pivots so we exercise the 'platforms = _PIVOT_PLATFORMS.get(id_type, [])'
    path where the list is empty.
    """
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    fake_pivots = [("unknown_type_xyz", "somevalue")]

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch("modules.pipeline.pivot_enricher._extract_pivots", return_value=fake_pivots),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"email_hibp": True}, mock_dispatch),
        ),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000007", "test_platform", {"anything": "x"}
        )

    assert count == 0
    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pivot_max_jobs_cap_breaks_loop():
    """Lines 182-183: jobs_queued >= _MAX_JOBS_PER_CALL → break.

    We inject 31 fake pivots (each with 1 platform job), which must be capped
    at _MAX_JOBS_PER_CALL (30). The 31st pivot is never dispatched.
    """
    import modules.pipeline.pivot_enricher as m

    mock_dispatch = AsyncMock()

    # Build a session that always returns None (no existing identifier)
    session = _make_session(existing=None)

    # 31 unique domain pivots, each maps to domain_whois in the registry
    fake_pivots = [("domain", f"site{i}.com") for i in range(31)]

    registry = {"domain_whois": True}

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch("modules.pipeline.pivot_enricher._extract_pivots", return_value=fake_pivots),
        patch.dict("sys.modules", _sys_modules_patch(registry, mock_dispatch)),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000008", "test_platform", {"domain": "x.com"}
        )

    assert count == m._MAX_JOBS_PER_CALL
    assert mock_dispatch.await_count == m._MAX_JOBS_PER_CALL


@pytest.mark.asyncio
async def test_pivot_multiple_pivot_types_each_logged(caplog):
    """Lines 214-222 fires once per pivot type that has queued jobs."""
    import logging

    data = {
        "email": "multi2@example.com",
        "phone": "+15557654322",
    }
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    registry = {
        "email_hibp": True,
        "phone_carrier": True,
    }

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict("sys.modules", _sys_modules_patch(registry, mock_dispatch)),
        caplog.at_level(logging.INFO, logger="modules.pipeline.pivot_enricher"),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000009", "test_platform", data
        )

    assert count == 2
    pivot_logs = [r for r in caplog.records if "Pivot" in r.message]
    assert len(pivot_logs) == 2


@pytest.mark.asyncio
async def test_pivot_dispatch_receives_correct_args():
    """Lines 205-210: dispatch_job called with correct platform/identifier/person_id."""
    data = {"domain": "dispatch-test.com"}
    mock_dispatch = AsyncMock()
    session = _make_session(existing=None)

    with (
        patch("modules.pipeline.pivot_enricher.AsyncSessionLocal", return_value=session),
        patch.dict(
            "sys.modules",
            _sys_modules_patch({"domain_whois": True}, mock_dispatch),
        ),
    ):
        count = await pivot_from_result(
            "00000000-0000-0000-0000-000000000010", "test_platform", data
        )

    assert count == 1
    call_kwargs = mock_dispatch.call_args
    assert call_kwargs.kwargs["platform"] == "domain_whois"
    assert call_kwargs.kwargs["identifier"] == "dispatch-test.com"
    assert call_kwargs.kwargs["priority"] == "normal"
