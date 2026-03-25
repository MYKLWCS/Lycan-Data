"""
test_final_gaps.py — Covers the last 5 remaining uncovered lines.

Files targeted:
  - api/routes/export.py          lines 76, 78  (CSV rows for identifiers + socials)
  - modules/crawlers/linkedin.py  lines 71, 76  (headline + location in _extract)
  - shared/utils/email.py         line 33       (is_valid_email return value)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ===========================================================================
# shared/utils/email.py  line 33 — is_valid_email return value
# ===========================================================================


class TestIsValidEmail:
    def test_valid_email_returns_true(self):
        from shared.utils.email import is_valid_email

        assert is_valid_email("user@example.com") is True

    def test_invalid_email_returns_false(self):
        from shared.utils.email import is_valid_email

        assert is_valid_email("not-an-email") is False


# ===========================================================================
# api/routes/export.py  lines 76, 78 — CSV rows written for identifiers + socials
# ===========================================================================


class TestExportPersonCsv:
    """Exercises the two for-loop bodies in export_person_csv."""

    def _build_app(self, person, identifiers, socials):
        from api.deps import db_session
        from api.routes.export import router

        app = FastAPI()
        app.include_router(router, prefix="/export")

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=person)

        # db.scalars(...).all() called twice — once for identifiers, once for socials
        scalars_result_idents = MagicMock()
        scalars_result_idents.all.return_value = identifiers
        scalars_result_socials = MagicMock()
        scalars_result_socials.all.return_value = socials
        mock_db.scalars = AsyncMock(side_effect=[scalars_result_idents, scalars_result_socials])

        async def override_db():
            yield mock_db

        app.dependency_overrides[db_session] = override_db
        return app

    def test_csv_with_identifiers_and_socials(self):
        """Lines 76 and 78: both for-loop bodies execute when lists are non-empty."""
        pid = uuid.uuid4()

        person = MagicMock()
        person.id = pid

        ident = MagicMock()
        ident.value = "test@example.com"
        ident.platform = "email"

        social = MagicMock()
        social.username = "testuser"
        social.platform = "twitter"
        social.follower_count = 500

        app = self._build_app(person, [ident], [social])
        client = TestClient(app)
        resp = client.get(f"/export/{pid}/csv")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "identifier" in body
        assert "test@example.com" in body
        assert "social" in body
        assert "testuser" in body

    def test_csv_social_no_username_uses_empty_string(self):
        """social.username=None → writes '' (the `or ''` branch on line 78)."""
        pid = uuid.uuid4()

        person = MagicMock()
        person.id = pid

        social = MagicMock()
        social.username = None
        social.platform = "instagram"
        social.follower_count = None

        app = self._build_app(person, [], [social])
        client = TestClient(app)
        resp = client.get(f"/export/{pid}/csv")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "social" in body
        assert "instagram" in body

    def test_csv_identifier_no_platform_uses_empty_string(self):
        """ident.platform=None → writes '' (the `or ''` branch on line 76)."""
        pid = uuid.uuid4()

        person = MagicMock()
        person.id = pid

        ident = MagicMock()
        ident.value = "+12125551234"
        ident.platform = None

        app = self._build_app(person, [ident], [])
        client = TestClient(app)
        resp = client.get(f"/export/{pid}/csv")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "+12125551234" in body


# ===========================================================================
# modules/crawlers/linkedin.py  lines 71, 76 — headline + location extracted
# ===========================================================================


class TestLinkedInExtractHeadlineAndLocation:
    """Exercises lines 71 and 76 in LinkedIn._extract()."""

    def _make_crawler(self):
        from modules.crawlers.linkedin import LinkedInCrawler

        return LinkedInCrawler()

    @pytest.mark.asyncio
    async def test_extract_headline_and_location(self):
        """Lines 71, 76: headline and loc selectors return truthy elements → inner_text called."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="Jane Smith | LinkedIn")

        headline_el = AsyncMock()
        headline_el.inner_text = AsyncMock(return_value="Senior Engineer at Acme")

        loc_el = AsyncMock()
        loc_el.inner_text = AsyncMock(return_value="San Francisco, CA")

        # Return headline_el for first query_selector call (.top-card-layout__headline),
        # loc_el for second (.top-card__subline-item), None for rest
        page.query_selector = AsyncMock(side_effect=[headline_el, loc_el, None, None])
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "janesmith")

        assert data.get("headline") == "Senior Engineer at Acme"
        assert data.get("location") == "San Francisco, CA"
        assert data.get("display_name") == "Jane Smith"

    @pytest.mark.asyncio
    async def test_extract_headline_only(self):
        """Line 71 only: headline found, loc is None."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="Bob Jones | LinkedIn")

        headline_el = AsyncMock()
        headline_el.inner_text = AsyncMock(return_value="VP of Engineering")

        page.query_selector = AsyncMock(side_effect=[headline_el, None, None, None])
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "bobjones")

        assert data.get("headline") == "VP of Engineering"
        assert data.get("location") is None
