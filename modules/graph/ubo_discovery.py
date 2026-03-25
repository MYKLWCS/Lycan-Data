"""
ubo_discovery.py — Recursive Ultimate Beneficial Owner (UBO) chain discovery.

Inputs  a company name, fans out to all registered company crawlers, then
performs BFS over the resulting officer graph until natural persons are found.

Each corporate layer triggers another round of crawling, so the BFS may hit
multiple external APIs per hop. External I/O is gathered concurrently;
DB writes are sequential (SQLAlchemy session is not concurrency-safe).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.crawlers.registry import get_crawler
from modules.crawlers.result import CrawlerResult
from modules.graph.company_intel import CompanyIntelligenceEngine
from shared.models.employment import EmploymentHistory
from shared.models.person import Person
from shared.models.watchlist import WatchlistMatch

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_COMPANY_CRAWLERS = ["company_opencorporates", "company_companies_house", "company_sec"]
_GLEIF_CRAWLER = "gov_gleif"

_OFFSHORE_JURISDICTIONS: frozenset[str] = frozenset(
    {
        "vg",
        "ky",
        "pa",
        "sc",
        "li",
        "mh",
        "bm",
        "ag",
        "ws",
        "vc",
        "british virgin islands",
        "cayman islands",
        "panama",
        "seychelles",
        "liechtenstein",
        "marshall islands",
        "bermuda",
        "antigua",
        "western samoa",
        "st. vincent",
    }
)

_CORP_SUFFIXES = re.compile(
    r"\b(llc|ltd|limited|corp|corporation|inc|incorporated|"
    r"plc|gmbh|ag|bv|sa|sas|pty|nv|kk|as|ab|oy|"
    r"holding|holdings|trust|foundation|fund|lp|llp|"
    r"company|co\.)\b",
    re.IGNORECASE,
)

# Hard cap on company nodes to prevent runaway HTTP fan-out
_MAX_COMPANY_QUEUE_SIZE = 50


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class PersonRef:
    name: str
    source: str  # "opencorporates" | "companies_house" | "sec" | "db"
    position: str  # "director" | "officer" | "shareholder" etc.
    jurisdiction: str | None
    company_name: str
    start_date: str | None = None
    end_date: str | None = None
    person_id: str | None = None  # UUID string if persisted to DB
    confidence: float = 0.7


@dataclass
class CrawledCompanyData:
    company_name: str
    jurisdiction: str | None
    company_numbers: list[str]
    registered_addresses: list[str]
    status: str | None
    incorporation_date: str | None
    entity_type: str | None
    lei: str | None
    officers: list[PersonRef]
    sec_filings: list[dict]
    has_proxy_filing: bool
    data_sources: list[str]
    crawl_errors: list[str]


@dataclass
class UBOCandidate:
    name: str
    person_id: str | None
    chain: list[str]  # [root_company, ..., person_name]
    depth: int
    controlling_roles: list[str]
    jurisdictions: list[str]
    confidence: float
    is_natural_person: bool
    sanctions_hits: list[dict]
    risk_score: float


@dataclass
class UBOResult:
    root_company: str
    jurisdiction: str | None
    max_depth_used: int
    nodes: list[dict]
    edges: list[dict]
    ubo_candidates: list[UBOCandidate]
    risk_flags: list[str]
    crawl_errors: list[str]
    discovered_at: datetime
    partial: bool


# ── Engine ────────────────────────────────────────────────────────────────────


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


class UBODiscoveryEngine:
    """Recursive BFS UBO chain discovery engine."""

    def __init__(self) -> None:
        self._company_engine = CompanyIntelligenceEngine()

    # ── Public entry point ────────────────────────────────────────────────────

    async def discover(
        self,
        company_name: str,
        jurisdiction: str | None,
        max_depth: int,
        session: AsyncSession,
    ) -> UBOResult:
        """Run full BFS UBO chain discovery. Returns partial results on errors."""
        visited_companies: set[str] = {_normalise(company_name)}
        visited_persons: set[str] = set()

        # (company_name, jurisdiction, depth, chain_so_far)
        queue: deque[tuple[str, str | None, int, list[str]]] = deque(
            [(company_name, jurisdiction, 0, [company_name])]
        )

        company_nodes: dict[str, dict] = {}
        person_nodes: dict[str, dict] = {}
        edges: list[dict] = []
        crawled_data: list[CrawledCompanyData] = []
        chain_map: dict[str, list[str]] = {}  # person_id → ownership chain
        role_map: dict[str, list[str]] = {}  # person_id → list of positions
        jur_map: dict[str, list[str]] = {}  # person_id → jurisdictions
        all_crawl_errors: list[str] = []
        has_circular = False
        company_queue_count = 0
        partial = False

        while queue:
            company_name_cur, jur_cur, depth, chain = queue.popleft()
            norm = _normalise(company_name_cur)
            company_node_id = f"company:{uuid.uuid5(uuid.NAMESPACE_DNS, norm)}"

            if company_node_id not in company_nodes:
                company_nodes[company_node_id] = {
                    "id": company_node_id,
                    "type": "company",
                    "label": company_name_cur,
                    "depth": depth,
                    "risk_score": 0.0,
                    "jurisdiction": jur_cur,
                }

            if depth >= max_depth:
                continue

            # Cap total company crawls
            company_queue_count += 1
            if company_queue_count > _MAX_COMPANY_QUEUE_SIZE:
                partial = True
                logger.warning(
                    "UBO: queue cap (%d) hit for '%s'", _MAX_COMPANY_QUEUE_SIZE, company_name
                )
                continue

            crawled = await self._crawl_company(company_name_cur, jur_cur)
            crawled_data.append(crawled)
            all_crawl_errors.extend(crawled.crawl_errors)

            for officer in crawled.officers:
                if self._is_corporate_name(officer.name):
                    # Corporate nominee — recurse into it
                    sub_norm = _normalise(officer.name)
                    sub_node_id = f"company:{uuid.uuid5(uuid.NAMESPACE_DNS, sub_norm)}"
                    edges.append(
                        {
                            "source": company_node_id,
                            "target": sub_node_id,
                            "type": "subsidiary",
                            "confidence": officer.confidence,
                            "chain_position": depth,
                        }
                    )
                    if sub_norm in visited_companies:
                        has_circular = True
                        continue
                    visited_companies.add(sub_norm)
                    new_chain = chain + [officer.name]
                    queue.append((officer.name, officer.jurisdiction, depth + 1, new_chain))
                else:
                    # Natural person
                    person_id = await self._upsert_person(
                        officer.name, company_name_cur, officer.position, session
                    )
                    visited_persons.add(person_id)

                    if person_id not in person_nodes:
                        person_nodes[person_id] = {
                            "id": person_id,
                            "type": "person",
                            "label": officer.name,
                            "depth": depth + 1,
                            "risk_score": 0.0,
                        }

                    edges.append(
                        {
                            "source": company_node_id,
                            "target": person_id,
                            "type": officer.position or "officer",
                            "confidence": officer.confidence,
                            "chain_position": depth,
                        }
                    )
                    chain_map.setdefault(person_id, []).extend(chain + [officer.name])
                    role_map.setdefault(person_id, []).append(officer.position or "officer")
                    jur_map.setdefault(person_id, []).append(
                        officer.jurisdiction or jur_cur or "unknown"
                    )

        # ── Post-BFS: sanctions check ──────────────────────────────────────────
        sanctions_map: dict[str, list[dict]] = {}
        if visited_persons:
            sanctions_map = await self._check_sanctions(list(visited_persons), session)

        # Update person node risk scores
        for pid, hits in sanctions_map.items():
            if hits and pid in person_nodes:
                person_nodes[pid]["risk_score"] = 1.0

        # ── Identify UBOs ─────────────────────────────────────────────────────
        ubo_candidates = self._identify_ubos(
            person_nodes, edges, sanctions_map, chain_map, role_map, jur_map
        )

        # ── Risk flags ────────────────────────────────────────────────────────
        risk_flags = self._compute_risk_flags(crawled_data, ubo_candidates, has_circular)

        # ── Build node/edge lists ─────────────────────────────────────────────
        all_nodes = list(company_nodes.values()) + list(person_nodes.values())

        return UBOResult(
            root_company=company_name,
            jurisdiction=jurisdiction,
            max_depth_used=max_depth,
            nodes=all_nodes,
            edges=edges,
            ubo_candidates=ubo_candidates,
            risk_flags=risk_flags,
            crawl_errors=all_crawl_errors,
            discovered_at=datetime.now(UTC),
            partial=partial,
        )

    # ── Crawler layer ─────────────────────────────────────────────────────────

    async def crawl_company(
        self,
        name: str,
        jurisdiction: str | None,
    ) -> CrawledCompanyData:
        """Public alias so route handlers can call it directly."""
        return await self._crawl_company(name, jurisdiction)

    async def _crawl_company(
        self,
        name: str,
        jurisdiction: str | None,
    ) -> CrawledCompanyData:
        """Fan-out to all company crawlers concurrently. Never raises."""
        tasks = [self._run_single_crawler(p, name) for p in _COMPANY_CRAWLERS]
        tasks.append(self._run_single_crawler(_GLEIF_CRAWLER, name))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        oc_result = results[0] if not isinstance(results[0], BaseException) else None
        ch_result = results[1] if not isinstance(results[1], BaseException) else None
        sec_result = results[2] if not isinstance(results[2], BaseException) else None
        gleif_result = results[3] if not isinstance(results[3], BaseException) else None

        officers, data_sources, crawl_errors = self._merge_officers(
            oc_result, ch_result, sec_result, gleif_result, name
        )

        # Extract LEI from GLEIF
        lei: str | None = None
        if gleif_result and gleif_result.found:
            completions = gleif_result.data.get("completions", [])
            for c in completions:
                if _normalise(c.get("name", "")) == _normalise(name):
                    lei = c.get("lei")
                    break
            if not lei and completions:
                lei = completions[0].get("lei")

        # Extract SEC filings
        sec_filings: list[dict] = []
        has_proxy = False
        if sec_result and sec_result.found:
            sec_filings = sec_result.data.get("filings", [])
            has_proxy = any(
                f.get("form_type", "").upper() in ("DEF 14A", "DEF14A") for f in sec_filings
            )

        # Extract company metadata from OpenCorporates
        companies_list: list[dict] = []
        if oc_result and oc_result.found:
            companies_list = oc_result.data.get("companies", [])

        jurisdiction_found = jurisdiction
        addresses: list[str] = []
        company_numbers: list[str] = []
        status: str | None = None
        incorp_date: str | None = None
        entity_type: str | None = None

        for co in companies_list:
            if co.get("jurisdiction") and not jurisdiction_found:
                jurisdiction_found = co["jurisdiction"]
            if co.get("registered_address"):
                addresses.append(co["registered_address"])
            if co.get("company_number"):
                company_numbers.append(co["company_number"])
            if co.get("status") and not status:
                status = co["status"]
            if co.get("incorporation_date") and not incorp_date:
                incorp_date = co["incorporation_date"]
            if co.get("company_type") and not entity_type:
                entity_type = co["company_type"]

        return CrawledCompanyData(
            company_name=name,
            jurisdiction=jurisdiction_found,
            company_numbers=company_numbers,
            registered_addresses=addresses,
            status=status,
            incorporation_date=incorp_date,
            entity_type=entity_type,
            lei=lei,
            officers=officers,
            sec_filings=sec_filings,
            has_proxy_filing=has_proxy,
            data_sources=data_sources,
            crawl_errors=crawl_errors,
        )

    async def _run_single_crawler(self, platform: str, identifier: str) -> CrawlerResult | None:
        """Instantiate and run one crawler. Returns None on any failure."""
        try:
            crawler_cls = get_crawler(platform)
            if crawler_cls is None:
                return None
            crawler = crawler_cls()
            return await crawler.scrape(identifier)
        except Exception as exc:
            logger.debug("UBO: crawler %s failed: %s", platform, exc)
            return None

    def _merge_officers(
        self,
        oc_result: CrawlerResult | None,
        ch_result: CrawlerResult | None,
        sec_result: CrawlerResult | None,
        gleif_result: CrawlerResult | None,
        company_name: str,
    ) -> tuple[list[PersonRef], list[str], list[str]]:
        """Merge officer lists; deduplicate by normalised name."""
        seen: dict[str, PersonRef] = {}
        data_sources: list[str] = []
        crawl_errors: list[str] = []

        source_map: list[tuple[CrawlerResult | None, str, float]] = [
            (oc_result, "opencorporates", 0.85),
            (ch_result, "companies_house", 0.90),
            (sec_result, "sec", 0.88),
        ]

        for result, source_name, reliability in source_map:
            if result is None:
                crawl_errors.append(f"{source_name}:no_response")
                continue
            if result.error:
                crawl_errors.append(f"{source_name}:{result.error}")
                continue
            if not result.found:
                continue

            data_sources.append(source_name)
            officers_raw: list[dict] = result.data.get("officers", [])
            for o in officers_raw:
                name = (o.get("name") or "").strip()
                if not name:
                    continue
                norm_key = re.sub(r"[^a-z0-9 ]", "", name.lower().strip())
                if norm_key in seen:
                    # Keep higher-confidence source
                    if reliability > seen[norm_key].confidence:
                        seen[norm_key] = PersonRef(
                            name=name,
                            source=source_name,
                            position=o.get("position")
                            or o.get("appointment_count")
                            and "director"
                            or "officer",
                            jurisdiction=o.get("jurisdiction")
                            or o.get("company_url", "").split("/")[4]
                            if o.get("company_url")
                            else None,
                            company_name=o.get("company_name") or company_name,
                            start_date=o.get("start_date"),
                            end_date=o.get("end_date"),
                            confidence=reliability,
                        )
                else:
                    seen[norm_key] = PersonRef(
                        name=name,
                        source=source_name,
                        position=o.get("position") or "officer",
                        jurisdiction=o.get("jurisdiction"),
                        company_name=o.get("company_name") or company_name,
                        start_date=o.get("start_date"),
                        end_date=o.get("end_date"),
                        confidence=reliability,
                    )

        if gleif_result is None:
            crawl_errors.append("gleif:no_response")
        elif gleif_result.error:
            crawl_errors.append(f"gleif:{gleif_result.error}")
        elif gleif_result.found:
            data_sources.append("gleif")

        return list(seen.values()), data_sources, crawl_errors

    # ── Utility helpers ───────────────────────────────────────────────────────

    def _is_corporate_name(self, name: str) -> bool:
        """Return True if name looks like a company rather than a natural person."""
        return bool(_CORP_SUFFIXES.search(name))

    # ── DB layer ──────────────────────────────────────────────────────────────

    async def _upsert_person(
        self,
        name: str,
        company_name: str,
        position: str,
        session: AsyncSession,
    ) -> str:
        """Look up or create a Person. Upsert EmploymentHistory. Returns UUID str."""
        norm_name = name.strip()

        stmt = select(Person).where(func.lower(Person.full_name) == norm_name.lower()).limit(1)
        result = await session.execute(stmt)
        person = result.scalar_one_or_none()

        if not person:
            person = Person(full_name=norm_name, meta={"source": "ubo_discovery"})
            session.add(person)
            await session.flush()

        # Upsert EmploymentHistory
        emp_stmt = (
            select(EmploymentHistory)
            .where(
                EmploymentHistory.person_id == person.id,
                func.lower(EmploymentHistory.employer_name) == company_name.lower().strip(),
            )
            .limit(1)
        )
        emp_result = await session.execute(emp_stmt)
        existing_emp = emp_result.scalar_one_or_none()

        if not existing_emp:
            session.add(
                EmploymentHistory(
                    person_id=person.id,
                    employer_name=company_name.strip(),
                    job_title=position,
                    is_current=True,
                    meta={"source": "ubo_discovery"},
                )
            )
            await session.flush()

        return str(person.id)

    async def _check_sanctions(
        self,
        person_ids: list[str],
        session: AsyncSession,
    ) -> dict[str, list[dict]]:
        """Batch query WatchlistMatch for a list of person UUIDs."""
        if not person_ids:
            return {}

        pid_uuids = [uuid.UUID(p) for p in person_ids]
        stmt = select(WatchlistMatch).where(WatchlistMatch.person_id.in_(pid_uuids))
        result = await session.execute(stmt)
        rows = result.scalars().all()

        out: dict[str, list[dict]] = {p: [] for p in person_ids}
        for row in rows:
            pid_str = str(row.person_id)
            if pid_str in out:
                out[pid_str].append(
                    {
                        "list_type": row.list_type,
                        "match_name": row.match_name,
                        "confidence": row.confidence,
                    }
                )
        return out

    # ── UBO identification ────────────────────────────────────────────────────

    def _identify_ubos(
        self,
        person_nodes: dict[str, dict],
        edges: list[dict],
        sanctions_map: dict[str, list[dict]],
        chain_map: dict[str, list[str]],
        role_map: dict[str, list[str]],
        jur_map: dict[str, list[str]],
    ) -> list[UBOCandidate]:
        candidates: list[UBOCandidate] = []

        for person_id, node in person_nodes.items():
            chain = chain_map.get(person_id, [])
            roles = list(dict.fromkeys(role_map.get(person_id, ["officer"])))
            jurisdictions = list(dict.fromkeys(jur_map.get(person_id, ["unknown"])))
            hits = sanctions_map.get(person_id, [])

            # Confidence derived from depth: deeper chains are less certain
            depth = node.get("depth", 1)
            base_conf = max(0.3, 1.0 - (depth - 1) * 0.15)
            risk = 1.0 if hits else 0.0

            candidates.append(
                UBOCandidate(
                    name=node["label"],
                    person_id=person_id,
                    chain=chain,
                    depth=depth,
                    controlling_roles=roles,
                    jurisdictions=jurisdictions,
                    confidence=round(base_conf, 2),
                    is_natural_person=True,
                    sanctions_hits=hits,
                    risk_score=risk,
                )
            )

        candidates.sort(key=lambda c: c.depth)
        return candidates

    def _compute_risk_flags(
        self,
        crawled_companies: list[CrawledCompanyData],
        ubo_candidates: list[UBOCandidate],
        has_circular: bool,
    ) -> list[str]:
        flags: list[str] = []

        # Shell company chain: deep chain with no UBOs identified
        if not ubo_candidates and len(crawled_companies) > 2:
            flags.append("shell_company_chain")

        # Offshore jurisdiction
        for cd in crawled_companies:
            jur = (cd.jurisdiction or "").lower()
            if jur in _OFFSHORE_JURISDICTIONS:
                flags.append("offshore_jurisdiction")
                break

        if has_circular:
            flags.append("circular_ownership")

        # Sanctions hit on any UBO
        if any(c.sanctions_hits for c in ubo_candidates):
            flags.append("person_on_sanctions_list")

        return list(dict.fromkeys(flags))
