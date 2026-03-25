"""
Enrichment Pipeline Orchestrator.

Runs all enrichers for a person in sequence and publishes a completion event.
Each enricher is independent — failures are logged and don't block subsequent enrichers.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import event_bus

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentStepResult:
    enricher: str
    status: str  # "ok" | "skipped" | "error"
    detail: str = ""
    duration_ms: float = 0.0


@dataclass
class EnrichmentReport:
    person_id: str
    started_at: str
    finished_at: str
    total_duration_ms: float
    steps: list[EnrichmentStepResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "ok")

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "error")


class EnrichmentOrchestrator:
    """
    Runs all available enrichers for a single person.

    Enrichers run sequentially (shared DB session, no asyncio.gather).
    Errors in one enricher don't stop others.
    After all steps, publishes enrichment_complete event to event_bus.
    """

    async def enrich_person(self, person_id: str, session: AsyncSession) -> EnrichmentReport:
        """
        Run the full enrichment pipeline for a person.
        Returns a report of what ran, what succeeded, and what failed.
        """
        started_at = datetime.now(UTC)
        steps: list[EnrichmentStepResult] = []

        # ── Step 1: Financial / AML ───────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="financial_aml",
                coro=self._run_financial_aml(person_id, session),
                person_id=person_id,
            )
        )

        # ── Step 2: Marketing Tags ────────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="marketing_tags",
                coro=self._run_marketing_tags(person_id, session),
                person_id=person_id,
            )
        )

        # ── Step 3: Deduplication scoring ─────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="deduplication",
                coro=self._run_deduplication(person_id, session),
                person_id=person_id,
            )
        )

        # ── Step 4: Burner assessment ─────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="burner_assessment",
                coro=self._run_burner(person_id, session),
                person_id=person_id,
            )
        )

        # ── Step 5: Relationship score ────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="relationship_score",
                coro=self._run_relationship_score(person_id, session),
                person_id=person_id,
            )
        )

        # ── Step 6: Update coverage score ─────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="coverage_update",
                coro=self._update_coverage(person_id, session),
                person_id=person_id,
            )
        )

        finished_at = datetime.now(UTC)
        total_ms = (finished_at - started_at).total_seconds() * 1000

        report = EnrichmentReport(
            person_id=person_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            total_duration_ms=round(total_ms, 2),
            steps=steps,
        )

        # Publish completion event
        await self._publish_completion(person_id, report)

        return report

    async def _run_step(self, enricher: str, coro, person_id: str = "") -> EnrichmentStepResult:
        """Run a single enricher coroutine, catching all exceptions."""
        t0 = datetime.now(UTC)
        try:
            await coro
            duration = (datetime.now(UTC) - t0).total_seconds() * 1000
            return EnrichmentStepResult(
                enricher=enricher,
                status="ok",
                duration_ms=round(duration, 2),
            )
        except Exception as exc:
            duration = (datetime.now(UTC) - t0).total_seconds() * 1000
            logger.exception("Enricher %r failed for person_id=%s", enricher, person_id)
            return EnrichmentStepResult(
                enricher=enricher,
                status="error",
                detail=str(exc)[:200],
                duration_ms=round(duration, 2),
            )

    async def _run_financial_aml(self, person_id: str, session: AsyncSession) -> None:
        # The class is FinancialIntelligenceEngine, not FinancialAMLEngine.
        from modules.enrichers.financial_aml import FinancialIntelligenceEngine

        engine = FinancialIntelligenceEngine()
        await engine.score_person(person_id, session)

    async def _run_marketing_tags(self, person_id: str, session: AsyncSession) -> None:
        from modules.enrichers.marketing_tags import MarketingTagsEngine

        engine = MarketingTagsEngine()
        await engine.tag_person(person_id, session)

    async def _run_deduplication(self, person_id: str, session: AsyncSession) -> None:
        from modules.enrichers.deduplication import score_person_dedup

        await score_person_dedup(person_id, session)

    async def _run_burner(self, person_id: str, session: AsyncSession) -> None:
        # persist_burner_assessment signature: (session, identifier_id, score)
        # It takes one identifier at a time with a BurnerScore.
        # We load phone identifiers and run compute_burner_score on each, then persist.
        from sqlalchemy import select

        from modules.enrichers.burner_detector import (
            compute_burner_score,
            persist_burner_assessment,
        )
        from shared.models.identifier import Identifier

        result = await session.execute(
            select(Identifier).where(
                Identifier.person_id == person_id,
                Identifier.type == "phone",
            )
        )
        identifiers = result.scalars().all()

        if not identifiers:
            return

        for identifier in identifiers:
            score = compute_burner_score(phone=identifier.value)
            await persist_burner_assessment(
                session=session,
                identifier_id=identifier.id,
                score=score,
            )

    async def _run_relationship_score(self, person_id: str, session: AsyncSession) -> None:
        """Compute relationship_score from network breadth across all linked data."""
        import uuid

        from sqlalchemy import func, select

        from shared.models.address import Address
        from shared.models.identifier import Identifier
        from shared.models.person import Person
        from shared.models.social_profile import SocialProfile

        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id
        person = await session.get(Person, pid)
        if not person:
            return

        # Count distinct data points as a proxy for network breadth
        social_count = (
            await session.execute(
                select(func.count())
                .select_from(SocialProfile)
                .where(SocialProfile.person_id == pid)
            )
        ).scalar() or 0

        ident_count = (
            await session.execute(
                select(func.count()).select_from(Identifier).where(Identifier.person_id == pid)
            )
        ).scalar() or 0

        addr_count = (
            await session.execute(
                select(func.count()).select_from(Address).where(Address.person_id == pid)
            )
        ).scalar() or 0

        # Simple normalized score: more data points = wider network footprint
        # Caps at 1.0 with diminishing returns
        breadth = social_count * 0.10 + ident_count * 0.05 + addr_count * 0.08
        score = round(min(1.0, breadth), 4)

        if score > person.relationship_score:
            person.relationship_score = score
            await session.flush()
            await session.commit()

    async def _update_coverage(self, person_id: str, session: AsyncSession) -> None:
        """
        Compute and store Person.meta['coverage'] based on completed CrawlJob rows.
        coverage = {
            "attempted": N,      # total crawl jobs for this person
            "found": M,          # jobs where result contained data (result_count > 0)
            "total_enabled": K,  # count of enabled DataSources
            "pct": float         # round(M/K*100, 1) clamped to 100.0
        }
        """
        import uuid

        from sqlalchemy import func, select

        from shared.models.crawl import CrawlJob, DataSource
        from shared.models.person import Person

        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id
        person = await session.get(Person, pid)
        if not person:
            return

        # Count attempted and found jobs
        attempted_result = await session.execute(
            select(func.count())
            .select_from(CrawlJob)
            .where(
                CrawlJob.person_id == pid,
                CrawlJob.status.in_(["done", "failed", "blocked", "rate_limited"]),
            )
        )
        attempted: int = attempted_result.scalar() or 0

        found_result = await session.execute(
            select(func.count())
            .select_from(CrawlJob)
            .where(
                CrawlJob.person_id == pid,
                CrawlJob.status == "done",
                CrawlJob.result_count > 0,
            )
        )
        found: int = found_result.scalar() or 0

        # Total enabled data sources
        enabled_result = await session.execute(
            select(func.count())
            .select_from(DataSource)
            .where(DataSource.is_enabled == True)  # noqa: E712
        )
        total_enabled: int = enabled_result.scalar() or 1  # avoid div-by-zero

        pct = round(min(100.0, (found / total_enabled) * 100), 1)

        meta = dict(person.meta or {})
        meta["coverage"] = {
            "attempted": attempted,
            "found": found,
            "total_enabled": total_enabled,
            "pct": pct,
        }
        person.meta = meta

        try:
            await session.flush()
            await session.commit()
        except Exception as exc:
            logger.warning("Coverage update failed for person_id=%s: %s", person_id, exc)
            await session.rollback()

    async def _publish_completion(self, person_id: str, report: EnrichmentReport) -> None:
        if not event_bus.is_connected:
            return
        try:
            await event_bus.publish(
                "enrichment",
                {
                    "event": "enrichment_complete",
                    "person_id": person_id,
                    "ok_count": report.ok_count,
                    "error_count": report.error_count,
                    "total_duration_ms": report.total_duration_ms,
                },
            )
        except Exception:
            logger.exception("Failed to publish enrichment_complete for %s", person_id)
