"""
test_pep_enricher_daemon.py — Unit tests for modules/enrichers/pep_enricher.py.

Covers:
  - start(): one iteration then stops via sleep side_effect
  - start(): batch exception swallowed, sleep still called
  - _process_pending(): queries DB, iterates person_ids, calls check_person
  - _process_pending(): per-person exception swallowed
  - check_person(): person not found → early return
  - check_person(): no crawler matches → is_pep=False, no timeline events
  - check_person(): matches found → is_pep=True, highest_level resolved, meta updated
  - check_person(): multiple matches, highest tier selected correctly
  - check_person(): crawler exception swallowed per-crawler
  - _persist_pep_record(): inserts new PepClassification
  - _persist_pep_record(): updates existing when new confidence is higher
  - _persist_pep_record(): updates end_date on existing when newly available
  - _persist_pep_record(): does NOT update confidence when new is lower
  - _create_pep_timeline_events(): calls builder._upsert_event per match with start_date
  - _create_pep_timeline_events(): skips matches with no start_date
  - _create_pep_timeline_events(): swallows builder exception
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.pep_enricher import _LEVEL_RANK, PepEnricher

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_person(name: str = "Jane Smith", meta: dict | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = name
    p.meta = meta or {}
    return p


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _fetchall_result(rows: list) -> MagicMock:
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _pep_match(
    is_pep: bool = True,
    level: str = "tier2",
    position: str = "Senator",
    org: str = "Congress",
    confidence: float = 0.9,
    start_date: str | None = "2020-01-01",
    end_date: str | None = None,
) -> dict:
    return {
        "is_pep": is_pep,
        "pep_level": level,
        "pep_category": "government",
        "position_title": position,
        "organization": org,
        "confidence": confidence,
        "start_date": start_date,
        "end_date": end_date,
        "source_platform": "open_pep_search",
    }


# ── start() loop ──────────────────────────────────────────────────────────────


class TestPepEnricherStart:
    async def test_start_runs_one_iteration_then_stops(self):
        enricher = PepEnricher()
        enricher._process_pending = AsyncMock()

        with patch(
            "modules.enrichers.pep_enricher.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, Exception("stop")],
        ):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        enricher._process_pending.assert_awaited()

    async def test_start_swallows_batch_exception(self):
        enricher = PepEnricher()
        enricher._process_pending = AsyncMock(side_effect=RuntimeError("batch boom"))

        calls = 0

        async def fake_sleep(_):
            nonlocal calls
            calls += 1
            if calls >= 1:
                raise Exception("stop")

        with patch("modules.enrichers.pep_enricher.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        assert calls >= 1


# ── _process_pending() ────────────────────────────────────────────────────────


class TestPepProcessPending:
    async def test_process_pending_calls_check_per_person(self):
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = PepEnricher()
        enricher.check_person = AsyncMock()

        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.pep_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert enricher.check_person.await_count == 2

    async def test_process_pending_empty_batch(self):
        enricher = PepEnricher()
        enricher.check_person = AsyncMock()

        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.pep_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        enricher.check_person.assert_not_awaited()

    async def test_process_pending_swallows_per_person_error(self):
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = PepEnricher()

        checked: list[uuid.UUID] = []

        async def _check(pid, session):
            checked.append(pid)
            if pid == pid1:
                raise RuntimeError("pep check failed")

        enricher.check_person = _check

        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.pep_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert pid1 in checked
        assert pid2 in checked


# ── check_person() ────────────────────────────────────────────────────────────


class TestCheckPerson:
    async def test_check_person_not_found(self):
        enricher = PepEnricher()
        session = _make_session()
        session.get = AsyncMock(return_value=None)
        # Should return without touching session.add
        await enricher.check_person(uuid.uuid4(), session)
        session.add.assert_not_called()

    async def test_check_person_no_matches(self):
        """No PEP hits → meta.pep_status=False."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        no_result = MagicMock()
        no_result.found = False

        crawler = MagicMock(scrape=AsyncMock(return_value=no_result))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler",
                return_value=crawler,
            ),
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["pep_status"] is False
        assert person.meta["pep_match_count"] == 0
        assert person.meta["pep_level"] is None

    async def test_check_person_with_matches(self):
        """PEP matches → is_pep=True, level set, meta updated."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        enricher._persist_pep_record = AsyncMock(return_value=MagicMock())
        enricher._create_pep_timeline_events = AsyncMock()

        match = _pep_match(level="tier1")
        found_result = MagicMock()
        found_result.found = True
        found_result.data = [match]

        crawler = MagicMock(scrape=AsyncMock(return_value=found_result))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler",
                return_value=crawler,
            ),
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["pep_status"] is True
        assert person.meta["pep_level"] == "tier1"
        enricher._create_pep_timeline_events.assert_awaited_once()

    async def test_check_person_highest_level_resolved(self):
        """Multiple matches at different tiers — highest rank wins."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        enricher._persist_pep_record = AsyncMock(return_value=MagicMock())
        enricher._create_pep_timeline_events = AsyncMock()

        matches = [_pep_match(level="tier3"), _pep_match(level="tier1"), _pep_match(level="family")]
        found_result = MagicMock()
        found_result.found = True
        found_result.data = matches

        crawler = MagicMock(scrape=AsyncMock(return_value=found_result))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler",
                return_value=crawler,
            ),
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["pep_level"] == "tier1"

    async def test_check_person_crawler_exception_swallowed(self):
        """A failing crawler does not abort the whole check."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        boom = MagicMock(scrape=AsyncMock(side_effect=RuntimeError("crawl error")))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=boom),
            patch("modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler", return_value=boom),
        ):
            await enricher.check_person(person.id, session)

        assert "pep_status" in person.meta

    async def test_check_person_uses_id_as_identifier_when_no_name(self):
        """Falls back to str(person_id) when full_name is None."""
        enricher = PepEnricher()
        person = _make_person()
        person.full_name = None
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        no_result = MagicMock()
        no_result.found = False
        crawler = MagicMock(scrape=AsyncMock(return_value=no_result))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler", return_value=crawler
            ),
        ):
            await enricher.check_person(person.id, session)

        assert "pep_checked_at" in person.meta

    async def test_check_person_crawler_returns_single_dict(self):
        """Crawler returning a dict (not a list) is wrapped in a list."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        enricher._persist_pep_record = AsyncMock(return_value=MagicMock())
        enricher._create_pep_timeline_events = AsyncMock()

        single_match = _pep_match(is_pep=True)
        found = MagicMock()
        found.found = True
        found.data = single_match  # dict, not list

        crawler = MagicMock(scrape=AsyncMock(return_value=found))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler", return_value=crawler
            ),
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["pep_status"] is True

    async def test_check_person_is_pep_false_in_match_skipped(self):
        """Match dict with is_pep=False should be excluded from pep_matches."""
        enricher = PepEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        non_pep = _pep_match(is_pep=False)
        found = MagicMock()
        found.found = True
        found.data = [non_pep]

        crawler = MagicMock(scrape=AsyncMock(return_value=found))

        with (
            patch("modules.crawlers.pep.open_pep_search.OpenPepSearchCrawler", return_value=crawler),
            patch(
                "modules.crawlers.pep.world_check_mirror.WorldCheckMirrorCrawler", return_value=crawler
            ),
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["pep_status"] is False


# ── _persist_pep_record() ─────────────────────────────────────────────────────


class TestPersistPepRecord:
    async def test_inserts_new_record(self):
        enricher = PepEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        match = _pep_match()
        await enricher._persist_pep_record(session, uuid.uuid4(), match)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_updates_confidence_when_higher(self):
        enricher = PepEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.5
        existing.end_date = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        match = _pep_match(confidence=0.95)
        await enricher._persist_pep_record(session, uuid.uuid4(), match)
        assert existing.confidence == 0.95
        session.add.assert_not_called()

    async def test_does_not_lower_confidence(self):
        """New confidence lower than existing → not overwritten."""
        enricher = PepEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.9
        existing.end_date = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        match = _pep_match(confidence=0.3)
        await enricher._persist_pep_record(session, uuid.uuid4(), match)
        assert existing.confidence == 0.9

    async def test_sets_end_date_on_existing(self):
        """end_date newly available → sets end_date, is_former=True, is_current=False."""
        enricher = PepEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.7
        existing.end_date = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        match = _pep_match(end_date="2023-12-31", confidence=0.7)
        await enricher._persist_pep_record(session, uuid.uuid4(), match)
        assert existing.end_date == "2023-12-31"
        assert existing.is_current is False
        assert existing.is_former is True

    async def test_does_not_overwrite_existing_end_date(self):
        """Existing end_date already set → not overwritten."""
        enricher = PepEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.7
        existing.end_date = "2021-06-01"
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        match = _pep_match(end_date="2023-12-31", confidence=0.7)
        await enricher._persist_pep_record(session, uuid.uuid4(), match)
        # end_date not overwritten because the branch condition checks `not existing.end_date`
        assert existing.end_date == "2021-06-01"


# ── _create_pep_timeline_events() ────────────────────────────────────────────


class TestCreatePepTimelineEvents:
    async def test_creates_event_for_each_match_with_start_date(self):
        enricher = PepEnricher()
        session = _make_session()
        mock_builder = MagicMock()
        mock_builder._upsert_event = AsyncMock(return_value=True)

        matches = [
            _pep_match(start_date="2015-01-01", position="President"),
            _pep_match(start_date="2019-03-10", position="Governor"),
        ]

        with patch(
            "modules.enrichers.pep_enricher.TimelineBuilder",
            return_value=mock_builder,
        ):
            await enricher._create_pep_timeline_events(session, uuid.uuid4(), matches)

        assert mock_builder._upsert_event.await_count == 2

    async def test_skips_matches_without_start_date(self):
        enricher = PepEnricher()
        session = _make_session()
        mock_builder = MagicMock()
        mock_builder._upsert_event = AsyncMock(return_value=True)

        matches = [
            _pep_match(start_date=None),
            _pep_match(start_date="2020-01-01"),
        ]

        with patch(
            "modules.enrichers.pep_enricher.TimelineBuilder",
            return_value=mock_builder,
        ):
            await enricher._create_pep_timeline_events(session, uuid.uuid4(), matches)

        assert mock_builder._upsert_event.await_count == 1

    async def test_swallows_builder_exception(self):
        enricher = PepEnricher()
        session = _make_session()

        with patch(
            "modules.enrichers.pep_enricher.TimelineBuilder",
            side_effect=ImportError("no timeline"),
        ):
            # Should not raise
            await enricher._create_pep_timeline_events(session, uuid.uuid4(), [_pep_match()])

    async def test_title_includes_org_when_present(self):
        """Title includes '— OrgName' when organization is in the match."""
        enricher = PepEnricher()
        session = _make_session()
        mock_builder = MagicMock()

        call_kwargs: list[dict] = []

        async def capture_upsert(**kwargs):
            call_kwargs.append(kwargs)
            return True

        mock_builder._upsert_event = capture_upsert

        matches = [
            _pep_match(position="Minister", org="Ministry of Finance", start_date="2018-05-01")
        ]

        with patch(
            "modules.enrichers.pep_enricher.TimelineBuilder",
            return_value=mock_builder,
        ):
            await enricher._create_pep_timeline_events(session, uuid.uuid4(), matches)

        assert len(call_kwargs) == 1
        assert "Ministry of Finance" in call_kwargs[0]["title"]

    async def test_title_omits_org_when_empty_string(self):
        """Empty org → title does not append '—'."""
        enricher = PepEnricher()
        session = _make_session()
        mock_builder = MagicMock()

        call_kwargs: list[dict] = []

        async def capture_upsert(**kwargs):
            call_kwargs.append(kwargs)
            return True

        mock_builder._upsert_event = capture_upsert

        matches = [_pep_match(position="Treasurer", org="", start_date="2018-05-01")]

        with patch(
            "modules.enrichers.pep_enricher.TimelineBuilder",
            return_value=mock_builder,
        ):
            await enricher._create_pep_timeline_events(session, uuid.uuid4(), matches)

        assert "—" not in call_kwargs[0]["title"]


# ── _LEVEL_RANK constant ─────────────────────────────────────────────────────


class TestLevelRank:
    def test_tier1_highest(self):
        assert _LEVEL_RANK["tier1"] > _LEVEL_RANK["tier2"]
        assert _LEVEL_RANK["tier2"] > _LEVEL_RANK["tier3"]
        assert _LEVEL_RANK["tier3"] > _LEVEL_RANK["family"]
        assert _LEVEL_RANK["family"] > _LEVEL_RANK["associate"]
