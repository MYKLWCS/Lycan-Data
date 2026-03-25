"""
adverse_media_enricher.py — Async daemon that checks persons for adverse
(negative) media coverage and persists AdverseMedia records.

Polls every hour. Targets persons with adverse_media_score=0 in Person.meta
or whose last adverse-media check is older than 24 hours. Deduplicates
results by url_hash. Computes a weighted severity score and updates
Person.meta. Raises high-severity alerts when critical or high-severity
coverage is found.

Severity scoring:
    critical → 1.0
    high     → 0.7
    medium   → 0.4
    low      → 0.1

    score = max(scores) * 0.6 + count_weighted_avg * 0.4
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal
from shared.models.alert import Alert
from shared.models.compliance_ext import AdverseMedia
from shared.models.person import Person

logger = logging.getLogger(__name__)

_SLEEP_INTERVAL = 3600  # 1 hour
_BATCH_SIZE = 40
_STALE_THRESHOLD_HOURS = 24

_SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 1.0,
    "high": 0.7,
    "medium": 0.4,
    "low": 0.1,
}

_ALERT_SEVERITIES = {"critical", "high"}


class AdverseMediaEnricher:
    """Continuously checks persons for adverse media coverage."""

    async def start(self) -> None:
        """Entry point — runs forever with 1-hour sleep between batches."""
        logger.info("AdverseMediaEnricher started (interval=%ds)", _SLEEP_INTERVAL)
        while True:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("AdverseMediaEnricher batch error: %s", exc)
            await asyncio.sleep(_SLEEP_INTERVAL)

    # ── Batch selection ───────────────────────────────────────────────────────

    async def _process_pending(self) -> None:
        stale_cutoff = datetime.now(UTC) - timedelta(hours=_STALE_THRESHOLD_HOURS)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Person.id)
                .where(
                    (~Person.meta.has_key("adverse_media_score"))
                    | (Person.meta["adverse_media_score"].astext.cast(float) == 0.0)
                    | (~Person.meta.has_key("adverse_media_checked_at"))
                    | (
                        Person.meta["adverse_media_checked_at"].astext.cast(datetime)
                        < stale_cutoff
                    )
                )
                .limit(_BATCH_SIZE)
            )
            person_ids = [row[0] for row in result.fetchall()]

        logger.info("AdverseMediaEnricher: %d persons to check", len(person_ids))
        for pid in person_ids:
            try:
                async with AsyncSessionLocal() as session:
                    await self.check_person(pid, session)
                    await session.commit()
            except Exception as exc:
                logger.exception(
                    "AdverseMediaEnricher: failed person_id=%s — %s", pid, exc
                )

    # ── Per-person check ──────────────────────────────────────────────────────

    async def check_person(self, person_id: uuid.UUID, session: AsyncSession) -> None:
        """Run adverse-media crawler for one person, persist results, update person."""
        from modules.crawlers.adverse_media_search import AdverseMediaSearchCrawler

        person = await session.get(Person, person_id)
        if not person:
            logger.warning("AdverseMediaEnricher: person_id=%s not found", person_id)
            return

        identifier = person.full_name or str(person_id)

        raw_results: list[dict] = []
        try:
            crawler = AdverseMediaSearchCrawler()
            r = await crawler.scrape(identifier)
            if r and r.found:
                raw_results = r.data if isinstance(r.data, list) else [r.data]
        except Exception as exc:
            logger.debug(
                "AdverseMediaEnricher: crawler failed for %s — %s", identifier, exc
            )

        # Persist records and collect successfully persisted ones
        persisted: list[AdverseMedia] = []
        for item in raw_results:
            record = await self._persist_media_record(session, person_id, item)
            if record is not None:
                persisted.append(record)

        # Compute score from all existing records for this person (not just new)
        all_result = await session.execute(
            select(AdverseMedia).where(
                AdverseMedia.person_id == person_id,
                AdverseMedia.is_retracted.is_(False),
            )
        )
        all_media = list(all_result.scalars().all())

        score = self._compute_adverse_score(
            [{"severity": m.severity} for m in all_media]
        )

        # Update Person.meta
        meta = dict(person.meta or {})
        meta["adverse_media_score"] = round(score, 4)
        meta["adverse_media_count"] = len(all_media)
        meta["adverse_media_checked_at"] = datetime.now(UTC).isoformat()
        person.meta = meta

        logger.info(
            "AdverseMediaEnricher: person_id=%s — new=%d total=%d score=%.4f",
            person_id, len(persisted), len(all_media), score,
        )

        # Raise alerts for critical/high new records
        critical_or_high = [
            m for m in persisted if m.severity in _ALERT_SEVERITIES
        ]
        if critical_or_high:
            await self._create_alerts(session, person_id, critical_or_high)

    # ── Record persistence ────────────────────────────────────────────────────

    async def _persist_media_record(
        self, session: AsyncSession, person_id: uuid.UUID, item: dict
    ) -> AdverseMedia | None:
        """Persist one AdverseMedia record, deduplicated by url_hash.

        Returns the record if newly inserted, None if it was a duplicate.
        """
        url = item.get("url", "")
        url_hash = hashlib.sha256(url.encode()).hexdigest() if url else None

        if url_hash:
            result = await session.execute(
                select(AdverseMedia).where(
                    AdverseMedia.url_hash == url_hash,
                ).limit(1)
            )
            if result.scalar_one_or_none() is not None:
                return None  # already stored

        severity = item.get("severity", "medium")
        if severity not in _SEVERITY_WEIGHTS:
            severity = "medium"

        record = AdverseMedia(
            person_id=person_id,
            headline=item.get("headline"),
            summary=item.get("summary"),
            url=url or None,
            url_hash=url_hash,
            publication_date=item.get("publication_date"),
            source_name=item.get("source_name"),
            source_country=item.get("source_country"),
            language=item.get("language", "en"),
            category=item.get("category"),
            severity=severity,
            sentiment_score=item.get("sentiment_score"),
            is_verified=bool(item.get("is_verified", False)),
            is_retracted=bool(item.get("is_retracted", False)),
            entities_mentioned=item.get("entities_mentioned", []),
            last_scraped_at=datetime.now(UTC),
            meta=item.get("meta", {}),
        )
        session.add(record)
        await session.flush()
        return record

    # ── Score computation ─────────────────────────────────────────────────────

    @staticmethod
    def _compute_adverse_score(media_list: list[dict]) -> float:
        """Weighted severity scoring.

        score = max(scores) * 0.6 + count_weighted_avg * 0.4

        An empty list returns 0.0.
        """
        if not media_list:
            return 0.0

        scores = [
            _SEVERITY_WEIGHTS.get(m.get("severity", "medium"), 0.4)
            for m in media_list
        ]
        max_score = max(scores)
        count_weighted_avg = sum(scores) / len(scores)
        return round(max_score * 0.6 + count_weighted_avg * 0.4, 4)

    # ── Alert creation ────────────────────────────────────────────────────────

    async def _create_alerts(
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        media_records: list[AdverseMedia],
    ) -> None:
        """Create Alert rows for critical or high-severity adverse media."""
        for record in media_records:
            alert = Alert(
                person_id=person_id,
                alert_type="adverse_media",
                severity=record.severity,
                title=f"Adverse media ({record.severity}): {record.headline or 'No headline'}",
                body=record.summary,
                payload={
                    "adverse_media_id": str(record.id),
                    "url": record.url,
                    "category": record.category,
                    "severity": record.severity,
                    "source_name": record.source_name,
                    "publication_date": (
                        record.publication_date.isoformat()
                        if record.publication_date
                        else None
                    ),
                },
                is_read=False,
                is_sent=False,
            )
            session.add(alert)

        logger.info(
            "AdverseMediaEnricher: created %d alert(s) for person_id=%s",
            len(media_records), person_id,
        )
