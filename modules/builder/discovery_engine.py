"""
People Builder — Universal Discovery Engine.

Accepts any combination of criteria and discovers matching people using the
appropriate crawlers. Runs as a background job with SSE progress events.

Phases: DISCOVER → BUILD → FILTER → EXPAND → CONTINUOUS GROWTH
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timezone, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.builder.criteria_router import CriteriaRouter
from modules.builder.filters import apply_post_filters
from shared.db import AsyncSessionLocal
from shared.events import event_bus
from shared.models.builder_job import BuilderJob, BuilderJobPerson
from shared.models.person import Person

logger = logging.getLogger(__name__)

# Relationship types to discover per person during expansion
EXPANSION_REL_TYPES = [
    "family", "associate", "employer", "employee", "cohabitant",
    "business_partner", "co_signatory",
]


class PeopleBuilder:
    """Orchestrates the full people-discovery pipeline."""

    def __init__(self) -> None:
        self._criteria_router = CriteriaRouter()
        self._active_jobs: dict[str, bool] = {}  # job_id -> cancelled flag

    async def start_discovery(
        self,
        criteria: dict[str, Any],
        max_results: int = 100,
    ) -> str:
        """Create a builder job and kick off async discovery. Returns job_id."""
        max_results = min(max(1, max_results), 10_000)

        async with AsyncSessionLocal() as session:
            job = BuilderJob(
                criteria=criteria,
                max_results=max_results,
                status="pending",
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = str(job.id)

        self._active_jobs[job_id] = False
        asyncio.create_task(self._run_pipeline(job_id, criteria, max_results))
        return job_id

    async def cancel_job(self, job_id: str) -> bool:
        """Signal a running job to cancel."""
        if job_id in self._active_jobs:
            self._active_jobs[job_id] = True
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(BuilderJob)
                    .where(BuilderJob.id == uuid.UUID(job_id))
                    .values(status="cancelled", completed_at=datetime.now(timezone.utc))
                )
                await session.commit()
            return True
        return False

    def _is_cancelled(self, job_id: str) -> bool:
        return self._active_jobs.get(job_id, False)

    # ── Main pipeline ──────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        job_id: str,
        criteria: dict[str, Any],
        max_results: int,
    ) -> None:
        try:
            await self._update_status(job_id, "discovering", started_at=datetime.now(timezone.utc))
            await self._emit(job_id, "discovering", "Starting discovery...")

            # Phase 1: DISCOVER
            raw_persons = await self._phase_discover(job_id, criteria, max_results)
            if self._is_cancelled(job_id):
                return

            # Phase 2: BUILD — enrich each discovered person
            await self._update_status(job_id, "building")
            built_persons = await self._phase_build(job_id, raw_persons)
            if self._is_cancelled(job_id):
                return

            # Phase 3: FILTER — apply criteria as post-filters
            await self._update_status(job_id, "filtering")
            filtered = await self._phase_filter(job_id, criteria, built_persons)
            if self._is_cancelled(job_id):
                return

            # Phase 4: EXPAND — queue relationship expansion for passed persons
            await self._update_status(job_id, "expanding")
            await self._phase_expand(job_id, filtered)

            # Mark complete
            await self._update_status(
                job_id, "complete", completed_at=datetime.now(timezone.utc)
            )
            await self._emit(
                job_id,
                "complete",
                f"Done. {len(filtered)} profiles built, relationships expanding in background.",
            )

        except Exception as exc:
            logger.exception("Builder job %s failed", job_id)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(BuilderJob)
                    .where(BuilderJob.id == uuid.UUID(job_id))
                    .values(
                        status="failed",
                        error_message=str(exc)[:2000],
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
            await self._emit(job_id, "error", f"Job failed: {exc}")
        finally:
            self._active_jobs.pop(job_id, None)

    # ── Phase 1: DISCOVER ──────────────────────────────────────────────────

    async def _phase_discover(
        self,
        job_id: str,
        criteria: dict[str, Any],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Use CriteriaRouter to pick crawlers and find candidate people."""
        sources = self._criteria_router.route(criteria)
        discovered: list[dict[str, Any]] = []
        total_sources = len(sources)

        for idx, source in enumerate(sources):
            if self._is_cancelled(job_id):
                break
            if len(discovered) >= max_results * 3:  # Over-discover for filtering headroom
                break

            await self._emit(
                job_id,
                "discovering",
                f"Searching source {idx + 1}/{total_sources}: {source['name']}...",
            )

            try:
                results = await self._run_source(source, criteria, max_results)
                discovered.extend(results)
            except Exception:
                logger.warning("Source %s failed for job %s", source["name"], job_id)

        # Deduplicate by name+location rough key
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in discovered:
            key = (p.get("full_name", "") + "|" + p.get("location", "")).lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        await self._update_counters(job_id, discovered_count=len(unique))
        await self._emit(
            job_id, "discovering", f"Found {len(unique)} potential matches."
        )
        return unique[:max_results * 2]

    async def _run_source(
        self,
        source: dict[str, Any],
        criteria: dict[str, Any],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Execute a single discovery source. Returns raw person dicts."""
        from modules.crawlers.registry import CRAWLER_REGISTRY

        crawler_name = source.get("crawler")
        if not crawler_name or crawler_name not in CRAWLER_REGISTRY:
            return []

        crawler_cls = CRAWLER_REGISTRY[crawler_name]
        crawler = crawler_cls()

        search_params = source.get("params", {})
        # crawl(query, params) — build query from name/location, pass rest as params
        query = search_params.get("name") or search_params.get("location") or ""
        crawl_params = {k: v for k, v in search_params.items() if k != "name"}
        try:
            result = await asyncio.wait_for(
                crawler.crawl(query, crawl_params), timeout=120
            )
            if isinstance(result, dict):
                persons = result.get("persons", result.get("results", []))
                if isinstance(persons, list):
                    return persons[:max_results]
            elif isinstance(result, list):
                # Convert CrawlerResult objects to person dicts
                person_dicts = []
                for item in result:
                    if hasattr(item, "data") and hasattr(item, "found"):
                        if item.found and item.data:
                            person_dicts.append({
                                **item.data,
                                "_source": item.platform,
                                "_source_reliability": item.source_reliability,
                            })
                    elif isinstance(item, dict):
                        person_dicts.append(item)
                return person_dicts[:max_results]
        except asyncio.TimeoutError:
            logger.warning("Timeout on crawler %s", crawler_name)
        except Exception:
            logger.warning("Crawler %s failed", crawler_name, exc_info=True)
        return []

    # ── Phase 2: BUILD ─────────────────────────────────────────────────────

    async def _phase_build(
        self,
        job_id: str,
        raw_persons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create Person records and queue full enrichment for each."""
        built: list[dict[str, Any]] = []

        for idx, raw in enumerate(raw_persons):
            if self._is_cancelled(job_id):
                break

            name = raw.get("full_name", raw.get("name", "Unknown"))
            await self._emit(
                job_id,
                "building",
                f"Building profile {idx + 1}/{len(raw_persons)} — {name}...",
            )

            async with AsyncSessionLocal() as session:
                person = await self._upsert_person(session, raw)
                person_id = str(person.id)

                # Link to job
                link = BuilderJobPerson(
                    job_id=uuid.UUID(job_id),
                    person_id=person.id,
                    phase="built",
                    enrichment_score=person.enrichment_score or 0.0,
                )
                session.add(link)
                await session.commit()

            # Queue enrichment via event bus
            try:
                await event_bus.publish("enrichment", {
                    "event": "crawl_complete",
                    "person_id": person_id,
                    "depth": 0,
                    "source": "builder",
                })
            except Exception:
                logger.debug("Could not publish enrichment event for %s", person_id)

            built.append({**raw, "_person_id": person_id, "_enrichment": person.enrichment_score or 0.0})

        await self._update_counters(job_id, built_count=len(built))
        return built

    async def _upsert_person(
        self, session: AsyncSession, raw: dict[str, Any]
    ) -> Person:
        """Create or find existing person from raw discovery data."""
        full_name = raw.get("full_name", raw.get("name"))
        dob_str = raw.get("date_of_birth", raw.get("dob"))

        # Try to find existing person by name + DOB
        if full_name:
            stmt = select(Person).where(Person.full_name == full_name)
            if dob_str:
                from datetime import date as date_type
                try:
                    if isinstance(dob_str, str):
                        dob = date_type.fromisoformat(dob_str)
                    else:
                        dob = dob_str
                    stmt = stmt.where(Person.date_of_birth == dob)
                except (ValueError, TypeError):
                    pass
            result = await session.execute(stmt.limit(1))
            existing = result.scalar_one_or_none()
            if existing and existing.merged_into is None:
                return existing

        # Create new person
        person = Person(
            full_name=full_name,
            gender=raw.get("gender"),
            nationality=raw.get("nationality"),
            marital_status=raw.get("marital_status"),
            enrichment_score=0.0,
        )
        if dob_str:
            try:
                from datetime import date as date_type
                person.date_of_birth = (
                    date_type.fromisoformat(dob_str) if isinstance(dob_str, str) else dob_str
                )
            except (ValueError, TypeError):
                pass

        session.add(person)
        await session.flush()
        return person

    # ── Phase 3: FILTER ────────────────────────────────────────────────────

    async def _phase_filter(
        self,
        job_id: str,
        criteria: dict[str, Any],
        built_persons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply original criteria as post-filters on built persons."""
        passed: list[dict[str, Any]] = []

        async with AsyncSessionLocal() as session:
            for bp in built_persons:
                if self._is_cancelled(job_id):
                    break
                person_id = bp.get("_person_id")
                if not person_id:
                    continue

                result = await session.execute(
                    select(Person).where(Person.id == uuid.UUID(person_id))
                )
                person = result.scalar_one_or_none()
                if not person:
                    continue

                if apply_post_filters(person, criteria):
                    passed.append(bp)
                    # Update link phase
                    await session.execute(
                        update(BuilderJobPerson)
                        .where(
                            BuilderJobPerson.job_id == uuid.UUID(job_id),
                            BuilderJobPerson.person_id == uuid.UUID(person_id),
                        )
                        .values(phase="filtered_in")
                    )
                else:
                    await session.execute(
                        update(BuilderJobPerson)
                        .where(
                            BuilderJobPerson.job_id == uuid.UUID(job_id),
                            BuilderJobPerson.person_id == uuid.UUID(person_id),
                        )
                        .values(phase="filtered_out")
                    )
            await session.commit()

        # Sort by enrichment score descending
        passed.sort(key=lambda x: x.get("_enrichment", 0), reverse=True)

        # Cap to max_results
        async with AsyncSessionLocal() as session:
            job_result = await session.execute(
                select(BuilderJob).where(BuilderJob.id == uuid.UUID(job_id))
            )
            job = job_result.scalar_one_or_none()
            max_r = job.max_results if job else 100

        passed = passed[:max_r]
        await self._update_counters(job_id, filtered_count=len(passed))
        await self._emit(
            job_id,
            "filtering",
            f"Applied filters — {len(passed)} of {len(built_persons)} match criteria.",
        )
        return passed

    # ── Phase 4: EXPAND ────────────────────────────────────────────────────

    async def _phase_expand(
        self,
        job_id: str,
        filtered: list[dict[str, Any]],
    ) -> None:
        """Queue relationship expansion for each filtered person."""
        expanded = 0
        rels_mapped = 0

        for fp in filtered:
            if self._is_cancelled(job_id):
                break
            person_id = fp.get("_person_id")
            if not person_id:
                continue

            await self._emit(
                job_id,
                "expanding",
                f"Expanding relationships for {fp.get('full_name', person_id)}...",
            )

            # Mark person as favourited for continuous growth
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Person)
                    .where(Person.id == uuid.UUID(person_id))
                    .values(meta=Person.meta + {"builder_favourited": True, "builder_job_id": job_id})
                )
                await session.commit()

            # Publish expansion event
            try:
                await event_bus.publish("graph", {
                    "event": "expand_relationships",
                    "person_id": person_id,
                    "depth": 2,
                    "source": "builder",
                })
            except Exception:
                logger.debug("Could not publish expansion event for %s", person_id)

            expanded += 1

        await self._update_counters(job_id, expanded_count=expanded, relationships_mapped=rels_mapped)
        await self._emit(
            job_id,
            "expanding",
            f"Expanding relationships for {expanded} profiles...",
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _update_status(
        self,
        job_id: str,
        status: str,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        async with AsyncSessionLocal() as session:
            values: dict[str, Any] = {"status": status}
            if started_at:
                values["started_at"] = started_at
            if completed_at:
                values["completed_at"] = completed_at
            await session.execute(
                update(BuilderJob)
                .where(BuilderJob.id == uuid.UUID(job_id))
                .values(**values)
            )
            await session.commit()

    async def _update_counters(self, job_id: str, **kwargs: int) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(BuilderJob)
                .where(BuilderJob.id == uuid.UUID(job_id))
                .values(**kwargs)
            )
            await session.commit()

    async def _emit(self, job_id: str, phase: str, message: str) -> None:
        """Publish SSE progress event."""
        try:
            await event_bus.publish("progress", {
                "event": "builder_progress",
                "job_id": job_id,
                "phase": phase,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass  # SSE is best-effort


# Module-level singleton
people_builder = PeopleBuilder()
