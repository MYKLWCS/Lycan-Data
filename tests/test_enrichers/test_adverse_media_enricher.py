"""
test_adverse_media_enricher.py — Unit tests for modules/enrichers/adverse_media_enricher.py.

Covers:
  - start(): one loop iteration then stops via sleep side_effect
  - start(): batch exception swallowed
  - _process_pending(): queries DB, iterates person_ids, calls check_person
  - _process_pending(): per-person exception swallowed
  - check_person(): person not found → early return
  - check_person(): crawler returns no results → score=0.0, no alerts
  - check_person(): crawler returns results → persisted, score computed, meta updated
  - check_person(): crawler exception swallowed
  - check_person(): critical/high records trigger _create_alerts
  - check_person(): only medium/low records → no alerts
  - check_person(): duplicate records (None returned from persist) excluded from persisted list
  - _persist_media_record(): deduplicates by url_hash → returns None
  - _persist_media_record(): inserts new record → returns AdverseMedia
  - _persist_media_record(): no url → url_hash is None, skips dedup lookup
  - _persist_media_record(): unknown severity falls back to "medium"
  - _compute_adverse_score(): empty list → 0.0
  - _compute_adverse_score(): single critical → 1.0 * 0.6 + 1.0 * 0.4 = 1.0
  - _compute_adverse_score(): mixed severities
  - _create_alerts(): creates Alert per record
  - _create_alerts(): publication_date present → payload isoformat
  - _create_alerts(): publication_date absent → payload None
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timezone, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.adverse_media_enricher import (
    _SEVERITY_WEIGHTS,
    AdverseMediaEnricher,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_person(name: str = "Bob Jones", meta: dict | None = None) -> MagicMock:
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


def _scalars_result(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one_or_none(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _media_record(severity: str = "medium", is_retracted: bool = False) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.severity = severity
    m.is_retracted = is_retracted
    m.headline = f"Test headline ({severity})"
    m.summary = "Summary text"
    m.url = "https://example.com/news/1"
    m.category = "financial_crime"
    m.source_name = "Reuters"
    m.publication_date = date(2024, 1, 15)
    return m


# ── start() loop ──────────────────────────────────────────────────────────────


class TestAdverseMediaEnricherStart:
    async def test_start_runs_one_iteration_then_stops(self):
        enricher = AdverseMediaEnricher()
        enricher._process_pending = AsyncMock()

        with patch(
            "modules.enrichers.adverse_media_enricher.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, Exception("stop")],
        ):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        enricher._process_pending.assert_awaited()

    async def test_start_swallows_batch_exception(self):
        enricher = AdverseMediaEnricher()
        enricher._process_pending = AsyncMock(side_effect=RuntimeError("oops"))

        calls = 0

        async def fake_sleep(_):
            nonlocal calls
            calls += 1
            if calls >= 1:
                raise Exception("stop")

        with patch(
            "modules.enrichers.adverse_media_enricher.asyncio.sleep", side_effect=fake_sleep
        ):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        assert calls >= 1


# ── _process_pending() ────────────────────────────────────────────────────────


class TestAdverseProcessPending:
    async def test_calls_check_per_person(self):
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = AdverseMediaEnricher()
        enricher.check_person = AsyncMock()

        session = _make_session()
        session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.adverse_media_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert enricher.check_person.await_count == 2

    async def test_empty_batch(self):
        enricher = AdverseMediaEnricher()
        enricher.check_person = AsyncMock()

        session = _make_session()
        session.execute = AsyncMock(return_value=_fetchall_result([]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.adverse_media_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        enricher.check_person.assert_not_awaited()

    async def test_swallows_per_person_error(self):
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = AdverseMediaEnricher()

        checked: list[uuid.UUID] = []

        async def _check(pid, session):
            checked.append(pid)
            if pid == pid1:
                raise RuntimeError("fail")

        enricher.check_person = _check

        session = _make_session()
        session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.adverse_media_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert pid1 in checked
        assert pid2 in checked


# ── check_person() ────────────────────────────────────────────────────────────


class TestCheckPerson:
    async def test_person_not_found(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()
        session.get = AsyncMock(return_value=None)
        await enricher.check_person(uuid.uuid4(), session)
        session.add.assert_not_called()

    async def test_no_crawler_results_sets_zero_score(self):
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        no_result = MagicMock()
        no_result.found = False
        crawler = MagicMock(scrape=AsyncMock(return_value=no_result))

        # all_media query returns empty list
        session.execute = AsyncMock(return_value=_scalars_result([]))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=crawler,
        ):
            await enricher.check_person(person.id, session)

        assert person.meta["adverse_media_score"] == 0.0
        assert person.meta["adverse_media_count"] == 0

    async def test_crawler_exception_swallowed(self):
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        boom = MagicMock(scrape=AsyncMock(side_effect=RuntimeError("crawl error")))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=boom,
        ):
            await enricher.check_person(person.id, session)

        assert "adverse_media_score" in person.meta

    async def test_critical_record_creates_alert(self):
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        critical_item = {"url": "https://news.com/1", "severity": "critical", "headline": "Fraud"}
        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = [critical_item]

        new_record = _media_record(severity="critical")
        enricher._persist_media_record = AsyncMock(return_value=new_record)
        enricher._create_alerts = AsyncMock()

        all_media = [new_record]
        session.execute = AsyncMock(return_value=_scalars_result(all_media))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=MagicMock(scrape=AsyncMock(return_value=crawler_result)),
        ):
            await enricher.check_person(person.id, session)

        enricher._create_alerts.assert_awaited_once()

    async def test_low_severity_does_not_create_alert(self):
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        low_item = {"url": "https://news.com/2", "severity": "low"}
        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = [low_item]

        new_record = _media_record(severity="low")
        enricher._persist_media_record = AsyncMock(return_value=new_record)
        enricher._create_alerts = AsyncMock()

        session.execute = AsyncMock(return_value=_scalars_result([new_record]))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=MagicMock(scrape=AsyncMock(return_value=crawler_result)),
        ):
            await enricher.check_person(person.id, session)

        enricher._create_alerts.assert_not_awaited()

    async def test_duplicate_record_excluded_from_persisted(self):
        """_persist_media_record returning None → not counted in persisted list."""
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        items = [{"url": "https://dup.com/1", "severity": "high"}]
        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = items

        # Returns None → duplicate
        enricher._persist_media_record = AsyncMock(return_value=None)
        enricher._create_alerts = AsyncMock()
        session.execute = AsyncMock(return_value=_scalars_result([]))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=MagicMock(scrape=AsyncMock(return_value=crawler_result)),
        ):
            await enricher.check_person(person.id, session)

        enricher._create_alerts.assert_not_awaited()

    async def test_crawler_returns_single_dict_not_list(self):
        """Crawler returning a single dict is wrapped in a list."""
        enricher = AdverseMediaEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        item = {"url": "https://news.com/solo", "severity": "medium"}
        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = item  # dict, not list

        new_record = _media_record(severity="medium")
        enricher._persist_media_record = AsyncMock(return_value=new_record)
        session.execute = AsyncMock(return_value=_scalars_result([new_record]))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=MagicMock(scrape=AsyncMock(return_value=crawler_result)),
        ):
            await enricher.check_person(person.id, session)

        enricher._persist_media_record.assert_awaited_once()

    async def test_uses_person_id_when_no_name(self):
        enricher = AdverseMediaEnricher()
        person = _make_person()
        person.full_name = None
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalars_result([]))

        no_result = MagicMock(found=False)
        crawler = MagicMock(scrape=AsyncMock(return_value=no_result))

        with patch(
            "modules.crawlers.adverse_media_search.AdverseMediaSearchCrawler",
            return_value=crawler,
        ):
            await enricher.check_person(person.id, session)

        assert "adverse_media_checked_at" in person.meta


# ── _persist_media_record() ───────────────────────────────────────────────────


class TestPersistMediaRecord:
    async def test_deduplicates_by_url_hash(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()
        url = "https://example.com/article/1"
        hashlib.sha256(url.encode()).hexdigest()

        existing_media = MagicMock()
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing_media
        session.execute = AsyncMock(return_value=r)

        item = {"url": url, "severity": "high"}
        result = await enricher._persist_media_record(session, uuid.uuid4(), item)
        assert result is None

    async def test_inserts_new_record(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        item = {
            "url": "https://fresh.com/story/2",
            "headline": "New fraud case",
            "severity": "high",
            "source_name": "FT",
        }
        result = await enricher._persist_media_record(session, uuid.uuid4(), item)
        assert result is not None
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_no_url_skips_dedup_lookup(self):
        """Empty url → url_hash=None → no execute call for dedup."""
        enricher = AdverseMediaEnricher()
        session = _make_session()

        item = {"severity": "low", "headline": "No URL item"}
        result = await enricher._persist_media_record(session, uuid.uuid4(), item)
        assert result is not None
        session.execute.assert_not_awaited()

    async def test_unknown_severity_falls_back_to_medium(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        item = {"url": "", "severity": "extreme"}
        result = await enricher._persist_media_record(session, uuid.uuid4(), item)
        assert result is not None
        # The record was created — severity was coerced to medium
        call_args = session.add.call_args[0][0]
        assert call_args.severity == "medium"

    async def test_missing_severity_defaults_to_medium(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        item = {"url": "", "headline": "No severity"}
        await enricher._persist_media_record(session, uuid.uuid4(), item)
        call_args = session.add.call_args[0][0]
        assert call_args.severity == "medium"


# ── _compute_adverse_score() ─────────────────────────────────────────────────


class TestComputeAdverseScore:
    def test_empty_list_returns_zero(self):
        assert AdverseMediaEnricher._compute_adverse_score([]) == 0.0

    def test_single_critical(self):
        # max = 1.0, avg = 1.0 → 1.0 * 0.6 + 1.0 * 0.4 = 1.0
        result = AdverseMediaEnricher._compute_adverse_score([{"severity": "critical"}])
        assert result == pytest.approx(1.0)

    def test_single_low(self):
        # 0.1 * 0.6 + 0.1 * 0.4 = 0.1
        result = AdverseMediaEnricher._compute_adverse_score([{"severity": "low"}])
        assert result == pytest.approx(0.1)

    def test_mixed_severities(self):
        # scores: critical=1.0, medium=0.4
        # max=1.0, avg=(1.0+0.4)/2=0.7
        # 1.0*0.6 + 0.7*0.4 = 0.6 + 0.28 = 0.88
        media = [{"severity": "critical"}, {"severity": "medium"}]
        result = AdverseMediaEnricher._compute_adverse_score(media)
        assert result == pytest.approx(0.88)

    def test_unknown_severity_treated_as_medium(self):
        # "unknown" → get fallback 0.4 (medium default in _SEVERITY_WEIGHTS.get)
        result = AdverseMediaEnricher._compute_adverse_score([{"severity": "extreme"}])
        assert result == pytest.approx(0.4)

    def test_multiple_same_severity(self):
        media = [{"severity": "high"}, {"severity": "high"}, {"severity": "high"}]
        # max=0.7, avg=0.7 → 0.7*0.6 + 0.7*0.4 = 0.7
        result = AdverseMediaEnricher._compute_adverse_score(media)
        assert result == pytest.approx(0.7)


# ── _create_alerts() ─────────────────────────────────────────────────────────


class TestCreateAlerts:
    async def test_creates_alert_per_record(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        records = [_media_record("critical"), _media_record("high")]
        await enricher._create_alerts(session, uuid.uuid4(), records)

        assert session.add.call_count == 2

    async def test_alert_payload_contains_expected_keys(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        record = _media_record("critical")
        await enricher._create_alerts(session, uuid.uuid4(), [record])

        call_args = session.add.call_args[0][0]
        assert call_args.alert_type == "adverse_media"
        assert call_args.severity == "critical"
        assert "adverse_media_id" in call_args.payload
        assert call_args.payload["severity"] == "critical"

    async def test_alert_publication_date_isoformat(self):
        """publication_date present → payload contains isoformat string."""
        enricher = AdverseMediaEnricher()
        session = _make_session()

        record = _media_record("high")
        record.publication_date = date(2024, 6, 15)
        await enricher._create_alerts(session, uuid.uuid4(), [record])

        call_args = session.add.call_args[0][0]
        assert call_args.payload["publication_date"] == "2024-06-15"

    async def test_alert_publication_date_none(self):
        """No publication_date → payload None."""
        enricher = AdverseMediaEnricher()
        session = _make_session()

        record = _media_record("high")
        record.publication_date = None
        await enricher._create_alerts(session, uuid.uuid4(), [record])

        call_args = session.add.call_args[0][0]
        assert call_args.payload["publication_date"] is None

    async def test_alert_title_includes_headline(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        record = _media_record("critical")
        record.headline = "CEO charged with fraud"
        await enricher._create_alerts(session, uuid.uuid4(), [record])

        call_args = session.add.call_args[0][0]
        assert "CEO charged with fraud" in call_args.title

    async def test_alert_no_headline_uses_fallback(self):
        enricher = AdverseMediaEnricher()
        session = _make_session()

        record = _media_record("high")
        record.headline = None
        await enricher._create_alerts(session, uuid.uuid4(), [record])

        call_args = session.add.call_args[0][0]
        assert "No headline" in call_args.title
