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
        import uuid

        from shared.models.person import Person

        # Skip if person was merged into another
        try:
            person = await session.get(
                Person,
                uuid.UUID(person_id) if isinstance(person_id, str) else person_id,
            )
            if person and person.merged_into:
                logger.info(
                    "Skipping enrichment for merged person %s (canonical: %s)",
                    person_id,
                    person.merged_into,
                )
                return EnrichmentReport(
                    person_id=person_id,
                    started_at=datetime.now(UTC).isoformat(),
                    finished_at=datetime.now(UTC).isoformat(),
                    total_duration_ms=0,
                    steps=[],
                )
        except Exception:
            logger.debug("Merged-person precheck failed for %s", person_id, exc_info=True)

        from shared.schemas.progress import EventType

        _total_steps = 12

        async def _emit_enrichment_progress(step_num: int):
            try:
                if event_bus.is_connected:
                    await event_bus.publish(
                        "progress",
                        {
                            "event_type": EventType.ENRICHMENT_RUNNING.value,
                            "search_id": str(person_id),
                            "records_processed": step_num,
                            "total_records": _total_steps,
                        },
                    )
            except Exception:
                logger.debug(
                    "Progress publish failed during enrichment step %s for %s",
                    step_num,
                    person_id,
                    exc_info=True,
                )

        await _emit_enrichment_progress(0)

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
        await _emit_enrichment_progress(1)

        # ── Step 2: Marketing Tags ────────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="marketing_tags",
                coro=self._run_marketing_tags(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(2)

        # ── Step 3: Deduplication scoring ─────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="deduplication",
                coro=self._run_deduplication(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(3)

        # ── Step 4: Burner assessment ─────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="burner_assessment",
                coro=self._run_burner(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(4)

        # ── Step 5: Relationship score ────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="relationship_score",
                coro=self._run_relationship_score(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(5)

        # ── Step 6: Update coverage score ─────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="coverage_update",
                coro=self._update_coverage(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(6)

        # ── Step 7: Location inference ─────────────────────────────────────────
        steps.append(
            await self._run_step(
                enricher="location",
                coro=self._run_location(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(7)

        # ── Step 8: Cross-seed cascade enricher ───────────────────────────────
        steps.append(
            await self._run_step(
                enricher="cascade",
                coro=self._run_cascade(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(8)

        # ── Step 9: Entity resolution (4-pass dedup + verification) ───────
        steps.append(
            await self._run_step(
                enricher="entity_resolution",
                coro=self._run_entity_resolution(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(9)

        # ── Step 10: Cross-person entity resolution ─────────────────────
        steps.append(
            await self._run_step(
                enricher="cross_person_resolution",
                coro=self._run_cross_person_resolution(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(10)

        # ── Step 11: Genealogy / family tree ─────────────────────────────
        steps.append(
            await self._run_step(
                enricher="genealogy",
                coro=self._run_genealogy(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(11)

        # ── Step 12: Enrichment score (spec formula) ───────────────────────
        steps.append(
            await self._run_step(
                enricher="enrichment_score",
                coro=self._compute_enrichment_score(person_id, session),
                person_id=person_id,
            )
        )
        await _emit_enrichment_progress(12)

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

        # Signal SEARCH_COMPLETE so progress bar reaches 100%
        try:
            if event_bus.is_connected:
                await event_bus.publish(
                    "progress",
                    {
                        "event_type": EventType.SEARCH_COMPLETE.value,
                        "search_id": str(person_id),
                        "results_found": report.ok_count,
                    },
                )
        except Exception:
            logger.debug("SEARCH_COMPLETE publish failed for %s", person_id, exc_info=True)

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

        # ── Infer relationships from shared addresses/identifiers ──
        try:
            from shared.models.relationship import Relationship

            # Find other persons sharing the same address
            if addr_count > 0:
                shared_addr = await session.execute(
                    select(Address.person_id)
                    .where(
                        Address.street.in_(select(Address.street).where(Address.person_id == pid)),
                        Address.person_id != pid,
                        Address.person_id.isnot(None),
                    )
                    .distinct()
                    .limit(20)
                )
                for (other_pid,) in shared_addr.all():
                    # Check if relationship already exists
                    existing_rel = (
                        await session.execute(
                            select(Relationship.id)
                            .where(
                                (
                                    (Relationship.person_a_id == pid)
                                    & (Relationship.person_b_id == other_pid)
                                )
                                | (
                                    (Relationship.person_a_id == other_pid)
                                    & (Relationship.person_b_id == pid)
                                )
                            )
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if not existing_rel:
                        session.add(
                            Relationship(
                                id=uuid.uuid4(),
                                person_a_id=pid,
                                person_b_id=other_pid,
                                relationship_type="co-location",
                                confidence_score=0.6,
                                source="address_match",
                            )
                        )

            # Find other persons sharing identifiers (email, phone)
            shared_idents = await session.execute(
                select(Identifier.person_id)
                .where(
                    Identifier.normalized_value.in_(
                        select(Identifier.normalized_value).where(
                            Identifier.person_id == pid,
                            Identifier.type.in_(["email", "phone"]),
                        )
                    ),
                    Identifier.person_id != pid,
                    Identifier.person_id.isnot(None),
                )
                .distinct()
                .limit(20)
            )
            for (other_pid,) in shared_idents.all():
                existing_rel = (
                    await session.execute(
                        select(Relationship.id)
                        .where(
                            (
                                (Relationship.person_a_id == pid)
                                & (Relationship.person_b_id == other_pid)
                            )
                            | (
                                (Relationship.person_a_id == other_pid)
                                & (Relationship.person_b_id == pid)
                            )
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not existing_rel:
                    session.add(
                        Relationship(
                            id=uuid.uuid4(),
                            person_a_id=pid,
                            person_b_id=other_pid,
                            relationship_type="shared_identifier",
                            confidence_score=0.8,
                            source="identifier_match",
                        )
                    )

            await session.flush()
        except Exception as exc:
            logger.debug("Relationship inference failed: %s", exc)
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
            select(func.count()).select_from(DataSource).where(DataSource.is_enabled == True)  # noqa: E712
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

    async def _run_location(self, person_id: str, session: AsyncSession) -> None:
        from modules.enrichers.location_enricher import LocationEnricher

        enricher = LocationEnricher()
        await enricher.enrich(person_id, session)

    async def _run_cascade(self, person_id: str, session: AsyncSession) -> None:
        from modules.enrichers.cascade_enricher import CascadeEnricher

        enricher = CascadeEnricher()
        await enricher.enrich(person_id, session)

    async def _run_entity_resolution(self, person_id: str, session: AsyncSession) -> None:
        from modules.enrichers.entity_resolution import EntityResolutionPipeline

        pipeline = EntityResolutionPipeline()
        await pipeline.resolve(person_id, session)

    async def _run_cross_person_resolution(self, person_id: str, session: AsyncSession) -> None:
        try:
            from modules.enrichers.entity_resolution import EntityResolutionPipeline

            pipeline = EntityResolutionPipeline()
            await pipeline.resolve_cross_person(person_id, session)
        except Exception as exc:
            logger.warning("Cross-person resolution failed for %s: %s", person_id, exc)

    async def _run_genealogy(self, person_id: str, session: AsyncSession) -> None:
        """Build family tree if relationships exist and no fresh snapshot."""
        try:
            import uuid

            from sqlalchemy import func, select

            from shared.models.family_tree import FamilyTreeSnapshot
            from shared.models.relationship import Relationship

            pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id

            # Check if fresh snapshot exists
            existing = (
                await session.execute(
                    select(FamilyTreeSnapshot)
                    .where(
                        FamilyTreeSnapshot.root_person_id == pid,
                        FamilyTreeSnapshot.is_stale.is_(False),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

            if existing:
                return  # Fresh snapshot already exists

            # Check if person has any relationships
            rel_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Relationship)
                    .where((Relationship.person_a_id == pid) | (Relationship.person_b_id == pid))
                )
            ).scalar() or 0

            if rel_count == 0:
                return  # No relationships to build tree from

            # Build tree inline
            from modules.enrichers.genealogy_enricher import GenealogyEnricher

            enricher = GenealogyEnricher()
            await enricher.build_tree(pid, session)
            logger.info("Built family tree for %s (%d relationships)", person_id, rel_count)
        except Exception as exc:
            logger.debug("Genealogy enrichment failed for %s: %s", person_id, exc)

    async def _compute_enrichment_score(self, person_id: str, session: AsyncSession) -> None:
        """
        Compute enrichment_score per spec formula:
          enrichment_score = (
              identity_completeness * 0.25 +
              social_coverage * 0.30 +
              employment_depth * 0.12 +
              financial_depth * 0.10 +
              legal_records * 0.10 +
              property_records * 0.07 +
              relationship_count * 0.06
          )
        Each component is 0-100 based on how many sub-fields are filled.
        """
        import uuid

        from sqlalchemy import func, select

        from shared.models.address import Address
        from shared.models.compliance_ext import AdverseMedia
        from shared.models.criminal import CriminalRecord
        from shared.models.employment import EmploymentHistory
        from shared.models.person import Person
        from shared.models.professional import CorporateDirectorship
        from shared.models.property import Property
        from shared.models.relationship import Relationship
        from shared.models.social_profile import SocialProfile

        pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id
        person = await session.get(Person, pid)
        if not person:
            return

        # 1. Identity completeness (0-100): name, DOB, SSN-last4 proxy, photo
        # Name alone = 50 (weight 2), DOB = 25, national_id/ssn = 12.5, photo = 12.5
        identity_fields = sum(
            [
                2 if person.full_name else 0,
                1 if person.date_of_birth else 0,
                0.5
                if getattr(person, "national_id", None) or getattr(person, "ssn_last4", None)
                else 0,
                0.5 if person.profile_image_url else 0,
            ]
        )
        identity_completeness = min(100, identity_fields * 25)

        # 2. Financial depth (0-100): credit score, income estimate, property
        financial_fields = 0
        financial_max = 3
        if person.alt_credit_score:
            financial_fields += 1
        if person.estimated_annual_income_usd:
            financial_fields += 1
        prop_count = (
            await session.execute(
                select(func.count()).select_from(Property).where(Property.person_id == pid)
            )
        ).scalar() or 0
        if prop_count > 0:
            financial_fields += 1
        financial_depth = (financial_fields / financial_max) * 100

        # 3. Employment depth (0-100): employer, title, history
        emp_rows = (
            await session.execute(
                select(func.count())
                .select_from(EmploymentHistory)
                .where(EmploymentHistory.person_id == pid)
            )
        ).scalar() or 0
        emp_fields = 0
        emp_max = 3
        if emp_rows > 0:
            emp_fields += 1  # has employer
            emp_fields += 1  # has title (assumed if record exists)
        if emp_rows > 1:
            emp_fields += 1  # has history
        employment_depth = (emp_fields / emp_max) * 100

        # 4. Social coverage (0-100): platforms found, follower counts
        social_count = (
            await session.execute(
                select(func.count())
                .select_from(SocialProfile)
                .where(SocialProfile.person_id == pid)
            )
        ).scalar() or 0
        # Score based on coverage with diminishing returns curve
        if social_count == 0:
            social_coverage = 0
        elif social_count == 1:
            social_coverage = 40
        elif social_count == 2:
            social_coverage = 65
        elif social_count == 3:
            social_coverage = 80
        else:
            social_coverage = 100

        # 5. Legal records (0-100): court, criminal, civil, AML
        legal_fields = 0
        legal_max = 4
        criminal_count = (
            await session.execute(
                select(func.count())
                .select_from(CriminalRecord)
                .where(CriminalRecord.person_id == pid)
            )
        ).scalar() or 0
        if criminal_count > 0:
            legal_fields += 2  # court + criminal
        if person.aml_risk_score is not None and person.aml_risk_score > 0:
            legal_fields += 1  # AML screening done
        if person.is_sanctioned:
            legal_fields += 1
        legal_records = (min(legal_fields, legal_max) / legal_max) * 100

        # 6. Property records (0-100): ownership, address history
        addr_count = (
            await session.execute(
                select(func.count()).select_from(Address).where(Address.person_id == pid)
            )
        ).scalar() or 0
        property_score = 0.0
        if prop_count > 0:
            property_score += 50
        if addr_count > 0:
            property_score += min(50.0, addr_count * 10)
        property_records = min(100.0, property_score)

        # 7. Relationship count (0-100): family, associates, professional
        rel_count = (
            await session.execute(
                select(func.count())
                .select_from(Relationship)
                .where((Relationship.person_a_id == pid) | (Relationship.person_b_id == pid))
            )
        ).scalar() or 0
        relationship_count = min(100.0, rel_count * 20)

        # 8. News/Media coverage (0-100)
        adverse_count = (
            await session.execute(
                select(func.count()).select_from(AdverseMedia).where(AdverseMedia.person_id == pid)
            )
        ).scalar() or 0
        media_coverage = min(100.0, adverse_count * 5)  # 20+ articles = 100

        # 9. Corporate/Business records (0-100)
        corp_count = (
            await session.execute(
                select(func.count())
                .select_from(CorporateDirectorship)
                .where(CorporateDirectorship.person_id == pid)
            )
        ).scalar() or 0
        corporate_depth = min(100.0, corp_count * 20)  # 5+ directorships = 100

        # Weighted composite — OSINT-calibrated
        enrichment_score = round(
            identity_completeness * 0.20
            + social_coverage * 0.20
            + employment_depth * 0.08
            + financial_depth * 0.08
            + legal_records * 0.08
            + property_records * 0.08
            + relationship_count * 0.05
            + media_coverage * 0.13
            + corporate_depth * 0.10,
            2,
        )

        person.enrichment_score = enrichment_score
        await session.flush()
        await session.commit()

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
