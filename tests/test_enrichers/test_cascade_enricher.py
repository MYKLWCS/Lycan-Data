"""
test_cascade_enricher.py — Unit tests for modules/enrichers/cascade_enricher.py.

Covers:
  - enrich: no profiles → returns 0
  - enrich: handle field on SocialProfile → queues USERNAME jobs
  - enrich: profile_data email → queues EMAIL jobs
  - enrich: profile_data phone → queues PHONE jobs
  - enrich: instagram/twitter/linkedin handles in profile_data
  - enrich: duplicate seeds within a single run are deduped
  - enrich: seed already in existing Identifier set → skipped
  - _check_seed: invalid email format → rejected
  - _check_seed: invalid phone format → rejected
  - _check_seed: value already known → returns []
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.cascade_enricher import CascadeEnricher

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_session(existing_identifiers=None, social_profiles=None):
    """Build a mock AsyncSession that returns the given lists."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    # Build ordered execute return values: first call → identifiers, second → profiles
    calls = []
    for lst in (existing_identifiers or [], social_profiles or []):
        r = MagicMock()
        r.scalars.return_value.all.return_value = lst
        calls.append(r)

    session.execute = AsyncMock(side_effect=calls)
    return session


def _mock_identifier(type_: str, norm_val: str):
    i = MagicMock()
    i.type = type_
    i.normalized_value = norm_val
    return i


def _mock_profile(handle=None, profile_data=None):
    p = MagicMock()
    p.handle = handle
    p.profile_data = profile_data or {}
    return p


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCascadeEnricherNoWork:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_profiles(self):
        """No social profiles → 0 jobs."""
        session = _make_session(existing_identifiers=[], social_profiles=[])
        enricher = CascadeEnricher()
        result = await enricher.enrich(str(uuid.uuid4()), session)
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_profile_has_no_seeds(self):
        """Profile exists but no extractable seeds."""
        profile = _mock_profile(handle=None, profile_data={"some_irrelevant": "data"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()
        result = await enricher.enrich(str(uuid.uuid4()), session)
        assert result == 0


class TestCascadeEnricherHandleField:
    @pytest.mark.asyncio
    async def test_handle_queues_username_jobs(self):
        """SocialProfile.handle → USERNAME jobs dispatched."""
        profile = _mock_profile(handle="johndoe99", profile_data={})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch(
            "modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock
        ) as mock_dispatch:
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0
        platforms_called = [c.kwargs["platform"] for c in mock_dispatch.call_args_list]
        assert len(platforms_called) > 0

    @pytest.mark.asyncio
    async def test_handle_already_known_is_skipped(self):
        """Handle that's already in existing identifiers → no jobs."""
        existing = _mock_identifier("username", "johndoe99")
        profile = _mock_profile(handle="johndoe99", profile_data={})
        session = _make_session(existing_identifiers=[existing], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch(
            "modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock
        ) as mock_dispatch:
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result == 0
        mock_dispatch.assert_not_called()


class TestCascadeEnricherEmailField:
    @pytest.mark.asyncio
    async def test_email_in_profile_data_queues_jobs(self):
        """profile_data.email → EMAIL jobs."""
        profile = _mock_profile(profile_data={"email": "alice@example.com"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch(
            "modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock
        ) as mock_dispatch:
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0
        # All dispatched with email value
        for c in mock_dispatch.call_args_list:
            assert c.kwargs["identifier"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_invalid_email_format_skipped(self):
        """Malformed email value → rejected by _check_seed."""
        profile = _mock_profile(profile_data={"email": "not-an-email"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch(
            "modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock
        ) as mock_dispatch:
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result == 0
        mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_alternate_key_email_address(self):
        """profile_data.email_address also triggers email jobs."""
        profile = _mock_profile(profile_data={"email_address": "bob@corp.org"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0


class TestCascadeEnricherPhoneField:
    @pytest.mark.asyncio
    async def test_phone_in_profile_data_queues_jobs(self):
        """profile_data.phone → PHONE jobs."""
        profile = _mock_profile(profile_data={"phone": "+12025550199"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0

    @pytest.mark.asyncio
    async def test_invalid_phone_skipped(self):
        """Too-short phone string → rejected."""
        profile = _mock_profile(profile_data={"phone": "123"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result == 0


class TestCascadeEnricherSocialPlatformHandles:
    @pytest.mark.asyncio
    async def test_instagram_handle_in_profile_data(self):
        """profile_data.instagram → INSTAGRAM_HANDLE jobs."""
        profile = _mock_profile(profile_data={"instagram": "myhandle123"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0

    @pytest.mark.asyncio
    async def test_twitter_handle_in_profile_data(self):
        """profile_data.twitter → TWITTER_HANDLE jobs."""
        profile = _mock_profile(profile_data={"twitter": "twitteruser"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0

    @pytest.mark.asyncio
    async def test_linkedin_url_in_profile_data(self):
        """profile_data.linkedin → LINKEDIN_URL jobs."""
        profile = _mock_profile(profile_data={"linkedin": "https://linkedin.com/in/johndoe"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0


class TestCascadeEnricherDeduplication:
    @pytest.mark.asyncio
    async def test_same_seed_from_two_profiles_only_queued_once(self):
        """The same username across two profile records is only queued once."""
        profile1 = _mock_profile(handle="shared_handle", profile_data={})
        profile2 = _mock_profile(handle="shared_handle", profile_data={})
        session = _make_session(existing_identifiers=[], social_profiles=[profile1, profile2])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            await enricher.enrich(str(uuid.uuid4()), session)

        # Should dispatch for the handle exactly once (multiple platforms, but 1 seed)
        identifiers_added = session.add.call_count
        assert identifiers_added == 1  # Only one Identifier row created

    @pytest.mark.asyncio
    async def test_username_key_in_profile_data_queues_jobs(self):
        """profile_data.username → USERNAME jobs (line 104)."""
        profile = _mock_profile(handle=None, profile_data={"username": "screen_user"})
        session = _make_session(existing_identifiers=[], social_profiles=[profile])
        enricher = CascadeEnricher()

        with patch("modules.enrichers.cascade_enricher.dispatch_job", new_callable=AsyncMock):
            result = await enricher.enrich(str(uuid.uuid4()), session)

        assert result > 0
        identifiers_added = session.add.call_count
        assert identifiers_added == 1

    @pytest.mark.asyncio
    async def test_empty_string_value_skipped(self):
        """_check_seed with empty string → returns []."""
        enricher = CascadeEnricher()
        known: set = set()
        result = enricher._check_seed(
            __import__("shared.constants", fromlist=["SeedType"]).SeedType.USERNAME,
            "",
            known,
        )
        assert result == []
