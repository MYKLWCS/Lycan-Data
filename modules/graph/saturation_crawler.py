"""
Saturation Crawler — recursive entity discovery with novelty-based stopping.

Starting from a seed entity (person or company), fans out across all registered
crawlers, discovers connected entities, queues them, and keeps crawling until
the novelty rate (new vs duplicate data) drops below threshold.

Growth controls:
  - max_depth: how many hops outward from seed (default 3)
  - max_entities: hard cap on total entities processed (default 200)
  - confidence_threshold: minimum confidence to follow a connection (default 0.6)
  - relationship_filter: optional set of edge types to follow
  - novelty_threshold: stop when novelty < this (default 0.05)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timezone, datetime
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.crawlers.registry import CRAWLER_REGISTRY, get_crawler
from modules.crawlers.result import CrawlerResult
from modules.graph.knowledge_graph import KnowledgeGraphBuilder, _entity_id
from shared.models.address import Address
from shared.models.employment import EmploymentHistory
from shared.models.identifier import Identifier
from shared.models.person import Person
from shared.models.relationship import Relationship
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)


class CrawlPhase(Enum):
    COLLECTING = "collecting"
    ENRICHING = "enriching"
    COMPLETE = "complete"


@dataclass
class CrawlStats:
    total_results: int = 0
    novel_results: int = 0
    duplicate_results: int = 0
    entities_processed: int = 0
    entities_queued: int = 0
    phase: CrawlPhase = CrawlPhase.COLLECTING
    novelty_rate: float = 1.0
    depth_distribution: dict[int, int] = field(default_factory=dict)
    source_contribution: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_seconds: float = 0.0


@dataclass
class QueueItem:
    identifier: str
    entity_type: str  # "person" | "company"
    depth: int
    source_entity: str | None = None  # what entity discovered this one
    confidence: float = 1.0


@dataclass
class GrowthControls:
    max_depth: int = 3
    max_entities: int = 200
    confidence_threshold: float = 0.6
    novelty_threshold: float = 0.05
    min_results_before_check: int = 20
    relationship_filter: set[str] | None = None
    crawl_delay: float = 0.5


# Crawler categories that make sense for person vs company searches
_PERSON_CRAWLERS = [
    "fastpeoplesearch", "truepeoplesearch", "whitepages", "spokeo",
    "peekyou", "radaris", "familytreenow",
    "linkedin", "twitter", "facebook", "instagram",
    "email_holehe", "email_emailrep",
    "phone_truecaller", "phone_numlookup",
    "court_courtlistener",
]

_COMPANY_CRAWLERS = [
    "company_opencorporates", "company_companies_house", "company_sec",
    "gov_gleif", "gov_sam", "gov_usaspending",
    "domain_whois", "financial_crunchbase",
]


class SaturationCrawler:
    """
    Keeps crawling until data novelty drops below threshold, then stops.

    Usage:
        crawler = SaturationCrawler(graph_builder)
        result = await crawler.saturate("John Smith", "person", session)
    """

    def __init__(
        self,
        graph: KnowledgeGraphBuilder,
        controls: GrowthControls | None = None,
    ):
        self.graph = graph
        self.controls = controls or GrowthControls()
        self._seen_hashes: set[str] = set()
        self._processed: set[str] = set()
        self.stats = CrawlStats()

    async def saturate(
        self,
        seed_identifier: str,
        seed_type: str,
        session: AsyncSession,
        on_progress: Callable[[dict], Any] | None = None,
    ) -> dict:
        """
        Run saturation crawl starting from seed entity.

        Returns summary dict with stats and whether saturation was reached.
        """
        self.stats = CrawlStats()
        self._seen_hashes.clear()
        self._processed.clear()

        queue: deque[QueueItem] = deque()
        queue.append(QueueItem(
            identifier=seed_identifier,
            entity_type=seed_type,
            depth=0,
        ))

        logger.info(
            "Saturation crawl started: seed=%r type=%s max_depth=%d max_entities=%d",
            seed_identifier, seed_type, self.controls.max_depth, self.controls.max_entities,
        )

        # ── Phase 1: Collection ───────────────────────────────────────────────
        self.stats.phase = CrawlPhase.COLLECTING
        await self._collection_phase(queue, session, on_progress)

        # ── Phase 2: Enrichment (graph sync) ──────────────────────────────────
        self.stats.phase = CrawlPhase.ENRICHING
        if on_progress:
            await _call_progress(on_progress, self._snapshot())

        await self._sync_to_graph(session)

        # ── Done ──────────────────────────────────────────────────────────────
        self.stats.phase = CrawlPhase.COMPLETE
        self.stats.elapsed_seconds = (
            datetime.now(timezone.utc) - self.stats.started_at
        ).total_seconds()

        overall_novelty = (
            self.stats.novel_results / max(self.stats.total_results, 1)
        )
        saturation_reached = (
            self.stats.total_results >= self.controls.min_results_before_check
            and overall_novelty < self.controls.novelty_threshold
        )

        result = {
            "seed": seed_identifier,
            "seed_type": seed_type,
            "entities_processed": self.stats.entities_processed,
            "total_results": self.stats.total_results,
            "novel_results": self.stats.novel_results,
            "duplicate_results": self.stats.duplicate_results,
            "final_novelty_rate": round(overall_novelty, 4),
            "saturation_reached": saturation_reached,
            "phase": "complete",
            "elapsed_seconds": round(self.stats.elapsed_seconds, 2),
            "depth_distribution": self.stats.depth_distribution,
            "source_contribution": self.stats.source_contribution,
            "errors": self.stats.errors[-20:],  # last 20 errors
        }

        logger.info("Saturation crawl complete: %s", json.dumps(result, default=str))
        return result

    # ── Collection phase ──────────────────────────────────────────────────────

    async def _collection_phase(
        self,
        queue: deque[QueueItem],
        session: AsyncSession,
        on_progress: Callable[[dict], Any] | None,
    ) -> None:
        while queue and self.stats.entities_processed < self.controls.max_entities:
            item = queue.popleft()

            # Skip already-processed or too-deep items
            cache_key = f"{item.entity_type}:{item.identifier.lower().strip()}"
            if cache_key in self._processed:
                continue
            if item.depth > self.controls.max_depth:
                continue
            if item.confidence < self.controls.confidence_threshold:
                continue

            self._processed.add(cache_key)
            self.stats.entities_processed += 1
            self.stats.depth_distribution[item.depth] = (
                self.stats.depth_distribution.get(item.depth, 0) + 1
            )

            logger.debug(
                "Processing: %s %r depth=%d (%d/%d)",
                item.entity_type, item.identifier, item.depth,
                self.stats.entities_processed, self.controls.max_entities,
            )

            # Run crawlers for this entity
            results = await self._crawl_entity(item)

            # Check novelty for each result
            batch_novel = 0
            for cr in results:
                data_hash = _hash_result(cr)
                self.stats.total_results += 1
                self.stats.source_contribution[cr.platform] = (
                    self.stats.source_contribution.get(cr.platform, 0) + 1
                )

                if data_hash not in self._seen_hashes:
                    self._seen_hashes.add(data_hash)
                    self.stats.novel_results += 1
                    batch_novel += 1
                else:
                    self.stats.duplicate_results += 1

            # Guard against memory leak — cap visited set size
            if len(self._seen_hashes) > 50_000:
                logger.warning(
                    "visited_nodes exceeded 50 000 (%d) — stopping crawl to prevent memory leak",
                    len(self._seen_hashes),
                )
                break

            # Discover connected entities and enqueue them
            if item.depth < self.controls.max_depth:
                connections = await self._discover_connections(
                    item, results, session,
                )
                for conn in connections:
                    conn_key = f"{conn.entity_type}:{conn.identifier.lower().strip()}"
                    if conn_key not in self._processed:
                        queue.append(conn)
                        self.stats.entities_queued += 1

            # Progress callback
            if on_progress:
                await _call_progress(on_progress, self._snapshot())

            # Check novelty — stop early if saturated
            if self.stats.total_results >= self.controls.min_results_before_check:
                overall = self.stats.novel_results / max(self.stats.total_results, 1)
                self.stats.novelty_rate = overall
                if overall < self.controls.novelty_threshold:
                    logger.info(
                        "Saturation reached: novelty=%.2f%% after %d results",
                        overall * 100, self.stats.total_results,
                    )
                    break

            # Rate-limit between entities
            if self.controls.crawl_delay > 0:
                await asyncio.sleep(self.controls.crawl_delay)

    async def _crawl_entity(self, item: QueueItem) -> list[CrawlerResult]:
        """Run all relevant crawlers for an entity. Never raises."""
        crawler_names = (
            _PERSON_CRAWLERS if item.entity_type == "person" else _COMPANY_CRAWLERS
        )

        # Only run crawlers that are actually registered
        available = [
            name for name in crawler_names
            if name in CRAWLER_REGISTRY
        ]

        results: list[CrawlerResult] = []
        tasks = []
        for name in available:
            tasks.append(self._run_single_crawler(name, item.identifier))

        # Run concurrently (max 5 at a time to avoid hammering)
        sem = asyncio.Semaphore(5)

        async def _bounded(coro):
            async with sem:
                return await coro

        gathered = await asyncio.gather(
            *[_bounded(t) for t in tasks],
            return_exceptions=True,
        )

        for i, result in enumerate(gathered):
            if isinstance(result, BaseException):
                self.stats.errors.append(f"{available[i]}: {result}")
                continue
            if result is not None and result.found:
                results.append(result)

        return results

    async def _run_single_crawler(
        self, platform: str, identifier: str,
    ) -> CrawlerResult | None:
        """Instantiate and run one crawler. Returns None on failure."""
        try:
            crawler_cls = get_crawler(platform)
            if crawler_cls is None:
                return None
            crawler = crawler_cls()
            return await crawler.scrape(identifier)
        except Exception as exc:
            logger.debug("Crawler %s failed for %r: %s", platform, identifier, exc)
            return None

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def _discover_connections(
        self,
        parent: QueueItem,
        results: list[CrawlerResult],
        session: AsyncSession,
    ) -> list[QueueItem]:
        """
        Extract connected entities from crawler results and the relational DB.

        Returns QueueItems for the next wave of crawling.
        """
        connections: list[QueueItem] = []
        seen_names: set[str] = set()
        next_depth = parent.depth + 1

        # 1. Extract from crawler results (officers, relatives, companies)
        for cr in results:
            data = cr.data

            # Officers / directors found in company crawls
            for officer in data.get("officers", []):
                name = (officer.get("name") or "").strip()
                if name and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    connections.append(QueueItem(
                        identifier=name,
                        entity_type="person",
                        depth=next_depth,
                        source_entity=parent.identifier,
                        confidence=officer.get("confidence", 0.7),
                    ))

            # Companies found in person crawls
            for company in data.get("companies", []) + data.get("employers", []):
                name = company if isinstance(company, str) else (company.get("name") or "")
                name = name.strip()
                if name and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    connections.append(QueueItem(
                        identifier=name,
                        entity_type="company",
                        depth=next_depth,
                        source_entity=parent.identifier,
                        confidence=0.7,
                    ))

            # Relatives / associates
            for relative in data.get("relatives", []) + data.get("associates", []):
                name = relative if isinstance(relative, str) else (relative.get("name") or "")
                name = name.strip()
                if name and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    connections.append(QueueItem(
                        identifier=name,
                        entity_type="person",
                        depth=next_depth,
                        source_entity=parent.identifier,
                        confidence=0.65,
                    ))

        # 2. Cross-reference the relational DB for existing connections
        if parent.entity_type == "person":
            db_connections = await self._db_person_connections(
                parent.identifier, session,
            )
        else:
            db_connections = await self._db_company_connections(
                parent.identifier, session,
            )

        for conn in db_connections:
            key = conn.identifier.lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                conn.depth = next_depth
                conn.source_entity = parent.identifier
                connections.append(conn)

        # Apply relationship filter if set
        if self.controls.relationship_filter:
            # Only keep connections whose type is in the filter
            # (for now, all discovered connections pass through)
            pass

        # Cap per-entity fan-out to prevent explosion
        return connections[:15]

    async def _db_person_connections(
        self, name: str, session: AsyncSession,
    ) -> list[QueueItem]:
        """Find connections for a person name from the relational DB."""
        items: list[QueueItem] = []
        name_lower = name.lower().strip()

        # Find person by name
        stmt = select(Person).where(
            func.lower(Person.full_name) == name_lower
        ).limit(1)
        result = await session.execute(stmt)
        person = result.scalar_one_or_none()
        if not person:
            return items

        pid = person.id

        # Employers
        emp_stmt = select(EmploymentHistory).where(
            EmploymentHistory.person_id == pid,
            EmploymentHistory.employer_name.isnot(None),
        )
        emp_rows = (await session.execute(emp_stmt)).scalars().all()
        for emp in emp_rows:
            items.append(QueueItem(
                identifier=emp.employer_name,
                entity_type="company",
                depth=0,
                confidence=0.85 if emp.is_current else 0.6,
            ))

        # Relationships (other persons)
        rel_stmt = select(Relationship).where(
            (Relationship.person_a_id == pid) | (Relationship.person_b_id == pid)
        )
        rel_rows = (await session.execute(rel_stmt)).scalars().all()
        other_ids = set()
        for rel in rel_rows:
            other_id = rel.person_b_id if rel.person_a_id == pid else rel.person_a_id
            if other_id not in other_ids:
                other_ids.add(other_id)

        if other_ids:
            p_stmt = select(Person).where(Person.id.in_(list(other_ids)))
            p_rows = (await session.execute(p_stmt)).scalars().all()
            for p in p_rows:
                if p.full_name:
                    items.append(QueueItem(
                        identifier=p.full_name,
                        entity_type="person",
                        depth=0,
                        confidence=0.7,
                    ))

        return items

    async def _db_company_connections(
        self, name: str, session: AsyncSession,
    ) -> list[QueueItem]:
        """Find persons connected to a company name from the relational DB."""
        items: list[QueueItem] = []
        name_lower = name.lower().strip()

        emp_stmt = select(EmploymentHistory).where(
            func.lower(EmploymentHistory.employer_name).contains(name_lower)
        )
        emp_rows = (await session.execute(emp_stmt)).scalars().all()

        seen_pids = set()
        for emp in emp_rows:
            if emp.person_id and emp.person_id not in seen_pids:
                seen_pids.add(emp.person_id)

        if seen_pids:
            p_stmt = select(Person).where(Person.id.in_(list(seen_pids)))
            p_rows = (await session.execute(p_stmt)).scalars().all()
            for p in p_rows:
                if p.full_name:
                    items.append(QueueItem(
                        identifier=p.full_name,
                        entity_type="person",
                        depth=0,
                        confidence=0.8,
                    ))

        return items

    # ── Graph sync ────────────────────────────────────────────────────────────

    async def _sync_to_graph(self, session: AsyncSession) -> None:
        """
        Push all discovered entities and relationships into the AGE graph.

        Reads from the relational DB for all processed entities and writes
        them into the knowledge graph.
        """
        for cache_key in self._processed:
            entity_type, identifier = cache_key.split(":", 1)
            try:
                if entity_type == "person":
                    await self._sync_person_to_graph(identifier, session)
                elif entity_type == "company":
                    await self._sync_company_to_graph(identifier, session)
            except Exception:
                logger.debug("Graph sync failed for %s", cache_key, exc_info=True)

    async def _sync_person_to_graph(
        self, name: str, session: AsyncSession,
    ) -> None:
        """Sync a person and their edges into the knowledge graph."""
        name_lower = name.lower().strip()
        stmt = select(Person).where(
            func.lower(Person.full_name) == name_lower
        ).limit(1)
        result = await session.execute(stmt)
        person = result.scalar_one_or_none()
        if not person:
            return

        eid = _entity_id("Person", str(person.id))
        await self.graph.add_entity("Person", eid, {
            "name": person.full_name or "",
            "risk_score": person.default_risk_score or 0.0,
        }, session)

        # Employment edges
        emp_stmt = select(EmploymentHistory).where(
            EmploymentHistory.person_id == person.id,
            EmploymentHistory.employer_name.isnot(None),
        )
        emps = (await session.execute(emp_stmt)).scalars().all()
        for emp in emps:
            company_eid = _entity_id("Company", emp.employer_name)
            try:
                await self.graph.add_entity("Company", company_eid, {
                    "legal_name": emp.employer_name,
                }, session)
                rel_type = "OFFICER_OF" if emp.job_title else "EMPLOYED_BY"
                await self.graph.add_relationship(
                    "Person", eid, rel_type, "Company", company_eid,
                    properties={"title": emp.job_title or "employee"},
                    session=session,
                )
            except Exception:
                pass  # best effort

        # Address edges
        addr_stmt = select(Address).where(Address.person_id == person.id)
        addrs = (await session.execute(addr_stmt)).scalars().all()
        for addr in addrs:
            addr_eid = _entity_id("Address", str(addr.id))
            label = ", ".join(filter(None, [addr.street, addr.city, addr.state_province]))
            try:
                await self.graph.add_entity("Address", addr_eid, {
                    "name": label,
                    "street": addr.street or "",
                    "city": addr.city or "",
                    "state": addr.state_province or "",
                }, session)
                await self.graph.add_relationship(
                    "Person", eid, "LIVES_AT", "Address", addr_eid,
                    session=session,
                )
            except Exception:
                pass

        # Identifier edges (phone, email)
        ident_stmt = select(Identifier).where(
            Identifier.person_id == person.id,
            Identifier.type.in_(["phone", "email"]),
        )
        idents = (await session.execute(ident_stmt)).scalars().all()
        for ident in idents:
            itype = ident.type.lower()
            graph_label = "Phone" if itype == "phone" else "Email"
            edge_type = "HAS_PHONE" if itype == "phone" else "HAS_EMAIL"
            i_eid = _entity_id(graph_label, ident.value)
            try:
                props = {"number": ident.value} if itype == "phone" else {"address": ident.value}
                props["name"] = ident.value
                await self.graph.add_entity(graph_label, i_eid, props, session)
                await self.graph.add_relationship(
                    "Person", eid, edge_type, graph_label, i_eid,
                    session=session,
                )
            except Exception:
                pass

        # Social profile edges
        sp_stmt = select(SocialProfile).where(SocialProfile.person_id == person.id)
        sps = (await session.execute(sp_stmt)).scalars().all()
        for sp in sps:
            sp_eid = _entity_id("Social_Profile", f"{sp.platform}:{sp.handle or sp.platform_user_id}")
            try:
                await self.graph.add_entity("Social_Profile", sp_eid, {
                    "name": f"{sp.platform}:{sp.handle or ''}",
                    "platform": sp.platform,
                    "username": sp.handle or sp.platform_user_id or "",
                }, session)
                await self.graph.add_relationship(
                    "Person", eid, "HAS_PROFILE", "Social_Profile", sp_eid,
                    session=session,
                )
            except Exception:
                pass

    async def _sync_company_to_graph(
        self, name: str, session: AsyncSession,
    ) -> None:
        """Sync a company and its people into the knowledge graph."""
        name_lower = name.lower().strip()
        company_eid = _entity_id("Company", name_lower)

        await self.graph.add_entity("Company", company_eid, {
            "legal_name": name,
            "name": name,
        }, session)

        # Find all people employed there
        emp_stmt = select(EmploymentHistory).where(
            func.lower(EmploymentHistory.employer_name).contains(name_lower)
        )
        emps = (await session.execute(emp_stmt)).scalars().all()

        person_ids = list({emp.person_id for emp in emps if emp.person_id})
        if not person_ids:
            return

        p_stmt = select(Person).where(Person.id.in_(person_ids))
        persons = (await session.execute(p_stmt)).scalars().all()
        person_map = {p.id: p for p in persons}

        for emp in emps:
            person = person_map.get(emp.person_id)
            if not person:
                continue
            person_eid = _entity_id("Person", str(person.id))
            try:
                await self.graph.add_entity("Person", person_eid, {
                    "name": person.full_name or "",
                    "risk_score": person.default_risk_score or 0.0,
                }, session)
                rel_type = "OFFICER_OF" if emp.job_title else "EMPLOYED_BY"
                await self.graph.add_relationship(
                    "Person", person_eid, rel_type, "Company", company_eid,
                    properties={"title": emp.job_title or "employee"},
                    session=session,
                )
            except Exception:
                pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _snapshot(self) -> dict:
        overall = self.stats.novel_results / max(self.stats.total_results, 1)
        return {
            "phase": self.stats.phase.value,
            "entities_processed": self.stats.entities_processed,
            "total_results": self.stats.total_results,
            "novel_results": self.stats.novel_results,
            "novelty_rate": round(overall, 4),
            "depth_distribution": self.stats.depth_distribution,
            "elapsed_seconds": round(
                (datetime.now(timezone.utc) - self.stats.started_at).total_seconds(), 2
            ),
        }


def _hash_result(cr: CrawlerResult) -> str:
    """Deterministic hash of a crawler result for deduplication."""
    payload = json.dumps(
        {"platform": cr.platform, "identifier": cr.identifier, "data": cr.data},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


async def _call_progress(fn: Callable, data: dict) -> None:
    """Call a progress callback, handling both sync and async."""
    result = fn(data)
    if asyncio.iscoroutine(result):
        await result
