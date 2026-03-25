"""genealogy_enricher.py — GenealogyEnricher daemon + BFS family tree builder."""
from __future__ import annotations
import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from shared.db import AsyncSessionLocal as AsyncSessionFactory
from shared.models.family_tree import FamilyTreeSnapshot
from shared.models.person import Person
from shared.models.relationship import Relationship

logger = logging.getLogger(__name__)

FAMILY_REL_TYPES = frozenset({
    "parent_of","child_of","sibling_of","spouse_of",
    "grandparent_of","grandchild_of","aunt_uncle_of","niece_nephew_of",
    "half_sibling_of","step_parent_of","step_child_of",
})
ANCESTOR_TYPES = frozenset({"parent_of","grandparent_of","step_parent_of"})
GENEALOGY_PLATFORMS = [
    "census_records","vitals_records","people_familysearch",
    "newspapers_archive","ancestry_hints","geni_public",
]
GOVERNMENT_PLATFORMS = frozenset({"census_records","vitals_records","people_familysearch"})
SLEEP_INTERVAL_SECONDS = 300


def compute_confidence(source_results: list[dict], is_government: bool = False) -> float:
    count = len(source_results)
    if count == 0: return 0.0
    if count == 1: base = 0.40
    elif count == 2: base = 0.72
    else: base = 0.92
    bonus = 0.15 if is_government else 0.0
    return min(1.0, base + bonus)


class GenealogyEnricher:
    async def start(self) -> None:
        logger.info("GenealogyEnricher started (interval=%ds)", SLEEP_INTERVAL_SECONDS)
        while True:
            try:
                await self._process_pending()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("GenealogyEnricher: unhandled error in batch")
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)

    async def _process_pending(self) -> None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Person).where(
                    Person.meta["needs_genealogy"].as_boolean().is_(True),
                    Person.merged_into.is_(None),
                )
            )
            persons = result.scalars().all()
            logger.info("GenealogyEnricher: %d person(s) flagged", len(persons))
            for person in persons:
                try:
                    async with AsyncSessionFactory() as build_session:
                        snapshot = await self.build_tree(person.id, build_session)
                        await build_session.commit()
                    logger.info("GenealogyEnricher: built tree for %s", person.id)
                    meta = dict(person.meta or {})
                    meta["needs_genealogy"] = False
                    person.meta = meta
                    await session.commit()
                except Exception:
                    logger.exception("GenealogyEnricher: failed for person %s", person.id)

    async def build_tree(self, seed_person_id: UUID, session: AsyncSession) -> FamilyTreeSnapshot:
        queue: deque[tuple[UUID, int]] = deque([(seed_person_id, 0)])
        visited: set[UUID] = set()
        max_ancestors = 8
        while queue:
            person_id, generation = queue.popleft()
            if person_id in visited: continue
            if generation < 0 and abs(generation) > max_ancestors: continue
            visited.add(person_id)
            results = await self._run_genealogy_crawlers(person_id, session)
            relatives = self._parse_relatives(results)
            for relative in relatives:
                rel_type = relative.get("rel_type","")
                if rel_type not in FAMILY_REL_TYPES: continue
                canonical = await self._find_or_create_person(relative, session)
                if canonical.id in visited: continue
                is_gov = relative.get("platform") in GOVERNMENT_PLATFORMS
                confidence = compute_confidence(relative.get("sources",[]), is_government=is_gov)
                await self._upsert_relationship(person_id, canonical.id, rel_type, confidence,
                                                relative.get("sources",[]), session)
                delta = -1 if rel_type in ANCESTOR_TYPES else 1
                queue.append((canonical.id, generation + delta))
        return await self._save_snapshot(seed_person_id, visited, session)

    async def _run_genealogy_crawlers(self, person_id: UUID, session: AsyncSession) -> list[dict]:
        person = await session.get(Person, person_id)
        if not person or not person.full_name: return []
        identifier = person.full_name
        if person.date_of_birth:
            identifier = f"{person.full_name} {person.date_of_birth.year}"
        from modules.crawlers.registry import get_crawler
        results: list[dict] = []
        for platform in GENEALOGY_PLATFORMS:
            crawler_cls = get_crawler(platform)
            if crawler_cls is None: continue
            try:
                crawler = crawler_cls()
                result = await crawler.scrape(identifier)
                if result.found and result.data:
                    relatives = result.data.get("relatives",[])
                    source_url = result.data.get("source_url","")
                    if relatives:
                        record = {"_platform": platform, "_reliability": result.source_reliability,
                                  "source_url": source_url}
                        for rel in relatives:
                            rel_type = rel.get("relationship","")
                            full_name = rel.get("full_name","").strip()
                            if not full_name or rel_type not in FAMILY_REL_TYPES: continue
                            key = rel_type + "s_list"
                            record.setdefault(key,[]).append({"name": full_name,
                                "birth_year": rel.get("birth_year"), "rel_type": rel_type,
                                "platform": platform, "sources": [{"platform": platform,"url": source_url}]})
                        results.append(record)
                    for pd in result.data.get("persons",[]):
                        pd["_platform"] = platform
                        pd["_reliability"] = result.source_reliability
                        results.append(pd)
            except Exception:
                logger.debug("crawler %s failed for %s", platform, person_id)
        return results

    def _parse_relatives(self, results: list[dict]) -> list[dict]:
        relatives: list[dict] = []
        for record in results:
            platform = record.get("_platform","unknown")
            source_url = record.get("source_url","")
            for rel_type in FAMILY_REL_TYPES:
                for entry in record.get(rel_type+"s_list",[]):
                    if entry.get("name"):
                        relatives.append({"name": entry["name"], "birth_year": entry.get("birth_year"),
                            "rel_type": rel_type, "platform": platform,
                            "sources": entry.get("sources",[{"platform": platform,"url": source_url}])})
            for parent in record.get("parents",[]):
                if parent.get("name"):
                    relatives.append({"name": parent["name"],"birth_year": parent.get("birth_year"),
                        "rel_type":"parent_of","platform": platform,
                        "sources":[{"platform": platform,"url": source_url}]})
            for child in record.get("children",[]):
                if child.get("name"):
                    relatives.append({"name": child["name"],"birth_year": child.get("birth_year"),
                        "rel_type":"child_of","platform": platform,
                        "sources":[{"platform": platform,"url": source_url}]})
            for spouse in record.get("spouses",[]):
                if spouse.get("name"):
                    relatives.append({"name": spouse["name"],"birth_year": None,
                        "rel_type":"spouse_of","platform": platform,
                        "sources":[{"platform": platform,"url": source_url}]})
            for sibling in record.get("siblings",[]):
                if sibling.get("name"):
                    relatives.append({"name": sibling["name"],"birth_year": sibling.get("birth_year"),
                        "rel_type":"sibling_of","platform": platform,
                        "sources":[{"platform": platform,"url": source_url}]})
        return relatives

    async def _find_or_create_person(self, relative: dict, session: AsyncSession) -> Person:
        name = relative.get("name","").strip()
        birth_year = relative.get("birth_year")
        if not name:
            p = Person(full_name="Unknown", meta={"genealogy_placeholder": True})
            session.add(p); await session.flush(); return p
        stmt = select(Person).where(Person.full_name.ilike(name))
        result = await session.execute(stmt)
        candidates = result.scalars().all()
        if birth_year:
            year_matches = [c for c in candidates if c.date_of_birth and c.date_of_birth.year == birth_year]
            if year_matches: return year_matches[0]
        if candidates: return candidates[0]
        kwargs = {"full_name": name, "meta": {"genealogy_sourced": True}}
        if birth_year:
            try: kwargs["date_of_birth"] = datetime(birth_year, 1, 1).date()
            except Exception: pass
        p = Person(**kwargs)
        session.add(p); await session.flush(); return p

    async def _upsert_relationship(self, person_a_id: UUID, person_b_id: UUID, rel_type: str,
            confidence: float, sources: list[dict], session: AsyncSession) -> None:
        stmt = (pg_insert(Relationship).values(
            person_a_id=person_a_id, person_b_id=person_b_id, rel_type=rel_type,
            score=confidence, evidence={"sources": sources},
            first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        ).on_conflict_do_update(
            constraint="uq_relationship",
            set_={"score": confidence, "evidence": {"sources": sources},
                  "last_seen_at": datetime.now(UTC)},
        ))
        await session.execute(stmt)
        await session.flush()

    async def _save_snapshot(self, root_person_id: UUID, visited: set[UUID],
            session: AsyncSession) -> FamilyTreeSnapshot:
        tree_json = await self._build_tree_json(root_person_id, visited, session)
        depth_ancestors, depth_descendants = await self._compute_depths(root_person_id, session)
        existing = (await session.execute(
            select(FamilyTreeSnapshot).where(FamilyTreeSnapshot.root_person_id == root_person_id)
        )).scalars().first()
        if existing:
            await session.delete(existing); await session.flush()
        snapshot = FamilyTreeSnapshot(root_person_id=root_person_id, tree_json=tree_json,
            depth_ancestors=depth_ancestors, depth_descendants=depth_descendants,
            source_count=len(visited), built_at=datetime.now(UTC), is_stale=False)
        session.add(snapshot); await session.flush()
        return snapshot

    async def _build_tree_json(self, root_person_id: UUID, visited: set[UUID],
            session: AsyncSession) -> dict:
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        if visited:
            result = await session.execute(select(Person).where(Person.id.in_(visited)))
            for p in result.scalars().all():
                nodes[str(p.id)] = {"id": str(p.id), "name": p.full_name or "Unknown",
                    "birth_date": p.date_of_birth.isoformat() if p.date_of_birth else None,
                    "is_root": p.id == root_person_id}
        if visited:
            rel_result = await session.execute(select(Relationship).where(
                Relationship.person_a_id.in_(visited), Relationship.person_b_id.in_(visited),
                Relationship.rel_type.in_(FAMILY_REL_TYPES),
            ))
            for rel in rel_result.scalars().all():
                edges.append({"from": str(rel.person_a_id), "to": str(rel.person_b_id),
                    "rel_type": rel.rel_type, "confidence": rel.score})
        return {"root_person_id": str(root_person_id), "nodes": nodes, "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges)}

    async def _compute_depths(self, root_person_id: UUID, session: AsyncSession) -> tuple[int,int]:
        depth_ancestors = 0
        depth_descendants = 0
        ancestor_q: deque[tuple[UUID, int]] = deque([(root_person_id, 0)])
        seen_anc: set[UUID] = {root_person_id}
        while ancestor_q:
            pid, d = ancestor_q.popleft()
            rels = (await session.execute(select(Relationship).where(
                Relationship.person_b_id == pid, Relationship.rel_type.in_(ANCESTOR_TYPES),
            ))).scalars().all()
            for rel in rels:
                if rel.person_a_id not in seen_anc:
                    seen_anc.add(rel.person_a_id)
                    depth_ancestors = max(depth_ancestors, d+1)
                    ancestor_q.append((rel.person_a_id, d+1))
        desc_q: deque[tuple[UUID, int]] = deque([(root_person_id, 0)])
        seen_desc: set[UUID] = {root_person_id}
        while desc_q:
            pid, d = desc_q.popleft()
            rels = (await session.execute(select(Relationship).where(
                Relationship.person_a_id == pid, Relationship.rel_type == "child_of",
            ))).scalars().all()
            for rel in rels:
                if rel.person_b_id not in seen_desc:
                    seen_desc.add(rel.person_b_id)
                    depth_descendants = max(depth_descendants, d+1)
                    desc_q.append((rel.person_b_id, d+1))
        return depth_ancestors, depth_descendants
