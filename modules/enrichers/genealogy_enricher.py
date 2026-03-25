"""Genealogy enricher — runs genealogy crawlers, builds family tree, persists to DB."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

FAMILY_REL_TYPES: frozenset[str] = frozenset({
    "parent_of",
    "child_of",
    "sibling_of",
    "spouse_of",
    "grandparent_of",
    "grandchild_of",
    "aunt_uncle_of",
    "niece_nephew_of",
    "step_parent_of",
    "step_child_of",
    "half_sibling_of",
})

ANCESTOR_TYPES: frozenset[str] = frozenset({
    "parent_of",
    "grandparent_of",
    "step_parent_of",
})

GOVERNMENT_PLATFORMS: frozenset[str] = frozenset({
    "census_records",
    "vitals_records",
    "people_familysearch",
})


def compute_confidence(source_results: list[dict], is_government: bool = False) -> float:
    """Compute confidence score based on corroborating sources."""
    n = len(source_results)
    if n == 0:
        return 0.0
    if n == 1:
        score = 0.40
    elif n == 2:
        score = 0.72
    else:
        score = 0.92

    if is_government:
        score = min(1.0, score + 0.15)

    return score


class GenealogyEnricher:
    """
    Daemon that enriches Person records with genealogy data.
    Uses BFS to build a family tree up to 8 ancestor generations.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def start(self) -> None:
        """Main daemon loop — runs _process_pending every 60 seconds."""
        while True:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("GenealogyEnricher error: %s", exc)
            await asyncio.sleep(60)

    async def _process_pending(self) -> None:
        """Find persons without genealogy snapshots and enrich them."""
        from shared.models.person import Person
        from shared.models.family_tree import FamilyTreeSnapshot

        async with self._session_factory() as session:
            from sqlalchemy import select, not_, exists

            stmt = (
                select(Person)
                .where(
                    not_(
                        exists().where(
                            FamilyTreeSnapshot.root_person_id == Person.id
                        )
                    )
                )
                .limit(10)
            )
            result = await session.execute(stmt)
            persons = result.scalars().all()

        for person in persons:
            try:
                await self._enrich_person(person)
            except Exception as exc:
                logger.exception("Failed to enrich person %s: %s", person.id, exc)

    async def _enrich_person(self, person: Any) -> None:
        """Run crawlers and build tree for a single person."""
        name = person.full_name or ""
        dob = person.date_of_birth
        birth_year = str(dob.year) if dob else ""
        identifier = f"{name}:{birth_year}"

        source_results = await self._run_genealogy_crawlers(identifier)
        relatives = self._parse_relatives(source_results)
        tree = await self.build_tree(person, relatives)
        await self._save_tree(person, tree, source_results)

    async def _run_genealogy_crawlers(self, identifier: str) -> list[dict]:
        """Run all registered genealogy crawlers for the identifier."""
        from modules.crawlers.registry import get_crawler

        platforms = ["ancestry_hints", "census_records", "geni_public",
                     "newspapers_archive", "vitals_records"]
        results = []
        for platform in platforms:
            crawler_cls = get_crawler(platform)
            if crawler_cls is None:
                continue
            crawler = crawler_cls()
            try:
                result = await crawler.scrape(identifier)
                if result.found:
                    results.append({
                        "platform": platform,
                        "data": result.data,
                    })
            except Exception as exc:
                logger.warning("Crawler %s failed: %s", platform, exc)
        return results

    def _parse_relatives(self, source_results: list[dict]) -> list[dict]:
        """Extract relative records from crawler results."""
        relatives = []
        for source in source_results:
            data = source.get("data", {})
            for record in data.get("records", []):
                for rel in record.get("relationships", []):
                    name = rel.get("person2") or rel.get("name", "")
                    if parent := {"name": name, "rel_type": rel.get("type", "parent_of")}:
                        if parent.get("name"):
                            relatives.append(parent)
            for profile in data.get("profiles", []):
                name = profile.get("name", "")
                if name:
                    relatives.append({"name": name, "rel_type": "sibling_of"})
        return relatives

    async def build_tree(self, root_person: Any, relatives: list[dict]) -> dict:
        """BFS family tree construction from root person."""
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        visited: set[str] = set()

        root_id = str(root_person.id)
        nodes[root_id] = {
            "id": root_id,
            "name": root_person.full_name or "",
            "generation": 0,
        }
        visited.add(root_id)

        queue: deque[tuple[str, int]] = deque()
        for rel in relatives:
            queue.append((rel["name"], rel.get("rel_type", "parent_of")))

        generation = 0
        processed: set[str] = set()

        while queue:
            name, rel_type = queue.popleft()

            if name in processed:
                continue
            processed.add(name)

            if rel_type in ANCESTOR_TYPES:
                generation -= 1
            else:
                generation += 1

            if generation < -8:
                continue

            person_id = await self._find_or_create_person(name)

            if person_id in visited:
                continue

            visited.add(person_id)
            nodes[person_id] = {
                "id": person_id,
                "name": name,
                "generation": generation,
            }
            edges.append({
                "from": root_id,
                "to": person_id,
                "rel_type": rel_type,
            })

        depths = self._compute_depths(nodes)
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "depth_ancestors": depths["ancestors"],
            "depth_descendants": depths["descendants"],
        }

    async def _find_or_create_person(self, name: str) -> str:
        """Find existing person by name or create a new one."""
        from shared.models.person import Person
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = select(Person).where(Person.full_name.ilike(name)).limit(1)
            result = await session.execute(stmt)
            existing = result.scalars().first()
            if existing:
                return str(existing.id)

            new_person = Person(full_name=name)
            session.add(new_person)
            try:
                await session.commit()
                await session.refresh(new_person)
                return str(new_person.id)
            except Exception:
                await session.rollback()
                # Race condition — try fetch again
                result2 = await session.execute(stmt)
                found = result2.scalars().first()
                if found:
                    return str(found.id)
                return name  # fallback: use name as ID

    def _compute_depths(self, nodes: dict[str, dict]) -> dict[str, int]:
        """Compute max ancestor and descendant depths via dual BFS."""
        max_ancestor = 0
        max_descendant = 0

        for node in nodes.values():
            gen = node.get("generation", 0)
            if gen < 0:
                max_ancestor = max(max_ancestor, abs(gen))
            elif gen > 0:
                max_descendant = max(max_descendant, gen)

        return {"ancestors": max_ancestor, "descendants": max_descendant}

    async def _save_tree(self, person: Any, tree: dict, source_results: list[dict]) -> None:
        """Persist tree snapshot to DB."""
        from shared.models.family_tree import FamilyTreeSnapshot

        is_gov = any(
            s.get("platform") in GOVERNMENT_PLATFORMS for s in source_results
        )
        confidence = compute_confidence(source_results, is_government=is_gov)

        snapshot = FamilyTreeSnapshot(
            root_person_id=person.id,
            tree_json=tree,
            depth_ancestors=tree.get("depth_ancestors", 0),
            depth_descendants=tree.get("depth_descendants", 0),
            source_count=len(source_results),
            built_at=datetime.now(UTC),
            is_stale=False,
        )

        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()

        logger.info(
            "Saved tree for person %s (confidence=%.2f, sources=%d)",
            person.id,
            confidence,
            len(source_results),
        )
