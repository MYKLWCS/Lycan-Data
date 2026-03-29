"""
test_aggregator_wave3.py — Coverage gap tests for modules/pipeline/aggregator.py.

Targets uncovered dispatch branches and helpers:
  - aggregate_result dispatch: email_breach, sanctions, darkweb, people_search,
    court, sex_offender, bankruptcy
  - _handle_phone_enrichment: new/existing identifier, non-US area code
  - _handle_darkweb source_type branches: market→dark_market, forum→dark_forum
  - _upsert_phone_identifier: existing corroboration increment

All DB I/O is mocked via AsyncMock session.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.core.result import CrawlerResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    platform: str,
    identifier: str = "test@example.com",
    data: dict | None = None,
    found: bool = True,
) -> CrawlerResult:
    return CrawlerResult(
        platform=platform,
        identifier=identifier,
        found=found,
        data=data or {},
        source_reliability=0.8,
    )


def _make_session():
    """Return an AsyncMock session with scalar_one_or_none returning None by default."""
    session = AsyncMock()
    # execute returns an object whose scalar_one_or_none() returns None
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    exec_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    exec_result.mappings = MagicMock(
        return_value=MagicMock(one=MagicMock(return_value={"total_logs": 0, "found_count": 0}))
    )
    session.execute = AsyncMock(return_value=exec_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _make_person(person_id=None):
    p = MagicMock()
    p.id = person_id or uuid.uuid4()
    p.full_name = "John Doe"
    p.corroboration_count = 1
    p.source_reliability = 0.5
    p.default_risk_score = 0.5
    return p


# ===========================================================================
# aggregate_result dispatch branches
# ===========================================================================


class TestAggregateResultDispatch:
    """Test that aggregate_result correctly routes to sub-handlers per platform."""

    @pytest.mark.asyncio
    async def test_no_data_returns_no_write(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        result = _make_result("email_hibp", data={}, found=False)

        outcome = await aggregate_result(session, result, person_id=None)
        assert outcome["written"] is False

    @pytest.mark.asyncio
    async def test_email_breach_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "email_hibp",
            identifier="hack@example.com",
            data={
                "breaches": [{"name": "TestSite", "date": "2022-01-01", "data_classes": ["email"]}]
            },
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert outcome.get("breach_data") is True
        assert outcome.get("breach_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_sanctions_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "sanctions_ofac",
            identifier="John Doe",
            data={"matches": [{"name": "John Doe", "score": 0.95, "reason": "OFAC SDN"}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert "watchlist_hits" in outcome
        assert outcome["watchlist_hits"] >= 1

    @pytest.mark.asyncio
    async def test_darkweb_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "paste_psbdmp",
            identifier="user@example.com",
            data={"mentions": [{"url": "https://pastebin.com/abc", "preview": "leaked data"}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert outcome.get("darkweb") is True

    @pytest.mark.asyncio
    async def test_people_search_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "whitepages",
            identifier="John Smith",
            data={"results": [{"address": "123 Main St, Austin TX"}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert outcome.get("addresses") is True

    @pytest.mark.asyncio
    async def test_court_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "court_courtlistener",
            identifier="John Doe",
            data={"cases": [{"charge": "DUI", "level": "misdemeanor", "date": "2020-06-01"}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert "criminal_records" in outcome
        assert outcome["criminal_records"] >= 1

    @pytest.mark.asyncio
    async def test_sex_offender_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "public_nsopw",
            identifier="John Doe",
            data={"hits": [{"offense": "Sexual Assault", "state": "TX"}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert "sex_offender_records" in outcome
        assert outcome["sex_offender_records"] >= 1

    @pytest.mark.asyncio
    async def test_bankruptcy_dispatch(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _make_session()
        person_id = str(uuid.uuid4())
        result = _make_result(
            "bankruptcy_pacer",
            identifier="John Doe",
            data={"cases": [{"case_number": "11-12345", "chapter": 7}]},
        )

        person = _make_person(uuid.UUID(person_id))
        with patch(
            "modules.pipeline.aggregator._get_or_create_person", new=AsyncMock(return_value=person)
        ):
            outcome = await aggregate_result(session, result, person_id=person_id)

        assert outcome.get("bankruptcy") is True


# ===========================================================================
# _handle_phone_enrichment
# ===========================================================================


class TestHandlePhoneEnrichment:
    """Test _handle_phone_enrichment branches."""

    @pytest.mark.asyncio
    async def test_new_identifier_created(self):
        """When no existing Identifier found, a new one is created."""
        from modules.pipeline.aggregator import _handle_phone_enrichment

        session = _make_session()
        # scalar_one_or_none returns None → new identifier path
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=exec_result)

        result = _make_result(
            "phone_carrier",
            identifier="+15551234567",
            data={"carrier_name": "Verizon", "line_type": "mobile"},
        )
        person_id = uuid.uuid4()

        with (
            patch("modules.enrichers.burner_detector.compute_burner_score", return_value=0.1),
            patch("modules.enrichers.burner_detector.persist_burner_assessment", new=AsyncMock()),
        ):
            await _handle_phone_enrichment(session, result, person_id)

        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_identifier_not_duplicated(self):
        """When an Identifier already exists, no new row is added."""
        from modules.pipeline.aggregator import _handle_phone_enrichment

        session = _make_session()
        existing_ident = MagicMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=existing_ident)
        session.execute = AsyncMock(return_value=exec_result)

        result = _make_result(
            "phone_carrier",
            identifier="+15551234567",
            data={"carrier_name": "AT&T", "line_type": "landline"},
        )
        person_id = uuid.uuid4()

        with (
            patch("modules.enrichers.burner_detector.compute_burner_score", return_value=0.2),
            patch("modules.enrichers.burner_detector.persist_burner_assessment", new=AsyncMock()),
        ):
            await _handle_phone_enrichment(session, result, person_id)

        # No new row added for existing identifier
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_us_number_area_code_none(self):
        """Non-US phone number (+44...) gives area_code=None."""
        from modules.pipeline.aggregator import _handle_phone_enrichment

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=exec_result)

        result = _make_result(
            "phone_carrier", identifier="+447911123456", data={"carrier_name": "O2"}
        )
        person_id = uuid.uuid4()

        captured_args = {}

        def _mock_score(phone, carrier_name, line_type, area_code):
            captured_args["area_code"] = area_code
            return 0.1

        with (
            patch(
                "modules.enrichers.burner_detector.compute_burner_score", side_effect=_mock_score
            ),
            patch("modules.enrichers.burner_detector.persist_burner_assessment", new=AsyncMock()),
        ):
            await _handle_phone_enrichment(session, result, person_id)

        # UK number does not start with +1, so area_code should be None
        assert captured_args["area_code"] is None


# ===========================================================================
# _handle_darkweb source_type branches
# ===========================================================================


class TestHandleDarkwebSourceTypes:
    """Verify source_type mapping in _handle_darkweb."""

    @pytest.mark.asyncio
    async def test_market_platform_maps_to_dark_market(self):
        from modules.pipeline.aggregator import _handle_darkweb

        session = _make_session()
        result = _make_result(
            "darkweb_market_silk",
            data={"mentions": [{"url": "http://onion.example/item", "title": "Stolen Cards"}]},
        )
        person_id = uuid.uuid4()

        added_models = []
        session.add = MagicMock(side_effect=lambda m: added_models.append(m))

        await _handle_darkweb(session, result, person_id)

        darkweb_rows = [m for m in added_models if hasattr(m, "source_type")]
        assert any(m.source_type == "dark_market" for m in darkweb_rows)

    @pytest.mark.asyncio
    async def test_forum_platform_maps_to_dark_forum(self):
        from modules.pipeline.aggregator import _handle_darkweb

        session = _make_session()
        result = _make_result(
            "darkweb_forum_breach",
            data={
                "mentions": [{"url": "http://forum.onion/thread/1", "title": "Leaked Passwords"}]
            },
        )
        person_id = uuid.uuid4()

        added_models = []
        session.add = MagicMock(side_effect=lambda m: added_models.append(m))

        await _handle_darkweb(session, result, person_id)

        darkweb_rows = [m for m in added_models if hasattr(m, "source_type")]
        assert any(m.source_type == "dark_forum" for m in darkweb_rows)

    @pytest.mark.asyncio
    async def test_paste_platform_maps_to_paste_site(self):
        from modules.pipeline.aggregator import _handle_darkweb

        session = _make_session()
        result = _make_result(
            "paste_psbdmp",
            data={"mentions": [{"url": "https://pastebin.com/xyz", "preview": "data"}]},
        )
        person_id = uuid.uuid4()

        added_models = []
        session.add = MagicMock(side_effect=lambda m: added_models.append(m))

        await _handle_darkweb(session, result, person_id)

        darkweb_rows = [m for m in added_models if hasattr(m, "source_type")]
        assert any(m.source_type == "paste_site" for m in darkweb_rows)


# ===========================================================================
# _upsert_phone_identifier — existing corroboration increment
# ===========================================================================


class TestUpsertPhoneIdentifier:
    """Test _upsert_phone_identifier corroboration increment on existing row."""

    @pytest.mark.asyncio
    async def test_existing_identifier_increments_corroboration(self):
        from modules.pipeline.aggregator import _upsert_phone_identifier

        session = _make_session()
        existing = MagicMock()
        existing.corroboration_count = 2
        existing.meta = {"confirmed_via": "whatsapp"}

        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=exec_result)

        phone = "+15551234567"
        person_id = uuid.uuid4()

        await _upsert_phone_identifier(session, phone, person_id, "telegram")

        assert existing.corroboration_count == 3
        assert existing.meta.get("confirmed_telegram") is True
        # No new row added
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_identifier_is_created(self):
        from modules.pipeline.aggregator import _upsert_phone_identifier

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=exec_result)

        phone = "+15551234567"
        person_id = uuid.uuid4()

        await _upsert_phone_identifier(session, phone, person_id, "whatsapp")

        session.add.assert_called_once()
