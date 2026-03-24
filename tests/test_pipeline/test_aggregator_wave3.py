"""Wave-3 aggregator tests.

Covers:
  - aggregate_result dispatch branches: email_breach, sanctions, darkweb,
    people_search, court, sex_offender, bankruptcy (lines ~179-211)
  - _handle_phone_enrichment: new identifier, existing identifier,
    non-US area code (lines ~368-407)
  - _handle_darkweb source_type branches: dark_market, dark_forum (lines ~524-532)
  - _upsert_phone_identifier: existing corroboration increment (lines ~921-925)

All DB operations mocked with AsyncMock — no real database required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.crawlers.result import CrawlerResult
from modules.pipeline.aggregator import (
    _handle_darkweb,
    _handle_phone_enrichment,
    _upsert_phone_identifier,
    aggregate_result,
)
from shared.models.identifier import Identifier
from shared.constants import IdentifierType


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Return a mock AsyncSession with sensible defaults."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result

    session.get = AsyncMock(return_value=None)
    return session


def _make_result(**kwargs) -> CrawlerResult:
    defaults = {
        "platform": "email_breach",
        "identifier": "test@example.com",
        "found": True,
        "data": {},
        "source_reliability": 0.8,
    }
    defaults.update(kwargs)
    return CrawlerResult(**defaults)


def _make_person(person_id: uuid.UUID | None = None) -> MagicMock:
    p = MagicMock()
    p.id = person_id or uuid.uuid4()
    p.full_name = "Test Person"
    return p


# ══════════════════════════════════════════════════════════════════════════════
# aggregate_result dispatch branches
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dispatch_email_breach():
    """Platform in _EMAIL_BREACH_PLATFORMS triggers _handle_breach_data."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="email_breach",
        identifier="victim@corp.com",
        data={"breaches": [{"name": "HaveIBeenPwned", "date": "2023-01-01"}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_breach_data",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_breach,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_breach.assert_awaited_once()
    assert out.get("breach_data") is True
    assert out.get("breach_count") == 1


@pytest.mark.asyncio
async def test_dispatch_sanctions():
    """Platform in _SANCTIONS_PLATFORMS triggers _handle_watchlist."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="sanctions_ofac",
        identifier="Bad Actor",
        data={"match": True, "list": "OFAC-SDN"},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_watchlist",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_wl,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_wl.assert_awaited_once()
    assert "watchlist_hits" in out
    assert out["watchlist_hits"] == 1


@pytest.mark.asyncio
async def test_dispatch_darkweb():
    """Platform in _DARKWEB_PLATFORMS triggers _handle_darkweb."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="darkweb_ahmia",
        identifier="victim@corp.com",
        data={"mentions": [{"url": "http://abc.onion", "description": "leaked data"}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_darkweb",
            new_callable=AsyncMock,
        ) as mock_dw,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_dw.assert_awaited_once()
    assert out.get("darkweb") is True


@pytest.mark.asyncio
async def test_dispatch_people_search():
    """Platform in _PEOPLE_SEARCH_PLATFORMS triggers _handle_people_search."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="whitepages",
        identifier="John Doe",
        data={"addresses": [{"city": "Dallas", "state": "TX"}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_people_search",
            new_callable=AsyncMock,
        ) as mock_ps,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_ps.assert_awaited_once()
    assert out.get("addresses") is True


@pytest.mark.asyncio
async def test_dispatch_court():
    """Platform in _COURT_PLATFORMS triggers _handle_court_records."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="court_courtlistener",
        identifier="John Doe",
        data={"cases": [{"case_id": "TX-2024-001", "charge": "DUI"}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_court_records",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_court,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_court.assert_awaited_once()
    assert out.get("criminal_records") == 1


@pytest.mark.asyncio
async def test_dispatch_sex_offender():
    """Platform in _SEX_OFFENDER_PLATFORMS triggers _handle_sex_offender."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="public_nsopw",
        identifier="John Doe",
        data={"records": [{"offense": "RSO", "state": "TX"}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_sex_offender",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_so,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_so.assert_awaited_once()
    assert out.get("sex_offender_records") == 1


@pytest.mark.asyncio
async def test_dispatch_bankruptcy():
    """Platform in _BANKRUPTCY_PLATFORMS triggers _handle_bankruptcy."""
    session = _mock_session()
    person_id = uuid.uuid4()
    result = _make_result(
        platform="bankruptcy_pacer",
        identifier="John Doe",
        data={"filings": [{"case_number": "BK-2020-9999", "chapter": 7}]},
    )

    with (
        patch(
            "modules.pipeline.aggregator._get_or_create_person",
            new_callable=AsyncMock,
            return_value=_make_person(person_id),
        ),
        patch(
            "modules.pipeline.aggregator._handle_bankruptcy",
            new_callable=AsyncMock,
        ) as mock_bk,
        patch(
            "modules.pipeline.aggregator._record_identifier_history",
            new_callable=AsyncMock,
        ),
    ):
        out = await aggregate_result(session, result)

    mock_bk.assert_awaited_once()
    assert out.get("bankruptcy") is True


# ══════════════════════════════════════════════════════════════════════════════
# _handle_phone_enrichment
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_handle_phone_enrichment_new_identifier():
    """No existing Identifier row — creates one and calls burner helpers."""
    session = _mock_session()
    # scalar_one_or_none → None (no existing identifier)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()
    result = _make_result(
        platform="phone_carrier",
        identifier="+12125550100",
        data={"carrier_name": "Verizon", "line_type": "mobile"},
    )

    mock_score = MagicMock()
    mock_score.is_burner = False
    mock_score.score = 0.1

    with (
        patch(
            "modules.enrichers.burner_detector.compute_burner_score",
            return_value=mock_score,
        ) as mock_compute,
        patch(
            "modules.enrichers.burner_detector.persist_burner_assessment",
            new_callable=AsyncMock,
        ) as mock_persist,
    ):
        await _handle_phone_enrichment(session, result, person_id)

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    mock_compute.assert_called_once_with(
        phone="+12125550100",
        carrier_name="Verizon",
        line_type="mobile",
        area_code="212",
    )
    mock_persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_phone_enrichment_existing_identifier():
    """Existing Identifier row — skips add/flush, still scores."""
    session = _mock_session()

    existing_ident = MagicMock(spec=Identifier)
    existing_ident.id = uuid.uuid4()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_ident
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()
    result = _make_result(
        platform="phone_carrier",
        identifier="+12125550100",
        data={"carrier_name": "AT&T", "line_type": "voip"},
    )

    mock_score = MagicMock()

    with (
        patch(
            "modules.enrichers.burner_detector.compute_burner_score",
            return_value=mock_score,
        ),
        patch(
            "modules.enrichers.burner_detector.persist_burner_assessment",
            new_callable=AsyncMock,
        ) as mock_persist,
    ):
        await _handle_phone_enrichment(session, result, person_id)

    # No new row should have been added
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    mock_persist.assert_awaited_once_with(session, existing_ident.id, mock_score)


@pytest.mark.asyncio
async def test_handle_phone_enrichment_non_us_area_code_is_none():
    """Non-US number (+44…) — area_code passed as None to burner scorer."""
    session = _mock_session()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()
    result = _make_result(
        platform="phone_fonefinder",
        identifier="+447911123456",
        data={"carrier_name": "O2 UK", "line_type": "mobile"},
    )

    mock_score = MagicMock()

    with (
        patch(
            "modules.enrichers.burner_detector.compute_burner_score",
            return_value=mock_score,
        ) as mock_compute,
        patch(
            "modules.enrichers.burner_detector.persist_burner_assessment",
            new_callable=AsyncMock,
        ),
    ):
        await _handle_phone_enrichment(session, result, person_id)

    # area_code should be None for non-+1 numbers
    call_kwargs = mock_compute.call_args.kwargs
    assert call_kwargs["area_code"] is None


# ══════════════════════════════════════════════════════════════════════════════
# _handle_darkweb — source_type branches
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_handle_darkweb_dark_market_source_type():
    """Platform containing 'market' maps to source_type='dark_market'."""
    session = _mock_session()
    person_id = uuid.uuid4()

    result = _make_result(
        platform="darkweb_market_alphabay",
        identifier="victim@corp.com",
        data={
            "mentions": [
                {"url": "http://market.onion/listing/123", "description": "CC dump"}
            ]
        },
    )

    added_objects = []
    session.add.side_effect = added_objects.append

    await _handle_darkweb(session, result, person_id)

    # Find the DarkwebMention that was added
    from shared.models.darkweb import DarkwebMention

    dm_objects = [o for o in added_objects if isinstance(o, DarkwebMention)]
    assert len(dm_objects) == 1
    assert dm_objects[0].source_type == "dark_market"


@pytest.mark.asyncio
async def test_handle_darkweb_dark_forum_source_type():
    """Platform containing 'forum' maps to source_type='dark_forum'."""
    session = _mock_session()
    person_id = uuid.uuid4()

    result = _make_result(
        platform="darkweb_forum_dread",
        identifier="victim@corp.com",
        data={
            "mentions": [
                {"url": "http://forum.onion/thread/999", "description": "PII dump"}
            ]
        },
    )

    added_objects = []
    session.add.side_effect = added_objects.append

    await _handle_darkweb(session, result, person_id)

    from shared.models.darkweb import DarkwebMention

    dm_objects = [o for o in added_objects if isinstance(o, DarkwebMention)]
    assert len(dm_objects) == 1
    assert dm_objects[0].source_type == "dark_forum"


@pytest.mark.asyncio
async def test_handle_darkweb_paste_site_source_type():
    """Platform containing 'paste' maps to source_type='paste_site'."""
    session = _mock_session()
    person_id = uuid.uuid4()

    result = _make_result(
        platform="paste_pastebin",
        identifier="victim@corp.com",
        data={
            "mentions": [{"url": "https://pastebin.com/abc", "description": "leaked"}]
        },
    )

    added_objects = []
    session.add.side_effect = added_objects.append

    await _handle_darkweb(session, result, person_id)

    from shared.models.darkweb import DarkwebMention

    dm_objects = [o for o in added_objects if isinstance(o, DarkwebMention)]
    assert len(dm_objects) == 1
    assert dm_objects[0].source_type == "paste_site"


@pytest.mark.asyncio
async def test_handle_darkweb_empty_mentions_writes_nothing():
    """No mentions → nothing added to session."""
    session = _mock_session()
    person_id = uuid.uuid4()

    result = _make_result(
        platform="darkweb_torch",
        identifier="nobody@nowhere.com",
        data={"mentions": []},
    )

    await _handle_darkweb(session, result, person_id)

    session.add.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# _upsert_phone_identifier — existing corroboration increment
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upsert_phone_identifier_existing_increments_corroboration():
    """When phone already exists, corroboration_count is incremented and no new row added."""
    session = _mock_session()

    existing_ident = MagicMock(spec=Identifier)
    existing_ident.corroboration_count = 2
    existing_ident.meta = {"confirmed_via": "whatsapp"}

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_ident
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()

    await _upsert_phone_identifier(session, "+12125550100", person_id, "telegram")

    assert existing_ident.corroboration_count == 3
    assert existing_ident.meta.get("confirmed_telegram") is True
    # No new row should be added
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_phone_identifier_existing_none_corroboration_defaults_to_1():
    """corroboration_count=None is treated as 1 before incrementing."""
    session = _mock_session()

    existing_ident = MagicMock(spec=Identifier)
    existing_ident.corroboration_count = None
    existing_ident.meta = {}

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_ident
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()

    await _upsert_phone_identifier(session, "+12125550100", person_id, "whatsapp")

    # (None or 1) + 1 = 2
    assert existing_ident.corroboration_count == 2


@pytest.mark.asyncio
async def test_upsert_phone_identifier_new_creates_row():
    """No existing record — a new Identifier is added and flushed."""
    session = _mock_session()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = scalar_result

    person_id = uuid.uuid4()

    await _upsert_phone_identifier(session, "+447911123456", person_id, "telegram")

    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    added = session.add.call_args[0][0]
    assert added.type == IdentifierType.PHONE.value
    assert added.normalized_value == "+447911123456"
    assert added.meta.get("confirmed_via") == "telegram"
    assert added.meta.get("confirmed_telegram") is True
