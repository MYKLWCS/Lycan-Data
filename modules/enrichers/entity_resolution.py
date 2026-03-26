"""
4-Pass Entity Resolution Pipeline.

Orchestrates the complete deduplication and verification flow:

  Pass 1 — Exact Match:  Hash-based dedup using bloom filter + Dragonfly.
  Pass 2 — Fuzzy Match:  Jaro-Winkler names (≥0.92), Levenshtein addresses,
                          blocking strategy to reduce comparisons.
  Pass 3 — Graph-Based:  Connected component analysis (if A≈B and B≈C → A-B-C).
  Pass 4 — ML-Based:     Trained classifier or rule-based scoring fallback.

After passes complete:
  - Golden Record Construction: merge duplicates with source-priority provenance.
  - Verification: phone/email/address format + carrier/MX/geocoding checks.
  - Confidence Scoring: composite score from source reliability, cross-refs,
    freshness decay, and conflict penalty.

This module is called from the enrichment orchestrator and can also be
invoked directly for batch processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class ResolutionStepResult:
    step: str
    status: str  # "ok" | "skipped" | "error"
    detail: str = ""
    duration_ms: float = 0.0
    candidates_found: int = 0
    clusters_found: int = 0
    merges_executed: int = 0


@dataclass
class EntityResolutionReport:
    person_id: str
    started_at: str
    finished_at: str
    total_duration_ms: float
    steps: list[ResolutionStepResult] = field(default_factory=list)
    total_duplicates_found: int = 0
    total_merges: int = 0
    verification_count: int = 0
    confidence_score: float = 0.0


class EntityResolutionPipeline:
    """
    Orchestrates the 4-pass entity resolution pipeline for a single person.

    Usage:
        pipeline = EntityResolutionPipeline()
        report = await pipeline.resolve(person_id, session)
    """

    # Thresholds
    AUTO_MERGE_THRESHOLD = 0.85
    REVIEW_THRESHOLD = 0.70
    GRAPH_CONFIDENCE_THRESHOLD = 0.70

    async def resolve(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> EntityResolutionReport:
        """Run the full 4-pass pipeline for a single person."""
        started_at = datetime.now(UTC)
        steps: list[ResolutionStepResult] = []
        total_dupes = 0
        total_merges = 0

        # ── Pass 1: Exact Match ──────────────────────────────────────────
        step1 = await self._run_step(
            "pass1_exact_match",
            self._pass1_exact_match(person_id, session),
        )
        steps.append(step1)
        total_dupes += step1.candidates_found

        # ── Pass 2: Fuzzy Match ──────────────────────────────────────────
        step2 = await self._run_step(
            "pass2_fuzzy_match",
            self._pass2_fuzzy_match(person_id, session),
        )
        steps.append(step2)
        total_dupes += step2.candidates_found

        # ── Pass 3: Graph-Based ──────────────────────────────────────────
        step3 = await self._run_step(
            "pass3_graph_clustering",
            self._pass3_graph_clustering(person_id, session),
        )
        steps.append(step3)
        total_merges += step3.merges_executed

        # ── Pass 4: ML/Rule-Based ────────────────────────────────────────
        step4 = await self._run_step(
            "pass4_ml_scoring",
            self._pass4_ml_scoring(person_id, session),
        )
        steps.append(step4)
        total_dupes += step4.candidates_found

        # ── Verification ─────────────────────────────────────────────────
        step_verify = await self._run_step(
            "verification",
            self._run_verification(person_id, session),
        )
        steps.append(step_verify)

        # ── Confidence Scoring ───────────────────────────────────────────
        step_confidence = await self._run_step(
            "confidence_scoring",
            self._run_confidence_scoring(person_id, session),
        )
        steps.append(step_confidence)

        finished_at = datetime.now(UTC)
        total_ms = (finished_at - started_at).total_seconds() * 1000

        return EntityResolutionReport(
            person_id=person_id,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            total_duration_ms=round(total_ms, 2),
            steps=steps,
            total_duplicates_found=total_dupes,
            total_merges=total_merges,
            verification_count=step_verify.candidates_found,
            confidence_score=step_confidence.candidates_found / 100.0,
        )

    # ── Step runner ──────────────────────────────────────────────────────

    async def _run_step(
        self,
        name: str,
        coro,
    ) -> ResolutionStepResult:
        t0 = datetime.now(UTC)
        try:
            result = await coro
            duration = (datetime.now(UTC) - t0).total_seconds() * 1000
            if isinstance(result, ResolutionStepResult):
                result.duration_ms = round(duration, 2)
                return result
            return ResolutionStepResult(
                step=name, status="ok", duration_ms=round(duration, 2)
            )
        except Exception as exc:
            duration = (datetime.now(UTC) - t0).total_seconds() * 1000
            logger.exception("EntityResolution step %r failed for person", name)
            return ResolutionStepResult(
                step=name,
                status="error",
                detail=str(exc)[:200],
                duration_ms=round(duration, 2),
            )

    # ── Pass 1: Exact Match ──────────────────────────────────────────────

    async def _pass1_exact_match(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """
        Check if this person's identifiers match any existing bloom filter
        or Dragonfly cache entries via ExactMatchDeduplicator.
        """
        from shared.models.identifier import Identifier
        from shared.models.person import Person

        from modules.enrichers.deduplication import ExactMatchDeduplicator
        from shared.events import event_bus

        person = await session.get(Person, person_id)
        if person is None:
            return ResolutionStepResult(
                step="pass1_exact_match", status="skipped", detail="person not found"
            )

        # Load identifiers
        stmt = select(Identifier).where(Identifier.person_id == person_id)
        result = await session.execute(stmt)
        idents = result.scalars().all()

        # Build record dict for exact match check
        record: dict[str, str] = {
            "full_name": person.full_name or "",
            "dob": str(person.date_of_birth) if person.date_of_birth else "",
        }
        for ident in idents:
            val = ident.normalized_value or ident.value
            if ident.type == "email":
                record["email"] = val
            elif ident.type == "phone":
                record["phone"] = val
            elif ident.type == "ssn":
                record["ssn"] = val
            elif ident.type == "ein":
                record["ein"] = val

        # Use Dragonfly client if available
        dragonfly = None
        if event_bus.is_connected:
            dragonfly = event_bus.redis

        deduper = ExactMatchDeduplicator(dragonfly_client=dragonfly)
        is_dup, matched_key = deduper.check_and_mark_duplicate(record)

        return ResolutionStepResult(
            step="pass1_exact_match",
            status="ok",
            detail=f"matched_key={matched_key}" if is_dup else "no_exact_match",
            candidates_found=1 if is_dup else 0,
        )

    # ── Pass 2: Fuzzy Match ──────────────────────────────────────────────

    async def _pass2_fuzzy_match(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """Run fuzzy deduplication via score_person_dedup."""
        from modules.enrichers.deduplication import score_person_dedup

        candidates = await score_person_dedup(person_id, session)

        # Route candidates to auto-merge or review queue
        from shared.models.dedup_review import DedupReview

        merges = 0
        reviews = 0
        for c in candidates:
            if c.similarity_score >= self.AUTO_MERGE_THRESHOLD:
                merges += 1
            elif c.similarity_score >= self.REVIEW_THRESHOLD:
                # Check if review already exists
                existing = await session.execute(
                    select(DedupReview).where(
                        DedupReview.person_a_id == c.id_a,
                        DedupReview.person_b_id == c.id_b,
                    )
                )
                if existing.scalar_one_or_none() is None:
                    session.add(
                        DedupReview(
                            person_a_id=c.id_a,
                            person_b_id=c.id_b,
                            similarity_score=c.similarity_score,
                        )
                    )
                    reviews += 1

        if reviews:
            await session.flush()

        return ResolutionStepResult(
            step="pass2_fuzzy_match",
            status="ok",
            detail=f"{len(candidates)} candidates, {merges} auto-merge, {reviews} for review",
            candidates_found=len(candidates),
        )

    # ── Pass 3: Graph-Based ──────────────────────────────────────────────

    async def _pass3_graph_clustering(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """
        Build match graph from existing dedup reviews and fuzzy matches,
        find connected components, and execute merges for high-confidence clusters.
        """
        from modules.enrichers.deduplication import AsyncMergeExecutor
        from modules.enrichers.golden_record import build_golden_record_from_cluster
        from modules.enrichers.graph_dedup import (
            build_graph_from_dedup_reviews,
        )

        graph = await build_graph_from_dedup_reviews(
            session, confidence_threshold=self.GRAPH_CONFIDENCE_THRESHOLD
        )

        clusters = graph.find_clusters()
        if not clusters:
            return ResolutionStepResult(
                step="pass3_graph_clustering",
                status="ok",
                detail="no clusters found",
            )

        # Find clusters involving this person
        relevant = [c for c in clusters if person_id in c.record_ids]
        merges_done = 0

        for cluster in relevant:
            if cluster.avg_confidence >= self.AUTO_MERGE_THRESHOLD and cluster.size <= 5:
                try:
                    golden = await build_golden_record_from_cluster(
                        session, cluster.record_ids
                    )
                    # Merge non-canonical records into canonical
                    executor = AsyncMergeExecutor()
                    for rid in cluster.record_ids:
                        if rid != golden.canonical_id:
                            plan = {
                                "canonical_id": golden.canonical_id,
                                "duplicate_id": rid,
                            }
                            result = await executor.execute(plan, session)
                            if result.get("merged"):
                                merges_done += 1
                except Exception:
                    logger.exception(
                        "Pass 3 merge failed for cluster %s", cluster.cluster_id
                    )

        return ResolutionStepResult(
            step="pass3_graph_clustering",
            status="ok",
            detail=f"{len(clusters)} total clusters, {len(relevant)} relevant, {merges_done} merged",
            clusters_found=len(relevant),
            merges_executed=merges_done,
        )

    # ── Pass 4: ML/Rule-Based ────────────────────────────────────────────

    async def _pass4_ml_scoring(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """
        Re-score borderline candidates using ML model or rule-based fallback.
        """
        from shared.models.dedup_review import DedupReview

        from modules.enrichers.ml_dedup import MLDedup

        # Get unreviewed candidates in the review queue for this person
        stmt = select(DedupReview).where(
            DedupReview.reviewed == False,  # noqa: E712
            (DedupReview.person_a_id == person_id)
            | (DedupReview.person_b_id == person_id),
        )
        result = await session.execute(stmt)
        reviews = result.scalars().all()

        if not reviews:
            return ResolutionStepResult(
                step="pass4_ml_scoring",
                status="ok",
                detail="no pending reviews to re-score",
            )

        ml = MLDedup(match_threshold=self.AUTO_MERGE_THRESHOLD)

        # Load person records for scoring
        from shared.models.identifier import Identifier
        from shared.models.person import Person

        all_person_ids = set()
        for r in reviews:
            all_person_ids.add(str(r.person_a_id))
            all_person_ids.add(str(r.person_b_id))

        persons_stmt = select(Person).where(Person.id.in_(list(all_person_ids)))
        persons_result = await session.execute(persons_stmt)
        persons = {str(p.id): p for p in persons_result.scalars().all()}

        idents_stmt = select(Identifier).where(
            Identifier.person_id.in_(list(all_person_ids))
        )
        idents_result = await session.execute(idents_stmt)
        all_idents = idents_result.scalars().all()

        ident_map: dict[str, dict[str, list[str]]] = {}
        for ident in all_idents:
            pid = str(ident.person_id)
            val = ident.normalized_value or ident.value or ""
            ident_map.setdefault(pid, {"phones": [], "emails": []})
            if ident.type == "phone":
                ident_map[pid]["phones"].append(val)
            elif ident.type == "email":
                ident_map[pid]["emails"].append(val)

        def _to_dict(p) -> dict:
            pid = str(p.id)
            im = ident_map.get(pid, {})
            return {
                "id": pid,
                "full_name": p.full_name or "",
                "dob": str(p.date_of_birth) if p.date_of_birth else "",
                "phones": im.get("phones", []),
                "emails": im.get("emails", []),
                "_source": p.scraped_from or "unknown",
            }

        upgraded = 0
        for review in reviews:
            pa = persons.get(str(review.person_a_id))
            pb = persons.get(str(review.person_b_id))
            if pa is None or pb is None:
                continue

            confidence, is_match = ml.predict(_to_dict(pa), _to_dict(pb))

            if is_match and confidence >= self.AUTO_MERGE_THRESHOLD:
                # Upgrade from review to auto-merge
                review.reviewed = True
                review.decision = "merge"
                upgraded += 1

        if upgraded:
            await session.flush()

        return ResolutionStepResult(
            step="pass4_ml_scoring",
            status="ok",
            detail=f"re-scored {len(reviews)} reviews, {upgraded} upgraded to merge",
            candidates_found=upgraded,
        )

    # ── Verification ─────────────────────────────────────────────────────

    async def _run_verification(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """Verify all identifiers for this person."""
        from modules.enrichers.data_verifiers import verify_person_identifiers

        results = await verify_person_identifiers(person_id, session)
        return ResolutionStepResult(
            step="verification",
            status="ok",
            detail=f"verified {len(results)} identifiers",
            candidates_found=len(results),
        )

    # ── Confidence Scoring ───────────────────────────────────────────────

    async def _run_confidence_scoring(
        self,
        person_id: str,
        session: AsyncSession,
    ) -> ResolutionStepResult:
        """Compute confidence scores for all fields."""
        from modules.enrichers.confidence_scorer import compute_person_confidence

        result = await compute_person_confidence(person_id, session)
        score = result.get("composite_quality", 0.0)
        return ResolutionStepResult(
            step="confidence_scoring",
            status="ok",
            detail=f"composite_quality={score:.4f}",
            # Encode score * 100 as candidates_found for report aggregation
            candidates_found=int(score * 100),
        )
