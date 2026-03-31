"""
Extended coverage tests for pipeline and graph modules.

Targets uncovered lines in:
  - modules/pipeline/aggregator.py          (64% → target 90%+)
  - modules/pipeline/enrichment_orchestrator.py (81% → target 95%+)
  - modules/pipeline/ingestion_daemon.py    (91% → target 98%+)
  - modules/graph/entity_graph.py           (76% → target 95%+)
  - modules/graph/company_intel.py          (93% → target 100%)
  - modules/dispatcher/dispatcher.py        (97% → target 100%)
  - modules/dispatcher/growth_daemon.py     (87% → target 98%+)
  - modules/search/index_daemon.py          (89% → target 98%+)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _mock_session() -> AsyncMock:
    """AsyncSession with sensible no-op defaults."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.get = AsyncMock(return_value=None)

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    scalar_result.scalar.return_value = None

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    scalar_result.scalars.return_value = scalars_mock

    session.execute = AsyncMock(return_value=scalar_result)
    return session


def _scalars_result(items: list) -> MagicMock:
    sm = MagicMock()
    sm.all.return_value = items
    rm = MagicMock()
    rm.scalars.return_value = sm
    return rm


def _scalar_result(value) -> MagicMock:
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = value
    rm.scalar.return_value = value
    scalars_m = MagicMock()
    scalars_m.all.return_value = [value] if value is not None else []
    rm.scalars.return_value = scalars_m
    return rm


def _make_crawler_result(**kwargs):
    from modules.crawlers.core.result import CrawlerResult

    defaults = {
        "platform": "instagram",
        "identifier": "testuser",
        "found": True,
        "data": {"handle": "testuser"},
        "source_reliability": 0.6,
    }
    defaults.update(kwargs)
    return CrawlerResult(**defaults)


# ===========================================================================
# 1. AGGREGATOR — uncovered handlers
# ===========================================================================


class TestAggregatorFullNameBackfill:
    """Lines 146-155: full_name backfill logic on Person."""

    @pytest.mark.asyncio
    async def test_backfill_full_name_when_person_has_no_name(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(id=uuid.uuid4(), full_name=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            data={"handle": "alice", "full_name": "Alice Johnson"},
        )
        out = await aggregate_result(session, result, person_id=str(person.id))
        assert person.full_name == "Alice Johnson"
        assert "person_id" in out

    @pytest.mark.asyncio
    async def test_backfill_rejects_platform_word_as_name(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(id=uuid.uuid4(), full_name=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            data={"handle": "user", "display_name": "Instagram User"},
        )
        await aggregate_result(session, result, person_id=str(person.id))
        # "instagram" is a platform word — must not be backfilled
        assert person.full_name is None

    @pytest.mark.asyncio
    async def test_backfill_rejects_single_word_name(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(id=uuid.uuid4(), full_name=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            data={"handle": "mono", "full_name": "Mononym"},
        )
        await aggregate_result(session, result, person_id=str(person.id))
        assert person.full_name is None

    @pytest.mark.asyncio
    async def test_backfill_rejects_name_with_digits(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(id=uuid.uuid4(), full_name=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            data={"full_name": "Hacker 123"},
        )
        await aggregate_result(session, result, person_id=str(person.id))
        assert person.full_name is None

    @pytest.mark.asyncio
    async def test_backfill_skips_when_person_already_has_name(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(id=uuid.uuid4(), full_name="Existing Name")
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            data={"full_name": "Should Not Replace"},
        )
        await aggregate_result(session, result, person_id=str(person.id))
        assert person.full_name == "Existing Name"


class TestAggregatorWhatsAppTelegram:
    """Lines 167-170: WhatsApp/Telegram phone identifier upsert."""

    @pytest.mark.asyncio
    async def test_whatsapp_phone_stored_as_identifier(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.identifier import Identifier

        session = _mock_session()
        result = _make_crawler_result(
            platform="whatsapp",
            identifier="+12125551234",
            data={"phone": "+12125551234", "status": "online"},
        )
        out = await aggregate_result(session, result)
        assert out.get("phone_identifier") is not None

    @pytest.mark.asyncio
    async def test_telegram_phone_stored_when_identifier_looks_like_phone(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="telegram",
            identifier="+447700900123",
            data={"username": "telegramuser"},
        )
        out = await aggregate_result(session, result)
        assert out.get("phone_identifier") == "+447700900123"

    @pytest.mark.asyncio
    async def test_telegram_non_phone_identifier_not_stored(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="telegram",
            identifier="just_a_username",
            data={"username": "just_a_username"},
        )
        out = await aggregate_result(session, result)
        assert "phone_identifier" not in out


class TestAggregatorPhoneEnrichment:
    """Lines 174-175: phone enrichment dispatch."""

    @pytest.mark.asyncio
    async def test_phone_carrier_platform_triggers_enrichment(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="phone_carrier",
            identifier="+12125550000",
            data={"carrier_name": "T-Mobile", "line_type": "mobile"},
        )

        with patch(
            "modules.pipeline.aggregator._handle_phone_enrichment", new=AsyncMock()
        ) as mock_enrich:
            out = await aggregate_result(session, result)

        mock_enrich.assert_awaited_once()
        assert out.get("phone_enrichment") is True


class TestAggregatorEmailBreach:
    """Lines 179-181: email breach platform routing."""

    @pytest.mark.asyncio
    async def test_leakcheck_sources_written_as_breach_records(self):
        from modules.pipeline.aggregator import _handle_breach_data
        from shared.models.breach import BreachRecord

        session = _mock_session()
        result = _make_crawler_result(
            platform="email_leakcheck",
            identifier="victim@example.com",
            data={"sources": [{"db": "collection1"}, {"db": "combo_lists"}]},
        )
        count = await _handle_breach_data(session, result, uuid.uuid4())
        assert count == 2
        added = [c.args[0] for c in session.add.call_args_list]
        assert all(isinstance(a, BreachRecord) for a in added)

    @pytest.mark.asyncio
    async def test_breach_date_parse_failure_sets_none(self):
        from modules.pipeline.aggregator import _handle_breach_data
        from shared.models.breach import BreachRecord

        session = _mock_session()
        result = _make_crawler_result(
            platform="email_breach",
            identifier="test@example.com",
            data={"breaches": [{"name": "BadDate", "date": "not-a-date"}]},
        )
        count = await _handle_breach_data(session, result, uuid.uuid4())
        assert count == 1
        br = session.add.call_args_list[0].args[0]
        assert isinstance(br, BreachRecord)
        assert br.breach_date is None


class TestAggregatorSanctions:
    """Lines 185-186: sanctions routing + multiple matches."""

    @pytest.mark.asyncio
    async def test_multiple_sanctions_hits_counted(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="sanctions_ofac",
            identifier="John Smith",
            data={
                "matches": [
                    {"name": "JOHN SMITH", "score": 0.9},
                    {"name": "JON SMYTH", "score": 0.75},
                ]
            },
        )
        out = await aggregate_result(session, result)
        assert out["watchlist_hits"] == 2

    @pytest.mark.asyncio
    async def test_sanctions_no_matches_returns_zero(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="sanctions_un",
            identifier="Clean Person",
            data={"matches": []},
        )
        out = await aggregate_result(session, result)
        assert out["watchlist_hits"] == 0


class TestAggregatorDarkweb:
    """Lines 190-191: dark-web routing + paste platform source_type."""

    @pytest.mark.asyncio
    async def test_paste_platform_sets_paste_site_source_type(self):
        from modules.pipeline.aggregator import _handle_darkweb
        from shared.models.darkweb import DarkwebMention

        session = _mock_session()
        result = _make_crawler_result(
            platform="paste_pastebin",
            identifier="target@example.com",
            data={"mentions": [{"url": "https://pastebin.com/abc123", "title": "Leaked Data"}]},
        )
        await _handle_darkweb(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        mentions = [a for a in added if isinstance(a, DarkwebMention)]
        assert mentions[0].source_type == "paste_site"

    @pytest.mark.asyncio
    async def test_darkweb_platform_results_key_used_when_no_mentions_key(self):
        from modules.pipeline.aggregator import _handle_darkweb
        from shared.models.darkweb import DarkwebMention

        session = _mock_session()
        result = _make_crawler_result(
            platform="darkweb_torch",
            identifier="target",
            data={"results": [{"url": "http://abc.onion", "title": "Hit"}]},
        )
        await _handle_darkweb(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        mentions = [a for a in added if isinstance(a, DarkwebMention)]
        assert len(mentions) == 1

    @pytest.mark.asyncio
    async def test_darkweb_empty_url_no_hash(self):
        from modules.pipeline.aggregator import _handle_darkweb
        from shared.models.darkweb import DarkwebMention

        session = _mock_session()
        result = _make_crawler_result(
            platform="darkweb_ahmia",
            identifier="x",
            data={"mentions": [{"title": "No URL here"}]},
        )
        await _handle_darkweb(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        mentions = [a for a in added if isinstance(a, DarkwebMention)]
        assert mentions[0].source_url_hashed is None


class TestAggregatorPeopleSearch:
    """Lines 195-196: people-search routing."""

    @pytest.mark.asyncio
    async def test_fastpeoplesearch_platform_routes_to_addresses(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="fastpeoplesearch",
            identifier="John Doe",
            data={"results": [{"address": "1 Main St", "city": "Dallas", "state": "TX"}]},
        )
        out = await aggregate_result(session, result)
        assert out.get("addresses") is True

    @pytest.mark.asyncio
    async def test_people_search_skips_non_dict_result_entries(self):
        from modules.pipeline.aggregator import _handle_people_search
        from shared.models.address import Address

        session = _mock_session()
        result = _make_crawler_result(
            platform="whitepages",
            identifier="Jane Doe",
            data={"results": ["string_entry", None, {"address": "5 Oak", "city": "Austin"}]},
        )
        await _handle_people_search(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        addresses = [a for a in added if isinstance(a, Address)]
        # Only the dict entry with a non-empty address should be written
        assert len(addresses) == 1
        assert addresses[0].city == "Austin"

    @pytest.mark.asyncio
    async def test_people_search_skips_empty_address_field(self):
        from modules.pipeline.aggregator import _handle_people_search
        from shared.models.address import Address

        session = _mock_session()
        result = _make_crawler_result(
            platform="truepeoplesearch",
            identifier="Empty",
            data={"results": [{"address": "", "city": "Nowhere"}]},
        )
        await _handle_people_search(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        assert not any(isinstance(a, Address) for a in added)


class TestAggregatorCourtRecords:
    """Lines 200-201, 627-632, 637-642: court records handler."""

    @pytest.mark.asyncio
    async def test_court_records_with_dates_parsed_correctly(self):
        from modules.pipeline.aggregator import _handle_court_records
        from shared.models.criminal import CriminalRecord

        session = _mock_session()
        result = _make_crawler_result(
            platform="court_courtlistener",
            identifier="Defendant",
            data={
                "cases": [
                    {
                        "charge": "Theft",
                        "arrest_date": "2020-06-15",
                        "disposition_date": "2021-01-10",
                        "level": "misdemeanor",
                        "case_number": "TX-2020-001",
                        "court": "Travis County Court",
                        "url": "https://court.example.com/case/1",
                    }
                ]
            },
        )
        count = await _handle_court_records(session, result, uuid.uuid4())
        assert count == 1
        added = [c.args[0] for c in session.add.call_args_list]
        rec = next(a for a in added if isinstance(a, CriminalRecord))
        assert rec.offense_level == "misdemeanor"
        from datetime import date

        assert rec.arrest_date == date(2020, 6, 15)
        assert rec.disposition_date == date(2021, 1, 10)

    @pytest.mark.asyncio
    async def test_court_records_bad_dates_set_to_none(self):
        from modules.pipeline.aggregator import _handle_court_records
        from shared.models.criminal import CriminalRecord

        session = _mock_session()
        result = _make_crawler_result(
            platform="court_state",
            identifier="Defendant",
            data={
                "cases": [
                    {
                        "charge": "DUI",
                        "arrest_date": "not-a-date",
                        "disposition_date": "also-bad",
                    }
                ]
            },
        )
        count = await _handle_court_records(session, result, uuid.uuid4())
        assert count == 1
        added = [c.args[0] for c in session.add.call_args_list]
        rec = next(a for a in added if isinstance(a, CriminalRecord))
        assert rec.arrest_date is None
        assert rec.disposition_date is None

    @pytest.mark.asyncio
    async def test_court_records_no_alert_when_no_cases(self):
        from modules.pipeline.aggregator import _handle_court_records
        from shared.models.alert import Alert

        session = _mock_session()
        result = _make_crawler_result(
            platform="court_courtlistener",
            identifier="Clean",
            data={"cases": []},
        )
        count = await _handle_court_records(session, result, uuid.uuid4())
        assert count == 0
        added = [c.args[0] for c in session.add.call_args_list]
        assert not any(isinstance(a, Alert) for a in added)

    @pytest.mark.asyncio
    async def test_court_records_non_dict_cases_skipped(self):
        from modules.pipeline.aggregator import _handle_court_records

        session = _mock_session()
        result = _make_crawler_result(
            platform="court_state",
            identifier="X",
            data={"cases": ["string", 42, None]},
        )
        count = await _handle_court_records(session, result, uuid.uuid4())
        assert count == 0


class TestAggregatorSexOffender:
    """Lines 205-206, 695-729: sex offender registry handler."""

    @pytest.mark.asyncio
    async def test_sex_offender_hit_creates_record_and_critical_alert(self):
        from modules.pipeline.aggregator import _handle_sex_offender
        from shared.constants import AlertSeverity
        from shared.models.alert import Alert
        from shared.models.criminal import CriminalRecord

        session = _mock_session()
        result = _make_crawler_result(
            platform="public_nsopw",
            identifier="John Smith",
            data={"hits": [{"offense": "Lewd Acts", "jurisdiction": "TX", "state": "Texas"}]},
        )
        count = await _handle_sex_offender(session, result, uuid.uuid4())
        assert count == 1
        added = [c.args[0] for c in session.add.call_args_list]
        rec = next(a for a in added if isinstance(a, CriminalRecord))
        alert = next(a for a in added if isinstance(a, Alert))
        assert rec.is_sex_offender is True
        assert rec.offense_level == "felony"
        assert alert.severity == AlertSeverity.CRITICAL.value

    @pytest.mark.asyncio
    async def test_sex_offender_uses_results_key_fallback(self):
        from modules.pipeline.aggregator import _handle_sex_offender

        session = _mock_session()
        result = _make_crawler_result(
            platform="public_nsopw",
            identifier="X",
            data={"results": [{"offense": "Indecent Exposure", "state": "CA"}]},
        )
        count = await _handle_sex_offender(session, result, uuid.uuid4())
        assert count == 1

    @pytest.mark.asyncio
    async def test_sex_offender_no_hits_returns_zero(self):
        from modules.pipeline.aggregator import _handle_sex_offender

        session = _mock_session()
        result = _make_crawler_result(
            platform="public_nsopw",
            identifier="Clean Person",
            data={"hits": []},
        )
        count = await _handle_sex_offender(session, result, uuid.uuid4())
        assert count == 0

    @pytest.mark.asyncio
    async def test_sex_offender_non_dict_hits_skipped(self):
        from modules.pipeline.aggregator import _handle_sex_offender

        session = _mock_session()
        result = _make_crawler_result(
            platform="public_nsopw",
            identifier="X",
            data={"hits": ["bad_string", 99]},
        )
        count = await _handle_sex_offender(session, result, uuid.uuid4())
        assert count == 0


class TestAggregatorBankruptcy:
    """Lines 209-211, 738-763: bankruptcy handler."""

    @pytest.mark.asyncio
    async def test_bankruptcy_creates_new_credit_profile(self):
        from modules.pipeline.aggregator import _handle_bankruptcy
        from shared.models.identity_document import CreditProfile

        session = _mock_session()
        result = _make_crawler_result(
            platform="bankruptcy_pacer",
            identifier="John Smith",
            data={"cases": [{"case_number": "BK-2019-001", "chapter": "7"}]},
        )
        await _handle_bankruptcy(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        cp = next((a for a in added if isinstance(a, CreditProfile)), None)
        assert cp is not None
        assert cp.has_bankruptcy is True
        assert cp.bankruptcy_count == 1

    @pytest.mark.asyncio
    async def test_bankruptcy_updates_existing_credit_profile(self):
        from modules.pipeline.aggregator import _handle_bankruptcy
        from shared.models.identity_document import CreditProfile

        pid = uuid.uuid4()
        existing = CreditProfile(
            id=uuid.uuid4(),
            person_id=pid,
            has_bankruptcy=False,
            bankruptcy_count=1,
        )
        session = _mock_session()
        # Make execute() return the existing CreditProfile
        session.execute = AsyncMock(return_value=_scalar_result(existing))

        result = _make_crawler_result(
            platform="bankruptcy_pacer",
            identifier="X",
            data={"filings": [{"case": "A"}, {"case": "B"}, {"case": "C"}]},
        )
        await _handle_bankruptcy(session, result, pid)
        # Existing record should be updated in-place (no new add)
        assert existing.has_bankruptcy is True
        assert existing.bankruptcy_count == 3

    @pytest.mark.asyncio
    async def test_bankruptcy_no_cases_returns_early(self):
        from modules.pipeline.aggregator import _handle_bankruptcy

        session = _mock_session()
        result = _make_crawler_result(
            platform="bankruptcy_pacer",
            identifier="X",
            data={},
        )
        await _handle_bankruptcy(session, result, uuid.uuid4())
        session.add.assert_not_called()


class TestAggregatorIdentifierHistory:
    """Lines 773, 780, 782: identifier history type assignment."""

    @pytest.mark.asyncio
    async def test_phone_platform_sets_phone_type(self):
        from modules.pipeline.aggregator import _record_identifier_history
        from shared.models.identifier_history import IdentifierHistory

        session = _mock_session()
        result = _make_crawler_result(
            platform="phone_carrier",
            identifier="+12125550000",
            data={},
        )
        await _record_identifier_history(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        hist = next((a for a in added if isinstance(a, IdentifierHistory)), None)
        assert hist is not None
        assert hist.type == "phone"

    @pytest.mark.asyncio
    async def test_email_platform_sets_email_type(self):
        from modules.pipeline.aggregator import _record_identifier_history
        from shared.models.identifier_history import IdentifierHistory

        session = _mock_session()
        result = _make_crawler_result(
            platform="email_breach",
            identifier="user@example.com",
            data={},
        )
        await _record_identifier_history(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        hist = next((a for a in added if isinstance(a, IdentifierHistory)), None)
        assert hist is not None
        assert hist.type == "email"

    @pytest.mark.asyncio
    async def test_social_platform_sets_handle_type(self):
        from modules.pipeline.aggregator import _record_identifier_history
        from shared.models.identifier_history import IdentifierHistory

        session = _mock_session()
        result = _make_crawler_result(
            platform="twitter",
            identifier="twitterhandle",
            data={},
        )
        await _record_identifier_history(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        hist = next((a for a in added if isinstance(a, IdentifierHistory)), None)
        assert hist is not None
        assert hist.type == "handle"

    @pytest.mark.asyncio
    async def test_unknown_platform_sets_identifier_type(self):
        from modules.pipeline.aggregator import _record_identifier_history
        from shared.models.identifier_history import IdentifierHistory

        session = _mock_session()
        result = _make_crawler_result(
            platform="some_other_platform",
            identifier="some_value",
            data={},
        )
        await _record_identifier_history(session, result, uuid.uuid4())
        added = [c.args[0] for c in session.add.call_args_list]
        hist = next((a for a in added if isinstance(a, IdentifierHistory)), None)
        assert hist is not None
        assert hist.type == "identifier"

    @pytest.mark.asyncio
    async def test_no_identifier_returns_early(self):
        from modules.pipeline.aggregator import _record_identifier_history

        session = _mock_session()
        result = _make_crawler_result(platform="instagram", identifier="", data={})
        # Empty string is falsy — should return without adding anything
        await _record_identifier_history(session, result, uuid.uuid4())
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_history_entry_updates_last_seen(self):
        from modules.pipeline.aggregator import _record_identifier_history
        from shared.models.identifier_history import IdentifierHistory

        pid = uuid.uuid4()
        existing = IdentifierHistory(
            id=uuid.uuid4(),
            person_id=pid,
            type="handle",
            value="user123",
            is_current=True,
        )
        session = _mock_session()
        session.execute = AsyncMock(return_value=_scalar_result(existing))

        result = _make_crawler_result(platform="instagram", identifier="user123", data={})
        await _record_identifier_history(session, result, pid)
        # Should have updated, not added a new row
        session.add.assert_not_called()
        assert existing.is_current is True


class TestAggregatorNormalizeOffenseLevel:
    """Lines 838-845: _normalize_offense_level pure function."""

    def test_felony_variants(self):
        from modules.pipeline.aggregator import _normalize_offense_level

        assert _normalize_offense_level("Felony") == "felony"
        assert _normalize_offense_level("FEL") == "felony"
        assert _normalize_offense_level("Class A Felony") == "felony"

    def test_misdemeanor_variants(self):
        from modules.pipeline.aggregator import _normalize_offense_level

        assert _normalize_offense_level("Misdemeanor") == "misdemeanor"
        assert _normalize_offense_level("MISD") == "misdemeanor"
        assert _normalize_offense_level("Class B Misdemeanor") == "misdemeanor"

    def test_infraction_variants(self):
        from modules.pipeline.aggregator import _normalize_offense_level

        assert _normalize_offense_level("infraction") == "infraction"
        assert _normalize_offense_level("civil violation") == "infraction"

    def test_unknown_returns_unknown(self):
        from modules.pipeline.aggregator import _normalize_offense_level

        assert _normalize_offense_level("random gibberish") == "unknown"

    def test_none_returns_none(self):
        from modules.pipeline.aggregator import _normalize_offense_level

        assert _normalize_offense_level(None) is None


class TestAggregatorBehavioural:
    """Lines 868-872, 890-893: _handle_behavioural update path."""

    @pytest.mark.asyncio
    async def test_behavioural_updates_existing_profile_maxes_scores(self):
        from modules.pipeline.aggregator import _handle_behavioural
        from shared.models.behavioural import BehaviouralProfile

        pid = uuid.uuid4()
        existing = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=pid,
            gambling_score=0.3,
            financial_distress_score=0.0,
            drug_signal_score=0.5,
            violence_score=0.0,
        )
        session = _mock_session()
        session.execute = AsyncMock(return_value=_scalar_result(existing))

        result = _make_crawler_result(
            platform="social_posts_analyzer",
            identifier="@user",
            data={
                "gambling_language": True,  # 1.0 > 0.3 → should update
                "substance_language": False,  # 0.0 < 0.5 → should keep 0.5
                "financial_stress_language": False,
                "aggression_language": True,  # 1.0 > 0.0 → should update
            },
        )
        await _handle_behavioural(session, result, pid)
        assert existing.gambling_score == 1.0
        assert existing.drug_signal_score == 0.5  # kept at max
        assert existing.violence_score == 1.0


class TestAggregatorUpsertPhoneIdentifier:
    """Lines 904-939: _upsert_phone_identifier."""

    @pytest.mark.asyncio
    async def test_new_phone_identifier_inserted(self):
        from modules.pipeline.aggregator import _upsert_phone_identifier

        session = _mock_session()
        await _upsert_phone_identifier(session, "+12125550001", uuid.uuid4(), "whatsapp")
        # Upsert uses session.execute (pg_insert) not session.add
        assert session.execute.called

    @pytest.mark.asyncio
    async def test_existing_phone_identifier_increments_corroboration(self):
        from modules.pipeline.aggregator import _upsert_phone_identifier
        from shared.models.identifier import Identifier

        pid = uuid.uuid4()
        existing = Identifier(
            id=uuid.uuid4(),
            person_id=pid,
            type="phone",
            value="+12125550002",
            normalized_value="+12125550002",
            corroboration_count=1,
            meta={},
        )
        session = _mock_session()
        session.execute = AsyncMock(return_value=_scalar_result(existing))

        await _upsert_phone_identifier(session, "+1 212 555 0002", pid, "telegram")
        # Should have bumped corroboration, not created a new record
        session.add.assert_not_called()
        assert existing.corroboration_count == 2


class TestAggregatorSourceReliabilityUpdate:
    """Lines 800, 817-818: source_reliability update branch."""

    @pytest.mark.asyncio
    async def test_high_reliability_source_increments_corroboration(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(
            id=uuid.uuid4(),
            full_name="Test User",
            source_reliability=0.5,
            corroboration_count=1,
        )
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            identifier="testuser",
            data={"handle": "testuser"},
            source_reliability=0.85,
        )
        await aggregate_result(session, result, person_id=str(person.id))
        assert person.corroboration_count == 2
        assert person.source_reliability > 0.5

    @pytest.mark.asyncio
    async def test_low_reliability_source_does_not_update(self):
        from modules.pipeline.aggregator import aggregate_result
        from shared.models.person import Person

        person = Person(
            id=uuid.uuid4(),
            full_name="Test User",
            source_reliability=0.5,
            corroboration_count=1,
        )
        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        result = _make_crawler_result(
            platform="instagram",
            identifier="testuser",
            data={"handle": "testuser"},
            source_reliability=0.3,
        )
        original_reliability = person.source_reliability
        await aggregate_result(session, result, person_id=str(person.id))
        assert person.source_reliability == original_reliability


class TestAggregatorGetOrCreatePerson:
    """Lines 265-266, 279: person lookup edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_person_id_uuid_falls_through_to_create(self):
        from modules.pipeline.aggregator import _get_or_create_person
        from shared.models.person import Person

        session = _mock_session()
        result = _make_crawler_result(data={"full_name": "New Person"})

        person = await _get_or_create_person(session, "not-a-valid-uuid", result)
        assert isinstance(person, Person)

    @pytest.mark.asyncio
    async def test_existing_person_found_by_name(self):
        from modules.pipeline.aggregator import _get_or_create_person
        from shared.models.person import Person

        pid = uuid.uuid4()
        existing = Person(id=pid, full_name="Alice Smith")
        session = _mock_session()
        session.execute = AsyncMock(return_value=_scalar_result(existing))

        result = _make_crawler_result(data={"full_name": "Alice Smith"})
        person = await _get_or_create_person(session, None, result)
        assert person is existing


class TestAggregatorBehaviouralPlatform:
    """Lines 217-219: behavioural platform routing."""

    @pytest.mark.asyncio
    async def test_social_posts_analyzer_routes_to_behavioural(self):
        from modules.pipeline.aggregator import aggregate_result

        session = _mock_session()
        result = _make_crawler_result(
            platform="social_posts_analyzer",
            identifier="@user",
            data={
                "gambling_language": False,
                "financial_stress_language": True,
                "substance_language": False,
                "aggression_language": False,
            },
        )
        out = await aggregate_result(session, result)
        assert out.get("behavioural") is True


# ===========================================================================
# 2. ENRICHMENT ORCHESTRATOR — uncovered lines
# ===========================================================================


class TestEnrichmentOrchestratorRunBurner:
    """Lines 179-186: _run_burner with and without phone identifiers.

    Note: compute_burner_score / persist_burner_assessment are imported
    *inside* _run_burner, so we patch them at their origin module, not on
    the orchestrator module namespace.
    """

    @pytest.mark.asyncio
    async def test_run_burner_no_phone_identifiers_skips(self):
        from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator

        orchestrator = EnrichmentOrchestrator()
        session = _mock_session()
        scalars_m = MagicMock()
        scalars_m.all.return_value = []
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_m
        session.execute = AsyncMock(return_value=exec_result)

        with patch("modules.enrichers.burner_detector.compute_burner_score") as mock_score:
            await orchestrator._run_burner("person-1", session)
        mock_score.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_burner_calls_persist_for_each_phone(self):
        from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator

        orchestrator = EnrichmentOrchestrator()
        session = _mock_session()

        phone1 = MagicMock()
        phone1.id = uuid.uuid4()
        phone1.value = "+12125550001"

        phone2 = MagicMock()
        phone2.id = uuid.uuid4()
        phone2.value = "+12125550002"

        scalars_m = MagicMock()
        scalars_m.all.return_value = [phone1, phone2]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars_m
        session.execute = AsyncMock(return_value=exec_result)

        mock_score = MagicMock(return_value=MagicMock())
        mock_persist = AsyncMock()

        with (
            patch("modules.enrichers.burner_detector.compute_burner_score", mock_score),
            patch("modules.enrichers.burner_detector.persist_burner_assessment", mock_persist),
        ):
            await orchestrator._run_burner("person-1", session)

        assert mock_score.call_count == 2
        assert mock_persist.await_count == 2


class TestEnrichmentOrchestratorRelationshipScore:
    """Lines 205-237: _run_relationship_score."""

    @pytest.mark.asyncio
    async def test_run_relationship_score_no_person_returns_early(self):
        from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator

        orchestrator = EnrichmentOrchestrator()
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        # Should not raise
        await orchestrator._run_relationship_score(str(uuid.uuid4()), session)
        session.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_relationship_score_updates_when_higher(self):
        from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator
        from shared.models.person import Person

        orchestrator = EnrichmentOrchestrator()
        pid = uuid.uuid4()
        person = Person(id=pid, full_name="Bob", relationship_score=0.0)

        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        # social_count=3, ident_count=2, addr_count=1 → breadth=0.48 → score=0.48
        call_results = iter([3, 2, 1])

        def _scalar_side(*args, **kwargs):
            rm = MagicMock()
            rm.scalar.return_value = next(call_results)
            return rm

        session.execute = AsyncMock(side_effect=lambda stmt: _scalar_side())

        await orchestrator._run_relationship_score(str(pid), session)
        assert person.relationship_score > 0.0
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_relationship_score_no_update_when_lower(self):
        from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator
        from shared.models.person import Person

        orchestrator = EnrichmentOrchestrator()
        pid = uuid.uuid4()
        person = Person(id=pid, full_name="Carol", relationship_score=0.99)

        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        # Zero everything → breadth=0 → score=0 — should not update
        call_results = iter([0, 0, 0])

        def _scalar_side(*args, **kwargs):
            rm = MagicMock()
            rm.scalar.return_value = next(call_results)
            return rm

        session.execute = AsyncMock(side_effect=lambda stmt: _scalar_side())

        await orchestrator._run_relationship_score(str(pid), session)
        assert person.relationship_score == 0.99
        session.flush.assert_not_awaited()


class TestEnrichmentOrchestratorPublishCompletion:
    """Lines 253-254: publish exception swallowed."""

    @pytest.mark.asyncio
    async def test_publish_completion_exception_is_swallowed(self):
        from modules.pipeline.enrichment_orchestrator import (
            EnrichmentOrchestrator,
            EnrichmentReport,
        )

        orchestrator = EnrichmentOrchestrator()
        report = EnrichmentReport(
            person_id="p1",
            started_at="2024-01-01T00:00:00+00:00",
            finished_at="2024-01-01T00:00:01+00:00",
            total_duration_ms=100.0,
            steps=[],
        )

        with patch("modules.pipeline.enrichment_orchestrator.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.publish = AsyncMock(side_effect=ConnectionError("bus is down"))
            # Must not raise
            await orchestrator._publish_completion("p1", report)


# ===========================================================================
# 3. INGESTION DAEMON — uncovered lines
# ===========================================================================


class TestIngestionDaemonUncovered:
    """Lines 96-100, 106-107: pivot success logging, enrich failure swallowed."""

    @pytest.mark.asyncio
    async def test_pivot_queues_logged_when_n_positive(self):
        from modules.pipeline.ingestion_daemon import IngestionDaemon

        daemon = IngestionDaemon()
        payload = {
            "platform": "instagram",
            "identifier": "user",
            "found": True,
            "data": {"handle": "user"},
            "person_id": "00000000-0000-0000-0000-000000000001",
            "result": {},
            "source_reliability": 0.7,
        }

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.rollback = AsyncMock()

        with (
            patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
            patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
            patch(
                "modules.pipeline.ingestion_daemon.aggregate_result",
                new=AsyncMock(return_value={"person_id": "00000000-0000-0000-0000-000000000001"}),
            ),
            patch(
                "modules.pipeline.ingestion_daemon.pivot_from_result",
                new=AsyncMock(return_value=3),
            ),
            patch("modules.pipeline.ingestion_daemon._orchestrator") as mock_orch,
        ):
            mock_bus.dequeue = AsyncMock(return_value=payload)
            mock_bus.enqueue = AsyncMock()
            mock_orch.enrich_person = AsyncMock()
            await daemon._process_one()

        # Verify enqueue was called (pivot ran)
        mock_bus.enqueue.assert_awaited()

    @pytest.mark.asyncio
    async def test_enrichment_failure_does_not_propagate(self):
        from modules.pipeline.ingestion_daemon import IngestionDaemon

        daemon = IngestionDaemon()
        payload = {
            "platform": "instagram",
            "identifier": "user",
            "found": True,
            "data": {"handle": "user"},
            "person_id": "00000000-0000-0000-0000-000000000001",
            "result": {},
            "source_reliability": 0.7,
        }

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.rollback = AsyncMock()

        async def _boom(*args, **kwargs):
            raise RuntimeError("enrichment down")

        with (
            patch("modules.pipeline.ingestion_daemon.event_bus") as mock_bus,
            patch("modules.pipeline.ingestion_daemon.AsyncSessionLocal", return_value=mock_session),
            patch(
                "modules.pipeline.ingestion_daemon.aggregate_result",
                new=AsyncMock(return_value={"person_id": "00000000-0000-0000-0000-000000000001"}),
            ),
            patch(
                "modules.pipeline.ingestion_daemon.pivot_from_result",
                new=AsyncMock(return_value=0),
            ),
            patch("modules.pipeline.ingestion_daemon._orchestrator") as mock_orch,
        ):
            mock_bus.dequeue = AsyncMock(return_value=payload)
            mock_bus.enqueue = AsyncMock()
            mock_orch.enrich_person = AsyncMock(side_effect=_boom)
            # Must not raise
            await daemon._process_one()


# ===========================================================================
# 4. ENTITY GRAPH — uncovered lines
# ===========================================================================


class TestEntityGraphUncovered:
    """Lines 77, 89, 116, 145, 161-162, 167-170, 187-194, 208-211, 216-225."""

    def _make_session(self, side_effects: list) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=side_effects)
        return session

    def _empty(self):
        return _scalars_result([])

    @pytest.mark.asyncio
    async def test_empty_frontier_terminates_early(self):
        """depth=2 but no persons found → next_frontier stays empty, hop2 breaks early."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        # Hop1 always fires 6 queries: persons, addresses, identifiers, employment, social, rels.
        # Person query returns empty → no nodes added. next_frontier stays empty.
        # Hop2 hits `if not frontier: break` before any queries.
        session = self._make_session(
            [
                _scalars_result([]),  # hop1: persons (empty)
                _scalars_result([]),  # hop1: addresses
                _scalars_result([]),  # hop1: identifiers
                _scalars_result([]),  # hop1: employment
                _scalars_result([]),  # hop1: social
                _scalars_result([]),  # hop1: relationships
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=2)
        assert graph["nodes"] == []
        assert graph["edges"] == []

    @pytest.mark.asyncio
    async def test_already_visited_person_not_added_twice(self):
        """Person visited in hop 1 should be skipped in hop 2 if re-queued."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Alice"
        person.default_risk_score = 0.1

        # Depth 2 → two iterations. Second hop returns same person (via relationship)
        session = self._make_session(
            [
                _scalars_result([person]),  # hop1: persons
                self._empty(),  # hop1: addresses
                self._empty(),  # hop1: identifiers
                self._empty(),  # hop1: employment
                self._empty(),  # hop1: social
                self._empty(),  # hop1: relationships → next_frontier empty
                # hop2 never runs because frontier is empty after subtract
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=2)
        person_nodes = [n for n in graph["nodes"] if n["type"] == "person"]
        assert len(person_nodes) == 1

    @pytest.mark.asyncio
    async def test_identifier_ssn_creates_identifier_node(self):
        """SSN identifier type → node_type 'identifier'."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Dave"
        person.default_risk_score = 0.0

        ident = MagicMock()
        ident.id = uuid.uuid4()
        ident.person_id = pid_uuid
        ident.type = "ssn"
        ident.value = "123-45-6789"
        ident.confidence = 0.95

        session = self._make_session(
            [
                _scalars_result([person]),
                self._empty(),  # addresses
                _scalars_result([ident]),  # identifiers
                self._empty(),  # employment
                self._empty(),  # social
                self._empty(),  # relationships
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=1)
        ident_nodes = [n for n in graph["nodes"] if n["type"] == "identifier"]
        assert len(ident_nodes) == 1

    @pytest.mark.asyncio
    async def test_identifier_unknown_type_excluded(self):
        """Identifier types other than phone/email/ssn/passport should be excluded."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Eve"
        person.default_risk_score = 0.0

        ident = MagicMock()
        ident.id = uuid.uuid4()
        ident.person_id = pid_uuid
        ident.type = "username"  # not in the allowed set
        ident.value = "evey"
        ident.confidence = 0.9

        session = self._make_session(
            [
                _scalars_result([person]),
                self._empty(),
                _scalars_result([ident]),
                self._empty(),
                self._empty(),
                self._empty(),
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=1)
        ident_nodes = [n for n in graph["nodes"] if n["type"] in ("identifier", "phone", "email")]
        assert len(ident_nodes) == 0

    @pytest.mark.asyncio
    async def test_employment_former_employee_creates_employee_edge(self):
        """Former employee (is_current=False, no job_title) → 'employee' edge at conf 0.6."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Frank"
        person.default_risk_score = 0.0

        emp = MagicMock()
        emp.person_id = pid_uuid
        emp.employer_name = "Old Corp"
        emp.job_title = None
        emp.is_current = False

        session = self._make_session(
            [
                _scalars_result([person]),
                self._empty(),
                self._empty(),
                _scalars_result([emp]),
                self._empty(),
                self._empty(),
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=1)
        employee_edges = [e for e in graph["edges"] if e["type"] == "employee"]
        assert len(employee_edges) == 1
        assert employee_edges[0]["confidence"] == 0.6

    @pytest.mark.asyncio
    async def test_social_profile_creates_social_node(self):
        """Social profile → has_social edge + social_profile node."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Grace"
        person.default_risk_score = 0.0

        sp = MagicMock()
        sp.id = uuid.uuid4()
        sp.person_id = pid_uuid
        sp.platform = "twitter"
        sp.handle = "grace_tweet"
        sp.platform_user_id = None

        session = self._make_session(
            [
                _scalars_result([person]),
                self._empty(),
                self._empty(),
                self._empty(),
                _scalars_result([sp]),
                self._empty(),
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=1)
        social_nodes = [n for n in graph["nodes"] if n["type"] == "social_profile"]
        assert len(social_nodes) == 1
        assert "twitter" in social_nodes[0]["label"]
        social_edges = [e for e in graph["edges"] if e["type"] == "has_social"]
        assert len(social_edges) == 1

    @pytest.mark.asyncio
    async def test_relationship_expands_frontier_with_stub_node(self):
        """Relationship edge creates a stub node for the connected person."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)
        other_pid = uuid.uuid4()

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Harry"
        person.default_risk_score = 0.0

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.person_a_id = pid_uuid
        rel.person_b_id = other_pid
        rel.rel_type = "associate"
        rel.score = 0.7

        session = self._make_session(
            [
                _scalars_result([person]),  # hop1: persons
                self._empty(),  # addresses
                self._empty(),  # identifiers
                self._empty(),  # employment
                self._empty(),  # social
                _scalars_result([rel]),  # relationships → other_pid in next_frontier
                _scalars_result([]),  # hop2: persons (other person not in DB)
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=2)
        # Stub node for other_pid should exist
        node_ids = [n["id"] for n in graph["nodes"]]
        assert str(other_pid) in node_ids
        rel_edges = [e for e in graph["edges"] if e["type"] == "associate"]
        assert len(rel_edges) == 1

    @pytest.mark.asyncio
    async def test_duplicate_relationship_deduplication(self):
        """Same relationship traversed from both sides → only one edge emitted."""
        from modules.graph.entity_graph import EntityGraphBuilder

        person_id = str(uuid.uuid4())
        pid_uuid = uuid.UUID(person_id)
        other_pid = uuid.uuid4()

        person = MagicMock()
        person.id = pid_uuid
        person.full_name = "Iris"
        person.default_risk_score = 0.0

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.person_a_id = pid_uuid
        rel.person_b_id = other_pid
        rel.rel_type = "sibling"
        rel.score = 0.9

        # Duplicate: same rel appears twice in rel_by_pid (both sides map to it)
        session = self._make_session(
            [
                _scalars_result([person]),
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
                _scalars_result([rel, rel]),  # same rel twice
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
                self._empty(),
            ]
        )
        builder = EntityGraphBuilder()
        graph = await builder.build_person_graph(person_id, session, depth=2)
        sibling_edges = [e for e in graph["edges"] if e["type"] == "sibling"]
        # Dedup by edge_keys frozenset — should be exactly one
        assert len(sibling_edges) == 1

    @pytest.mark.asyncio
    async def test_find_shared_connections_detects_shared_employer(self):
        from modules.graph.entity_graph import EntityGraphBuilder

        pid_a = str(uuid.uuid4())
        pid_b = str(uuid.uuid4())
        pid_a_uuid = uuid.UUID(pid_a)
        pid_b_uuid = uuid.UUID(pid_b)

        def _emp(pid):
            e = MagicMock()
            e.person_id = pid
            e.employer_name = "Shared Corp"
            return e

        session = self._make_session(
            [
                self._empty(),  # identifiers (no shared)
                self._empty(),  # addresses (no shared)
                _scalars_result([_emp(pid_a_uuid), _emp(pid_b_uuid)]),  # employment
            ]
        )
        builder = EntityGraphBuilder()
        shared = await builder.find_shared_connections([pid_a, pid_b], session)
        employer_hits = [s for s in shared if s["type"] == "employer"]
        assert len(employer_hits) == 1
        assert employer_hits[0]["risk_implication"] == "shared_employer"

    @pytest.mark.asyncio
    async def test_detect_fraud_rings_phone_cluster(self):
        from modules.graph.entity_graph import EntityGraphBuilder

        pids = [uuid.uuid4() for _ in range(3)]

        def _phone(pid):
            p = MagicMock()
            p.person_id = pid
            p.value = "+12125559999"
            p.normalized_value = "+12125559999"
            return p

        phone_rows = [_phone(p) for p in pids]

        session = self._make_session(
            [
                self._empty(),  # addresses
                _scalars_result(phone_rows),  # phones
            ]
        )
        builder = EntityGraphBuilder()
        rings = await builder.detect_fraud_rings(session, min_connections=3)
        phone_rings = [r for r in rings if "phone:" in r["shared_element"]]
        assert len(phone_rings) == 1
        assert phone_rings[0]["risk_score"] >= 0.5


# ===========================================================================
# 5. COMPANY INTEL — uncovered lines
# ===========================================================================


class TestCompanyIntelUncovered:
    """Lines 91-92, 154, 222, 242-251."""

    def _make_session(self, *results) -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=list(results))
        return session

    def _make_emp(self, employer, person_id=None, location=None, is_current=False):
        row = MagicMock()
        row.person_id = person_id
        row.employer_name = employer
        row.job_title = None
        row.is_current = is_current
        row.location = location
        row.meta = {}
        return row

    def test_build_record_location_single_part_city_only(self):
        """Line 91-92: location with single part → city only, state=None."""
        from modules.graph.company_intel import _build_record_from_rows

        emp = self._make_emp("MonoCity Corp", location="Austin")
        record = _build_record_from_rows("MonoCity Corp", [emp], [])
        assert record.hq_address is not None
        assert record.hq_address["city"] == "Austin"
        assert record.hq_address["state"] is None

    def test_build_record_no_location_hq_address_is_none(self):
        from modules.graph.company_intel import _build_record_from_rows

        emp = self._make_emp("No Location Co", location=None)
        record = _build_record_from_rows("No Location Co", [emp], [])
        assert record.hq_address is None

    @pytest.mark.asyncio
    async def test_search_company_state_filter_eliminates_all_rows(self):
        """Line 154: state filter leaves no rows → returns []."""
        from modules.graph.company_intel import CompanyIntelligenceEngine

        emp = self._make_emp("Some Corp", location="Austin, TX")
        session = self._make_session(_scalars_result([emp]))
        engine = CompanyIntelligenceEngine()
        # Filter by CA — Austin TX should be excluded
        result = await engine.search_company("Some", "CA", session)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_company_network_person_without_person_map_entry(self):
        """Line 222: emp row with person_id that isn't in person_map → uses pid as label."""
        from modules.graph.company_intel import CompanyIntelligenceEngine

        pid = uuid.uuid4()
        emp = self._make_emp("Orphan Corp", person_id=pid, is_current=True)
        # Return employment but empty persons
        session = self._make_session(
            _scalars_result([emp]),  # employment
            _scalars_result([]),  # persons → empty person_map
        )
        engine = CompanyIntelligenceEngine()
        network = await engine.get_company_network("Orphan Corp", session)
        person_nodes = [n for n in network["nodes"] if n["type"] == "person"]
        assert len(person_nodes) == 1
        # Label should fall back to pid string
        assert person_nodes[0]["label"] == str(pid)

    @pytest.mark.asyncio
    async def test_get_company_network_with_relationships_between_persons(self):
        """Lines 242-251: multiple persons → relationship query fires."""
        from modules.graph.company_intel import CompanyIntelligenceEngine

        pid_a = uuid.uuid4()
        pid_b = uuid.uuid4()
        person_a = MagicMock()
        person_a.id = pid_a
        person_a.full_name = "Alice"
        person_a.default_risk_score = 0.0

        person_b = MagicMock()
        person_b.id = pid_b
        person_b.full_name = "Bob"
        person_b.default_risk_score = 0.0

        emp_a = self._make_emp("TwoPerson Inc", person_id=pid_a, is_current=True)
        emp_b = self._make_emp("TwoPerson Inc", person_id=pid_b, is_current=False)

        rel = MagicMock()
        rel.person_a_id = pid_a
        rel.person_b_id = pid_b
        rel.rel_type = "colleague"
        rel.score = 0.8

        session = self._make_session(
            _scalars_result([emp_a, emp_b]),  # employment
            _scalars_result([person_a, person_b]),  # persons
            _scalars_result([rel]),  # relationships (2 persons → fires)
        )
        engine = CompanyIntelligenceEngine()
        network = await engine.get_company_network("TwoPerson Inc", session)
        rel_edges = [e for e in network["edges"] if e["type"] == "colleague"]
        assert len(rel_edges) == 1
        assert rel_edges[0]["confidence"] == 0.8


# ===========================================================================
# 6. DISPATCHER — uncovered lines (47, 159, 181)
# ===========================================================================


class TestDispatcherUncovered:
    """Lines 47, 159, 181."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        from modules.dispatcher.dispatcher import CrawlDispatcher

        d = CrawlDispatcher()
        d._running = True
        await d.stop()
        assert d._running is False

    @pytest.mark.asyncio
    async def test_update_job_status_skips_when_no_job_id(self):
        """Line 159: job_id is None → method returns immediately."""
        from modules.dispatcher.dispatcher import CrawlDispatcher
        from shared.constants import CrawlStatus

        d = CrawlDispatcher()
        session = _mock_session()
        # Should not raise and should not execute any SQL
        await d._update_job_status(session, None, CrawlStatus.DONE)
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_log_crawl_skips_when_no_job_id(self):
        """Line 181: job_id is None → no CrawlLog created."""
        from modules.dispatcher.dispatcher import CrawlDispatcher

        d = CrawlDispatcher()
        session = _mock_session()
        await d._log_crawl(session, None, "instagram", "user", True, 500)
        session.add.assert_not_called()


# ===========================================================================
# 7. GROWTH DAEMON — uncovered lines (100, 115-119, 122-123)
# ===========================================================================


class TestGrowthDaemonUncovered:
    """Lines 100, 115-119, 122-123."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()
        gd._running = True
        await gd.stop()
        assert gd._running is False

    @pytest.mark.asyncio
    async def test_handle_event_ignores_non_crawl_complete(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()
        with patch.object(gd, "_get_person_identifiers", new=AsyncMock()) as mock_get:
            await gd._handle_event({"event": "something_else", "person_id": "abc"})
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_event_ignores_missing_person_id(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()
        with patch.object(gd, "_get_person_identifiers", new=AsyncMock()) as mock_get:
            await gd._handle_event({"event": "crawl_complete"})
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_event_stops_at_max_depth(self):
        from modules.dispatcher.growth_daemon import MAX_DEPTH, GrowthDaemon

        gd = GrowthDaemon()
        with patch.object(gd, "_get_person_identifiers", new=AsyncMock()) as mock_get:
            await gd._handle_event(
                {"event": "crawl_complete", "person_id": "p1", "depth": MAX_DEPTH}
            )
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_event_fans_out_jobs_for_identifiers(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()

        phone_ident = MagicMock()
        phone_ident.type = "phone"
        phone_ident.value = "+12125550001"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "modules.dispatcher.growth_daemon.AsyncSessionLocal",
                return_value=mock_session,
            ),
            patch.object(
                gd,
                "_get_person_identifiers",
                new=AsyncMock(return_value=[phone_ident]),
            ),
            patch.object(gd, "_fan_out", new=AsyncMock()) as mock_fan_out,
        ):
            await gd._handle_event({"event": "crawl_complete", "person_id": "p1", "depth": 0})

        mock_fan_out.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fan_out_respects_kill_switch(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()
        ident = MagicMock()
        ident.type = "phone"
        ident.value = "+12125550002"

        with (
            patch("modules.dispatcher.growth_daemon.settings") as mock_settings,
            patch(
                "modules.dispatcher.growth_daemon.dispatch_job", new=AsyncMock()
            ) as mock_dispatch,
            patch("modules.crawlers.registry.get_crawler", return_value=object()),
            patch.object(gd, "_job_exists", new=AsyncMock(return_value=False)),
        ):
            # Disable burner check kill switch
            mock_settings.enable_burner_check = False
            await gd._fan_out(ident, "p1", depth=0, remaining_budget=50)

        # No burner-check jobs dispatched when burner checks are disabled
        dispatched_platforms = [
            c.kwargs.get("platform") or c.args[0] for c in mock_dispatch.await_args_list
        ]
        assert "phone_carrier" not in dispatched_platforms
        assert "phone_fonefinder" not in dispatched_platforms
        assert "phone_truecaller" not in dispatched_platforms
        assert "phone_numlookup" not in dispatched_platforms

    @pytest.mark.asyncio
    async def test_fan_out_skips_existing_job(self):
        from modules.dispatcher.growth_daemon import GrowthDaemon

        gd = GrowthDaemon()
        ident = MagicMock()
        ident.type = "username"
        ident.value = "sherlock_user"

        with (
            patch(
                "modules.dispatcher.growth_daemon.dispatch_job", new=AsyncMock()
            ) as mock_dispatch,
            patch.object(gd, "_job_exists", new=AsyncMock(return_value=True)),
        ):
            await gd._fan_out(ident, "p1", depth=0, remaining_budget=50)

        mock_dispatch.assert_not_awaited()


# ===========================================================================
# 8. INDEX DAEMON — uncovered lines (76-77, 120-132, 135-138)
# ===========================================================================


class TestIndexDaemonUncovered:
    """Lines 76-77, 120-132, 135-138."""

    @pytest.mark.asyncio
    async def test_process_one_logs_warning_on_invalid_uuid(self):
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("modules.search.index_daemon.event_bus") as mock_bus,
            patch("modules.search.index_daemon.AsyncSessionLocal", return_value=mock_session),
        ):
            mock_bus.dequeue = AsyncMock(return_value={"person_id": "not-a-uuid"})
            # Should not raise — bad UUID is caught
            await daemon._process_one()

    @pytest.mark.asyncio
    async def test_index_person_builds_addresses_text_from_addr_parts(self):
        """Lines 120-132: address text assembly with multiple fields."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()

        pid = uuid.uuid4()
        person = MagicMock()
        person.id = pid
        person.full_name = "Test User"
        person.date_of_birth = None
        person.default_risk_score = 0.3
        person.nationality = "US"
        person.darkweb_exposure = 0
        person.verification_status = "verified"
        person.composite_quality = 0.8
        person.corroboration_count = 3
        person.created_at = None

        addr = MagicMock()
        addr.is_current = True
        addr.street = "99 Oak Street"
        addr.city = "Austin"
        addr.state_province = "TX"
        addr.postal_code = "78701"
        addr.country = "US"

        idents: list = []
        profiles: list = []

        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result(idents)
            elif call_count == 2:
                return _scalars_result([addr])
            else:
                return _scalars_result(profiles)

        session.execute = AsyncMock(side_effect=_side_effect)

        with patch("modules.search.index_daemon.meili_indexer") as mock_meili:
            mock_meili.index_person = AsyncMock(return_value=True)
            await daemon._index_person(session, pid)

        mock_meili.index_person.assert_awaited_once()
        doc = mock_meili.index_person.call_args.args[0]
        assert doc["city"] == "Austin"
        assert doc["state_province"] == "TX"
        assert "99 Oak Street" in doc["addresses_text"][0]

    @pytest.mark.asyncio
    async def test_index_person_risk_tier_labels(self):
        """Lines 135-138: correct risk_tier assignment for each threshold band."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()

        thresholds = [
            (0.85, "do_not_lend"),
            (0.65, "high_risk"),
            (0.45, "medium_risk"),
            (0.25, "low_risk"),
            (0.05, "preferred"),
        ]

        for score, expected_tier in thresholds:
            pid = uuid.uuid4()
            person = MagicMock()
            person.id = pid
            person.full_name = "Tier Test"
            person.date_of_birth = None
            person.default_risk_score = score
            person.nationality = None
            person.darkweb_exposure = 0
            person.verification_status = None
            person.composite_quality = None
            person.corroboration_count = None
            person.created_at = None

            session = _mock_session()
            session.get = AsyncMock(return_value=person)
            session.execute = AsyncMock(return_value=_scalars_result([]))

            with patch("modules.search.index_daemon.meili_indexer") as mock_meili:
                mock_meili.index_person = AsyncMock(return_value=True)
                await daemon._index_person(session, pid)

            doc = mock_meili.index_person.call_args.args[0]
            assert doc["risk_tier"] == expected_tier, (
                f"Score {score} expected tier {expected_tier}, got {doc['risk_tier']}"
            )

    @pytest.mark.asyncio
    async def test_index_person_not_found_returns_early(self):
        """Person not in DB → early return, meili never called."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        with patch("modules.search.index_daemon.meili_indexer") as mock_meili:
            mock_meili.index_person = AsyncMock()
            await daemon._index_person(session, uuid.uuid4())

        mock_meili.index_person.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_index_person_meili_failure_logged(self):
        """meili_indexer returns False → daemon logs error but does not raise."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()
        pid = uuid.uuid4()
        person = MagicMock()
        person.id = pid
        person.full_name = "Failed Index"
        person.date_of_birth = None
        person.default_risk_score = 0.0
        person.nationality = None
        person.darkweb_exposure = 0
        person.verification_status = None
        person.composite_quality = None
        person.corroboration_count = None
        person.created_at = None

        session = _mock_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        with patch("modules.search.index_daemon.meili_indexer") as mock_meili:
            mock_meili.index_person = AsyncMock(return_value=False)
            # Must not raise
            await daemon._index_person(session, pid)

        mock_meili.index_person.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_one_missing_person_id_returns_early(self):
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("modules.search.index_daemon.event_bus") as mock_bus,
            patch("modules.search.index_daemon.AsyncSessionLocal", return_value=mock_session),
        ):
            mock_bus.dequeue = AsyncMock(return_value={"person_id": None})
            await daemon._process_one()
            mock_session.__aenter__.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_index_person_addresses_text_caps_at_five(self):
        """Verifies only first 5 addresses are processed."""
        from modules.search.index_daemon import IndexDaemon

        daemon = IndexDaemon()
        pid = uuid.uuid4()
        person = MagicMock()
        person.id = pid
        person.full_name = "Many Addresses"
        person.date_of_birth = None
        person.default_risk_score = 0.1
        person.nationality = None
        person.darkweb_exposure = 0
        person.verification_status = None
        person.composite_quality = None
        person.corroboration_count = None
        person.created_at = None

        def _addr(n):
            a = MagicMock()
            a.is_current = False
            a.street = f"{n} Test St"
            a.city = "City"
            a.state_province = "ST"
            a.postal_code = None
            a.country = "US"
            return a

        # 8 addresses → only first 5 should appear in addresses_text
        addresses = [_addr(i) for i in range(8)]

        session = _mock_session()
        session.get = AsyncMock(return_value=person)

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalars_result([])  # identifiers
            elif call_count == 2:
                return _scalars_result(addresses)
            else:
                return _scalars_result([])  # profiles

        session.execute = AsyncMock(side_effect=_side_effect)

        with patch("modules.search.index_daemon.meili_indexer") as mock_meili:
            mock_meili.index_person = AsyncMock(return_value=True)
            await daemon._index_person(session, pid)

        doc = mock_meili.index_person.call_args.args[0]
        assert len(doc["addresses_text"]) == 5
