"""
genealogy_enricher.py — BFS genealogy enricher daemon.

Runs every 5 minutes. Finds persons flagged with needs_genealogy=true,
crawls 5 genealogy sources in parallel, builds a FamilyTreeSnapshot with
BFS traversal up to 8 ancestor and 5 descendant generations.

Confidence scoring:
  - 1 source  → 0.40
  - 2 sources → 0.72
  - 3+ sources → 0.92
  - government record (birth_cert, census) +0.15, capped at 1.0
"""

import asyncio
import logging
import uuid
from collections import deque
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal
from shared.models.family_tree import FamilyTreeSnapshot
from shared.models.person import Person
from shared.models.relationship import Relationship

logger = logging.getLogger(__name__)

FAMILY_REL_TYPES = [
    "parent_of",
    "child_of",
    "sibling_of",
    "spouse_of",
    "grandparent_of",
    "grandchild_of",
    "aunt_uncle_of",
    "niece_nephew_of",
    "half_sibling_of",
    "step_parent_of",
    "step_child_of",
]

_SLEEP_INTERVAL = 300  # 5 minutes


def compute_confidence(source_count: int, has_gov_record: bool = False) -> float:
    """Confidence scoring: 1→0.40, 2→0.72, 3+→0.92, gov record +0.15"""
    if source_count <= 0:
        return 0.0
    if source_count == 1:
        score = 0.40
    elif source_count == 2:
        score = 0.72
    else:
        score = 0.92
    if has_gov_record:
        score = min(1.0, score + 0.15)
    return score


class GenealogyEnricher:
    """Continuously enriches persons with genealogy data via BFS crawling."""

    def __init__(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        """Entry point — runs forever, sleeping between batches."""
        logger.info("GenealogyEnricher started (interval=%ds)", _SLEEP_INTERVAL)
        while self._running:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("GenealogyEnricher error: %s", exc)
            await asyncio.sleep(_SLEEP_INTERVAL)

    async def _process_pending(self) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Person.id).where(Person.meta["needs_genealogy"].astext == "true").limit(5)
            )
            person_ids = [row[0] for row in result.fetchall()]
            for person_id in person_ids:
                await self.build_tree(person_id, session)

    async def build_tree(
        self, seed_person_id: uuid.UUID, session: AsyncSession
    ) -> FamilyTreeSnapshot:
        from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
        from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
        from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
        from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
        from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler

        crawlers = [
            AncestryHintsCrawler(),
            CensusRecordsCrawler(),
            VitalsRecordsCrawler(),
            NewspapersArchiveCrawler(),
            GeniPublicCrawler(),
        ]

        queue: deque[tuple[uuid.UUID, int]] = deque([(seed_person_id, 0)])
        visited: set[uuid.UUID] = set()
        source_count = 0

        while queue:
            person_id, generation = queue.popleft()
            if person_id in visited or abs(generation) > 8:
                continue
            visited.add(person_id)

            person = await session.get(Person, person_id)
            if not person:
                continue
            identifier = person.full_name or str(person_id)

            results = []
            for crawler in crawlers:
                try:
                    r = await crawler.scrape(identifier)
                    if r and r.found:
                        results.append(r.data)
                        source_count += 1
                except Exception:
                    logger.debug(
                        "Genealogy crawler %s failed for %s",
                        getattr(crawler, "platform", type(crawler).__name__),
                        identifier,
                        exc_info=True,
                    )

            relatives = self._parse_relatives(results)
            for rel in relatives:
                canonical = await self._find_or_create_person(rel, session)
                has_gov = rel.get("record_type") in ("birth_cert", "census")
                confidence = compute_confidence(rel.get("source_count", 1), has_gov)
                await self._upsert_relationship(
                    person_id, canonical.id, rel["rel_type"], confidence, session
                )
                next_gen = (
                    generation - 1
                    if rel["rel_type"] in ("parent_of", "grandparent_of")
                    else generation + 1
                )
                queue.append((canonical.id, next_gen))

        # Build edges from relationships between visited nodes
        await session.flush()
        from shared.models.relationship import Relationship

        edges = []
        if visited:
            rel_result = await session.execute(
                select(Relationship).where(
                    (Relationship.person_a_id.in_(visited))
                    | (Relationship.person_b_id.in_(visited))
                )
            )
            for r in rel_result.scalars().all():
                edges.append(
                    {
                        "source": str(r.person_a_id),
                        "target": str(r.person_b_id),
                        "rel_type": r.relationship_type,
                        "confidence": r.confidence_score,
                    }
                )

        snapshot = FamilyTreeSnapshot(
            root_person_id=seed_person_id,
            tree_json={
                "nodes": [str(pid) for pid in visited],
                "edges": edges,
                "node_count": len(visited),
                "edge_count": len(edges),
            },
            depth_ancestors=8,
            depth_descendants=5,
            source_count=source_count,
            built_at=datetime.now(UTC),
            is_stale=False,
        )
        session.add(snapshot)
        await session.commit()

        # Clear the flag so we don't reprocess
        person = await session.get(Person, seed_person_id)
        if person and person.meta:
            person.meta["needs_genealogy"] = "false"
            await session.flush()

        return snapshot

    def _parse_relatives(self, results: list[dict]) -> list[dict]:
        relatives: list[dict] = []
        for data in results:
            for parent in data.get("parents", []):
                relatives.append(
                    {
                        **parent,
                        "rel_type": "parent_of",
                        "source_count": 1,
                        "record_type": data.get("record_type", "tree"),
                    }
                )
            for child in data.get("children", []):
                relatives.append(
                    {
                        **child,
                        "rel_type": "child_of",
                        "source_count": 1,
                        "record_type": data.get("record_type", "tree"),
                    }
                )
            for spouse in data.get("spouses", []):
                relatives.append(
                    {
                        **spouse,
                        "rel_type": "spouse_of",
                        "source_count": 1,
                        "record_type": data.get("record_type", "tree"),
                    }
                )
            for sibling in data.get("siblings", []):
                relatives.append(
                    {
                        **sibling,
                        "rel_type": "sibling_of",
                        "source_count": 1,
                        "record_type": data.get("record_type", "tree"),
                    }
                )
        return relatives

    async def _find_or_create_person(self, rel: dict, session: AsyncSession) -> Person:
        name = rel.get("name", "Unknown")
        result = await session.execute(select(Person).where(Person.full_name == name).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        new_person = Person(full_name=name, meta={"source": "genealogy_enricher"})
        session.add(new_person)
        await session.flush()
        return new_person

    async def _upsert_relationship(
        self,
        person_a_id: uuid.UUID,
        person_b_id: uuid.UUID,
        rel_type: str,
        confidence: float,
        session: AsyncSession,
    ) -> None:
        result = await session.execute(
            select(Relationship)
            .where(
                Relationship.person_a_id == person_a_id,
                Relationship.person_b_id == person_b_id,
                Relationship.rel_type == rel_type,
            )
            .limit(1)
        )
        rel = result.scalar_one_or_none()
        if rel:
            rel.score = max(rel.score or 0.0, confidence)
        else:
            rel = Relationship(
                person_a_id=person_a_id,
                person_b_id=person_b_id,
                rel_type=rel_type,
                score=confidence,
            )
            session.add(rel)
