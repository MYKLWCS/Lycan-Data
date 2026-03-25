# Family Tree Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build automated family tree construction with 8-generation ancestor tracing, unlimited descendant expansion, source confidence scoring, D3 hierarchical view, and GEDCOM export

**Architecture:** GenealogyEnricher asyncio daemon runs BFS over genealogy crawlers, stores relationships in existing Relationship table with family rel_types, caches assembled tree in FamilyTreeSnapshot. Frontend renders D3 tree layout.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, D3.js v7 tree layout, GEDCOM 5.5.5

---

## File Map

**New files:**
- `shared/models/family_tree.py` — FamilyTreeSnapshot SQLAlchemy model
- `migrations/versions/c4d5e6f7a8b9_add_family_tree_snapshots.py` — Alembic migration
- `modules/crawlers/genealogy/__init__.py` — package init
- `modules/crawlers/genealogy/ancestry_hints.py` — Ancestry public hints crawler
- `modules/crawlers/genealogy/census_records.py` — US Census via FamilySearch crawler
- `modules/crawlers/genealogy/vitals_records.py` — State vital records crawler
- `modules/crawlers/genealogy/newspapers_archive.py` — Chronicling America / LOC crawler
- `modules/crawlers/genealogy/geni_public.py` — Geni.com public profiles crawler
- `modules/enrichers/genealogy_enricher.py` — GenealogyEnricher daemon + BFS build_tree()
- `tests/test_enrichers/test_genealogy_enricher.py` — BFS algorithm + confidence scoring tests
- `tests/test_crawlers/test_genealogy_crawlers.py` — crawler mock tests

**Modified files:**
- `api/routes/persons.py` — add 4 family tree endpoints
- `worker.py` — add `--no-genealogy` flag and register GenealogyEnricher daemon
- `static/index.html` — add D3 CDN import, route `#/persons/<id>/tree`, `renderFamilyTree()` method

---

## Task 1: FamilyTreeSnapshot Model + Alembic Migration

**Files:**
- Create: `shared/models/family_tree.py`
- Create: `migrations/versions/c4d5e6f7a8b9_add_family_tree_snapshots.py`

- [ ] **Step 1: Write the SQLAlchemy model**

Create `shared/models/family_tree.py`:
```python
"""
family_tree.py — FamilyTreeSnapshot model.

Caches fully-assembled family trees so the API can serve them without
re-running BFS on every request. Set is_stale=True to trigger a rebuild
on next GET /persons/{id}/family-tree.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class FamilyTreeSnapshot(Base, TimestampMixin):
    __tablename__ = "family_tree_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tree_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    depth_ancestors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    depth_descendants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Write the Alembic migration**

Create `migrations/versions/c4d5e6f7a8b9_add_family_tree_snapshots.py`:
```python
"""Add family_tree_snapshots table

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS_COLS = [
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
]


def upgrade() -> None:
    op.create_table(
        "family_tree_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("root_person_id", sa.UUID(), nullable=False),
        sa.Column(
            "tree_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("depth_ancestors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("depth_descendants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default="false"),
        *_TS_COLS,
        sa.ForeignKeyConstraint(["root_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_tree_snapshots_root_person_id",
        "family_tree_snapshots",
        ["root_person_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_family_tree_snapshots_root_person_id", table_name="family_tree_snapshots")
    op.drop_table("family_tree_snapshots")
```

- [ ] **Step 3: Import model in shared/models/__init__.py** (or wherever the project auto-imports models for Alembic target_metadata). Verify that `migrations/env.py` picks up all models via the existing `Base.metadata` target — no env.py edit needed if it already imports `shared.models.*`.

---

## Task 2: Genealogy Crawlers — ancestry_hints + census_records + package init

**Files:**
- Create: `modules/crawlers/genealogy/__init__.py`
- Create: `modules/crawlers/genealogy/ancestry_hints.py`
- Create: `modules/crawlers/genealogy/census_records.py`

**Note:** `modules/crawlers/people_familysearch.py` and `modules/crawlers/people_findagrave.py` already exist. The genealogy crawlers below are NEW sources in a NEW sub-package — they are not replacements.

- [ ] **Step 1: Create package init**

Create `modules/crawlers/genealogy/__init__.py`:
```python
"""
Genealogy crawler sub-package.

All crawlers in this package emit CrawlerResult.data conforming to the
standard genealogy schema:

    {
        "person_name": str,
        "birth_date": str | None,
        "birth_place": str | None,
        "death_date": str | None,
        "death_place": str | None,
        "parents":  [{"name": str, "birth_year": int | None}],
        "children": [{"name": str, "birth_year": int | None}],
        "spouses":  [{"name": str, "marriage_date": str | None}],
        "siblings": [{"name": str, "birth_year": int | None}],
        "source_url": str,
        "record_type": str,  # birth_cert | census | obituary | memorial | tree
    }
"""
```

- [ ] **Step 2: ancestry_hints.py**

Create `modules/crawlers/genealogy/ancestry_hints.py`:
```python
"""
ancestry_hints.py — Ancestry.com public tree hints (no auth required).

Queries Ancestry's public search endpoint for suggested relatives from
public user-submitted family trees. No Ancestry account is needed.

Source: https://www.ancestry.com/search/
Registered as "genealogy_ancestry_hints".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://www.ancestry.com/search/collections/pubmembertrees/"
    "?name={name}&birth={birth_year}&count=10"
)

_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_relative(raw: dict) -> dict:
    return {
        "name": raw.get("displayName") or raw.get("name", ""),
        "birth_year": raw.get("birthYear") or raw.get("birth_year"),
    }


@register("genealogy_ancestry_hints")
class AncestryHintsCrawler(HttpxCrawler):
    """Fetch suggested relatives from Ancestry public member trees."""

    platform = "genealogy_ancestry_hints"
    source_reliability = 0.55  # public user trees — helpful but unverified

    async def crawl(self, identifier: str) -> CrawlerResult:
        """
        identifier: "Full Name" or "Full Name YYYY"
        """
        parts = identifier.rsplit(" ", 1)
        name = parts[0]
        birth_year = parts[1] if len(parts) == 2 and parts[1].isdigit() else ""

        url = _SEARCH_URL.format(
            name=quote_plus(name),
            birth_year=birth_year,
        )

        try:
            resp = await self._get(url, headers=_HEADERS)
            data = resp.json() if callable(getattr(resp, "json", None)) else {}
        except Exception as exc:
            logger.debug("ancestry_hints fetch failed for %s: %s", identifier, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        results = data.get("results") or data.get("persons") or []
        if not results:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                source_reliability=self.source_reliability,
            )

        top = results[0]
        relatives_raw = top.get("relatives") or {}

        genealogy_data = {
            "person_name": top.get("displayName") or name,
            "birth_date": top.get("birthDate"),
            "birth_place": top.get("birthPlace"),
            "death_date": top.get("deathDate"),
            "death_place": top.get("deathPlace"),
            "parents": [_parse_relative(r) for r in relatives_raw.get("parents", [])],
            "children": [_parse_relative(r) for r in relatives_raw.get("children", [])],
            "spouses": [
                {"name": r.get("displayName", ""), "marriage_date": r.get("marriageDate")}
                for r in relatives_raw.get("spouses", [])
            ],
            "siblings": [_parse_relative(r) for r in relatives_raw.get("siblings", [])],
            "source_url": url,
            "record_type": "tree",
        }

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=genealogy_data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )
```

- [ ] **Step 3: census_records.py**

Create `modules/crawlers/genealogy/census_records.py`:
```python
"""
census_records.py — US Census records via FamilySearch Platform API.

Retrieves household members from US Census records 1790-1940 using
FamilySearch's historical records search. Household members become
candidate relatives (parents, children, siblings living in same home).

NOTE: people_familysearch.py already exists at modules/crawlers/ and
handles living tree search. This crawler specifically targets census
collection records for household data.

Source: https://api.familysearch.org/platform/records/search
Registered as "genealogy_census_records".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings

logger = logging.getLogger(__name__)

# FamilySearch census collection IDs (1790-1940)
_CENSUS_COLLECTIONS = [
    "2116904",  # 1940 US Census
    "1417683",  # 1930 US Census
    "1311715",  # 1920 US Census
    "1727033",  # 1910 US Census
    "1417568",  # 1900 US Census
    "1417660",  # 1880 US Census
    "1438024",  # 1870 US Census
    "1438720",  # 1860 US Census
    "1473181",  # 1850 US Census
]

_RECORDS_URL = (
    "https://api.familysearch.org/platform/records/search"
    "?q.givenName={first}&q.surname={last}&q.birthLikeYear={year}"
    "&f.collectionId={collection}&count=5"
)
_FS_ACCEPT = "application/x-fs-v1+json"


def _fs_headers(token: str | None) -> dict:
    h = {
        "Accept": _FS_ACCEPT,
        "User-Agent": "LycanOSINT/1.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _extract_household(entry: dict) -> tuple[str, list[dict], str | None, str | None]:
    """Return (full_name, household_members, birth_date, birth_place) from a census entry."""
    gedcomx = entry.get("content", {}).get("gedcomx", {})
    persons = gedcomx.get("persons", [])
    relationships = gedcomx.get("relationships", [])

    primary = persons[0] if persons else {}

    # Extract primary person name
    full_name = ""
    for nf in (primary.get("names") or [{}])[0].get("nameForms", []):
        full_name = nf.get("fullText", "")
        if full_name:
            break

    # Extract birth facts
    birth_date = birth_place = None
    for fact in primary.get("facts", []):
        if fact.get("type", "").endswith("Birth"):
            birth_date = (fact.get("date") or {}).get("original")
            birth_place = (fact.get("place") or {}).get("original")
            break

    # Build id→name map for household
    id_to_name: dict[str, str] = {}
    for p in persons:
        pid = p.get("id", "")
        for nf in (p.get("names") or [{}])[0].get("nameForms", []):
            nm = nf.get("fullText", "")
            if nm:
                id_to_name[pid] = nm
                break

    # Map relationships to relative dicts
    household: list[dict] = []
    for rel in relationships:
        rtype = rel.get("type", "")
        p1 = (rel.get("person1") or {}).get("resourceId", "")
        p2 = (rel.get("person2") or {}).get("resourceId", "")
        other_id = p2 if p1 == primary.get("id") else p1
        other_name = id_to_name.get(other_id, "")
        if other_name:
            household.append({"name": other_name, "rel_hint": rtype, "birth_year": None})

    return full_name, household, birth_date, birth_place


@register("genealogy_census_records")
class CensusRecordsCrawler(HttpxCrawler):
    """Fetch US Census household records via FamilySearch."""

    platform = "genealogy_census_records"
    source_reliability = 0.80  # government census — high authority

    async def crawl(self, identifier: str) -> CrawlerResult:
        """
        identifier: "First Last" or "First Last YYYY"
        """
        parts = identifier.rsplit(" ", 1)
        full_name = parts[0]
        year = parts[1] if len(parts) == 2 and parts[1].isdigit() else "1900"

        name_parts = full_name.split(" ", 1)
        first = name_parts[0]
        last = name_parts[1] if len(name_parts) > 1 else ""

        token = getattr(settings, "familysearch_api_key", None)
        headers = _fs_headers(token)

        all_parents: list[dict] = []
        all_children: list[dict] = []
        all_siblings: list[dict] = []
        found_name = full_name
        found_birth_date = None
        found_birth_place = None
        source_url = ""

        for collection_id in _CENSUS_COLLECTIONS[:3]:  # top 3 most recent censuses
            url = _RECORDS_URL.format(
                first=quote_plus(first),
                last=quote_plus(last),
                year=year,
                collection=collection_id,
            )
            try:
                resp = await self._get(url, headers=headers)
                data = resp.json()
            except Exception as exc:
                logger.debug("census fetch failed (collection %s): %s", collection_id, exc)
                continue

            entries = (data.get("entries") or [])
            if not entries:
                continue

            name_out, household, bd, bp = _extract_household(entries[0])
            if name_out:
                found_name = name_out
            if bd and not found_birth_date:
                found_birth_date = bd
            if bp and not found_birth_place:
                found_birth_place = bp
            source_url = url

            # Household members classified loosely — enricher resolves exact rel_type
            for h in household:
                hint = h.get("rel_hint", "")
                entry_dict = {"name": h["name"], "birth_year": h["birth_year"]}
                if "Parent" in hint or "parent" in hint:
                    all_parents.append(entry_dict)
                elif "Child" in hint or "child" in hint:
                    all_children.append(entry_dict)
                else:
                    all_siblings.append(entry_dict)
            break  # stop at first collection that returns data

        if not source_url:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                source_reliability=self.source_reliability,
            )

        genealogy_data = {
            "person_name": found_name,
            "birth_date": found_birth_date,
            "birth_place": found_birth_place,
            "death_date": None,
            "death_place": None,
            "parents": all_parents,
            "children": all_children,
            "spouses": [],
            "siblings": all_siblings,
            "source_url": source_url,
            "record_type": "census",
        }

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=genealogy_data,
            profile_url=source_url,
            source_reliability=self.source_reliability,
        )
```

---

## Task 3: Genealogy Crawlers — vitals_records, newspapers_archive, geni_public

**Files:**
- Create: `modules/crawlers/genealogy/vitals_records.py`
- Create: `modules/crawlers/genealogy/newspapers_archive.py`
- Create: `modules/crawlers/genealogy/geni_public.py`

- [ ] **Step 1: vitals_records.py**

Create `modules/crawlers/genealogy/vitals_records.py`:
```python
"""
vitals_records.py — State vital records via public APIs.

Queries publicly accessible state vital record indices where available.
In practice most states have moved vital records behind paid portals;
this crawler targets the states that publish free searchable indices
(currently: California Death Index, Texas Death Records, Social Security
Death Index via FamilySearch).

Registered as "genealogy_vitals_records".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings

logger = logging.getLogger(__name__)

# FamilySearch SSDI collection
_SSDI_URL = (
    "https://api.familysearch.org/platform/records/search"
    "?q.givenName={first}&q.surname={last}"
    "&f.collectionId=1202535&count=5"
)
# California Death Index 1940-1997
_CADI_URL = (
    "https://api.familysearch.org/platform/records/search"
    "?q.givenName={first}&q.surname={last}"
    "&f.collectionId=1302231&count=5"
)

_FS_ACCEPT = "application/x-fs-v1+json"


def _fs_headers(token: str | None) -> dict:
    h = {"Accept": _FS_ACCEPT, "User-Agent": "LycanOSINT/1.0"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_vital_entry(entry: dict) -> dict:
    gedcomx = entry.get("content", {}).get("gedcomx", {})
    persons = gedcomx.get("persons", [])
    p = persons[0] if persons else {}

    full_name = ""
    for nf in (p.get("names") or [{}])[0].get("nameForms", []):
        full_name = nf.get("fullText", "")
        if full_name:
            break

    birth_date = birth_place = death_date = death_place = None
    for fact in p.get("facts", []):
        ftype = fact.get("type", "")
        if "Birth" in ftype:
            birth_date = (fact.get("date") or {}).get("original")
            birth_place = (fact.get("place") or {}).get("original")
        elif "Death" in ftype:
            death_date = (fact.get("date") or {}).get("original")
            death_place = (fact.get("place") or {}).get("original")

    # Vitals records rarely include relatives directly; parents sometimes appear
    relationships = gedcomx.get("relationships", [])
    persons_map = {p2.get("id", ""): p2 for p2 in persons}
    parents: list[dict] = []
    for rel in relationships:
        rtype = rel.get("type", "")
        if "ParentChild" in rtype:
            parent_ref = (rel.get("person1") or {}).get("resourceId", "")
            parent_obj = persons_map.get(parent_ref)
            if parent_obj and parent_obj.get("id") != p.get("id"):
                parent_name = ""
                for nf in (parent_obj.get("names") or [{}])[0].get("nameForms", []):
                    parent_name = nf.get("fullText", "")
                    if parent_name:
                        break
                if parent_name:
                    parents.append({"name": parent_name, "birth_year": None})

    return {
        "person_name": full_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "death_date": death_date,
        "death_place": death_place,
        "parents": parents,
        "children": [],
        "spouses": [],
        "siblings": [],
    }


@register("genealogy_vitals_records")
class VitalsRecordsCrawler(HttpxCrawler):
    """Fetch public vital records (SSDI, California Death Index) via FamilySearch."""

    platform = "genealogy_vitals_records"
    source_reliability = 0.85  # government vital records — very high authority

    async def crawl(self, identifier: str) -> CrawlerResult:
        parts = identifier.rsplit(" ", 1)
        full_name = parts[0]
        name_parts = full_name.split(" ", 1)
        first = name_parts[0]
        last = name_parts[1] if len(name_parts) > 1 else ""

        token = getattr(settings, "familysearch_api_key", None)
        headers = _fs_headers(token)

        for url_tpl, record_type in [(_SSDI_URL, "death_cert"), (_CADI_URL, "death_cert")]:
            url = url_tpl.format(first=quote_plus(first), last=quote_plus(last))
            try:
                resp = await self._get(url, headers=headers)
                data = resp.json()
            except Exception as exc:
                logger.debug("vitals_records fetch error: %s", exc)
                continue

            entries = data.get("entries") or []
            if not entries:
                continue

            parsed = _parse_vital_entry(entries[0])
            parsed["source_url"] = url
            parsed["record_type"] = record_type

            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=True,
                data=parsed,
                profile_url=url,
                source_reliability=self.source_reliability,
            )

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=False,
            source_reliability=self.source_reliability,
        )
```

- [ ] **Step 2: newspapers_archive.py**

Create `modules/crawlers/genealogy/newspapers_archive.py`:
```python
"""
newspapers_archive.py — Birth/marriage/death announcements via Chronicling America.

Queries the Library of Congress Chronicling America newspaper archive for
birth announcements, marriage notices, and obituaries. Returns structured
relative data extracted from matched articles.

Source: https://chroniclingamerica.loc.gov/
Registered as "genealogy_newspapers_archive".
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://chroniclingamerica.loc.gov/search/pages/results/"
    "?andtext={query}&format=json&rows=5"
)

# Simple regex patterns for extracting relatives from newspaper text
_SURVIVED_BY = re.compile(
    r"survived\s+by\s+(?:his|her|their)?\s*(?:wife|husband|spouse|son|daughter|child|children|parent|mother|father|brother|sister)[,\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
    re.IGNORECASE,
)
_MARRIED_TO = re.compile(
    r"married\s+(?:to\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
    re.IGNORECASE,
)
_PARENTS_OF = re.compile(
    r"(?:son|daughter)\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s+(?:and\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}))?",
    re.IGNORECASE,
)


def _extract_relatives(text: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (parents, spouses, siblings) extracted from raw article text."""
    parents: list[dict] = []
    spouses: list[dict] = []
    siblings: list[dict] = []

    for m in _PARENTS_OF.finditer(text):
        parents.append({"name": m.group(1).strip(), "birth_year": None})
        if m.group(2):
            parents.append({"name": m.group(2).strip(), "birth_year": None})

    for m in _MARRIED_TO.finditer(text):
        spouses.append({"name": m.group(1).strip(), "marriage_date": None})

    return parents, spouses, siblings


@register("genealogy_newspapers_archive")
class NewspapersArchiveCrawler(HttpxCrawler):
    """Search Chronicling America for genealogical announcements."""

    platform = "genealogy_newspapers_archive"
    source_reliability = 0.65  # historical newspapers — useful corroboration

    async def crawl(self, identifier: str) -> CrawlerResult:
        parts = identifier.rsplit(" ", 1)
        full_name = parts[0]

        query = quote_plus(f'"{full_name}" (born OR married OR died OR obituary)')
        url = _SEARCH_URL.format(query=query)

        try:
            resp = await self._get(url)
            data = resp.json()
        except Exception as exc:
            logger.debug("newspapers_archive fetch failed for %s: %s", identifier, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        items = data.get("items") or []
        if not items:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                source_reliability=self.source_reliability,
            )

        # Aggregate relative mentions across all returned articles
        all_parents: list[dict] = []
        all_spouses: list[dict] = []
        all_siblings: list[dict] = []

        best_date: str | None = None
        best_place: str | None = None

        for item in items:
            text = item.get("ocr_eng") or item.get("title") or ""
            parents, spouses, siblings = _extract_relatives(text)
            all_parents.extend(parents)
            all_spouses.extend(spouses)
            all_siblings.extend(siblings)

            if not best_date:
                best_date = item.get("date")
            if not best_place:
                best_place = item.get("place_of_publication")

        # Deduplicate by name
        def _dedup_by_name(lst: list[dict]) -> list[dict]:
            seen: set[str] = set()
            out: list[dict] = []
            for item2 in lst:
                k = item2.get("name", "").lower()
                if k and k not in seen:
                    seen.add(k)
                    out.append(item2)
            return out

        record_type = "obituary"  # most genealogical newspaper hits are obits
        genealogy_data = {
            "person_name": full_name,
            "birth_date": None,
            "birth_place": None,
            "death_date": best_date,
            "death_place": best_place,
            "parents": _dedup_by_name(all_parents),
            "children": [],
            "spouses": _dedup_by_name(all_spouses),
            "siblings": _dedup_by_name(all_siblings),
            "source_url": url,
            "record_type": record_type,
        }

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=genealogy_data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )
```

- [ ] **Step 3: geni_public.py**

Create `modules/crawlers/genealogy/geni_public.py`:
```python
"""
geni_public.py — Geni.com public profile family tree data.

Queries the Geni public API for profile data and direct family connections.
Only public profiles are accessible without auth.

Source: https://www.geni.com/api/
Registered as "genealogy_geni_public".
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.geni.com/search/results?search_type=people&names={name}&per_page=5"
_PROFILE_URL = "https://www.geni.com/api/profile/{profile_id}?fields=id,name,first_name,last_name,birth,death,unions,parents&only_data=1"
_UNION_URL = "https://www.geni.com/api/union/{union_id}?fields=id,partners,children&only_data=1"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}


def _extract_year(date_obj: dict | None) -> int | None:
    if not date_obj:
        return None
    raw = date_obj.get("year") or date_obj.get("date", {}).get("year")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


@register("genealogy_geni_public")
class GeniPublicCrawler(HttpxCrawler):
    """Fetch family tree data from Geni.com public profiles."""

    platform = "genealogy_geni_public"
    source_reliability = 0.60  # crowd-sourced family tree — moderate reliability

    async def crawl(self, identifier: str) -> CrawlerResult:
        parts = identifier.rsplit(" ", 1)
        full_name = parts[0]

        # Step 1: search for profile
        search_url = _SEARCH_URL.format(name=quote_plus(full_name))
        try:
            resp = await self._get(search_url, headers=_HEADERS)
            search_data = resp.json()
        except Exception as exc:
            logger.debug("geni_public search failed for %s: %s", identifier, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        results = search_data.get("results") or []
        if not results:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                source_reliability=self.source_reliability,
            )

        top = results[0]
        profile_id = top.get("id") or top.get("profile_id", "")
        if not profile_id:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                source_reliability=self.source_reliability,
            )

        # Step 2: fetch full profile
        profile_url = _PROFILE_URL.format(profile_id=profile_id)
        try:
            resp2 = await self._get(profile_url, headers=_HEADERS)
            profile = resp2.json()
        except Exception as exc:
            logger.debug("geni_public profile fetch failed for %s: %s", profile_id, exc)
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        birth = profile.get("birth") or {}
        death = profile.get("death") or {}

        # Parents
        parents_raw = profile.get("parents") or {}
        parents = [
            {"name": p.get("name", ""), "birth_year": _extract_year(p.get("birth"))}
            for p in parents_raw.values()
            if p.get("name")
        ]

        # Spouses + children from unions
        spouses: list[dict] = []
        children: list[dict] = []
        for union_id in (profile.get("unions") or []):
            union_url = _UNION_URL.format(union_id=union_id)
            try:
                resp3 = await self._get(union_url, headers=_HEADERS)
                union = resp3.json()
            except Exception:
                continue

            for partner in (union.get("partners") or {}).values():
                if partner.get("id") != profile_id and partner.get("name"):
                    spouses.append({"name": partner["name"], "marriage_date": None})

            for child in (union.get("children") or {}).values():
                if child.get("name"):
                    children.append(
                        {"name": child["name"], "birth_year": _extract_year(child.get("birth"))}
                    )

        genealogy_data = {
            "person_name": profile.get("name") or full_name,
            "birth_date": birth.get("date", {}).get("year"),
            "birth_place": (birth.get("place") or {}).get("name"),
            "death_date": death.get("date", {}).get("year"),
            "death_place": (death.get("place") or {}).get("name"),
            "parents": parents,
            "children": children,
            "spouses": spouses,
            "siblings": [],
            "source_url": f"https://www.geni.com/people/{profile_id}",
            "record_type": "tree",
        }

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=genealogy_data,
            profile_url=f"https://www.geni.com/people/{profile_id}",
            source_reliability=self.source_reliability,
        )
```

---

## Task 4: GenealogyEnricher — _parse_relatives() + Confidence Scoring

**File:** `modules/enrichers/genealogy_enricher.py` (partial — foundation layer)

- [ ] **Step 1: Create file with confidence scoring and _parse_relatives()**

Create `modules/enrichers/genealogy_enricher.py` with this initial skeleton:
```python
"""
genealogy_enricher.py — GenealogyEnricher asyncio daemon.

Builds family trees by running BFS over genealogy crawlers, storing results
in the existing Relationship table (new rel_type values) and caching the
assembled tree in FamilyTreeSnapshot.

Daemon wakes every 5 minutes and processes up to 10 persons with
meta["needs_genealogy"] == True.

New rel_type values introduced here:
    parent_of, child_of, sibling_of, spouse_of,
    grandparent_of, grandchild_of, aunt_uncle_of, niece_nephew_of,
    half_sibling_of, step_parent_of, step_child_of
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import async_session_factory
from shared.models.family_tree import FamilyTreeSnapshot
from shared.models.person import Person
from shared.models.relationship import Relationship

logger = logging.getLogger(__name__)

# ── Confidence scoring constants ──────────────────────────────────────────────
_BASE_SCORES = {1: 0.40, 2: 0.72}
_BASE_SCORE_3PLUS = 0.92
_GOV_BONUS = 0.15
_GOV_RECORD_TYPES = {"birth_cert", "death_cert", "census"}
_CONFLICT_MULTIPLIER = 0.60

# ── Crawler identifier to source_reliability weights ──────────────────────────
_SOURCE_RELIABILITY: dict[str, float] = {
    "genealogy_vitals_records": 0.85,
    "genealogy_census_records": 0.80,
    "genealogy_newspapers_archive": 0.65,
    "genealogy_geni_public": 0.60,
    "genealogy_ancestry_hints": 0.55,
    "people_familysearch": 0.75,
    "people_findagrave": 0.65,
}

# Map from genealogy schema keys to rel_type values (person_a → person_b direction)
_RELATIVES_TO_REL_TYPE: dict[str, str] = {
    "parents": "child_of",    # seed is child_of the parent
    "children": "parent_of",  # seed is parent_of the child
    "spouses": "spouse_of",
    "siblings": "sibling_of",
}

# ── Relative canonical form ────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name.lower())).strip()


def compute_confidence(
    source_names: list[str],
    record_types: list[str],
    conflicting: bool = False,
) -> float:
    """
    Compute confidence score for a relationship claim.

    Rules:
    - 1 source                 → 0.40
    - 2 independent sources    → 0.72
    - 3+ sources               → 0.92
    - Any government record    → +0.15 bonus, capped at 1.0
    - Conflicting sources      → max(source_scores) × 0.60

    Args:
        source_names: list of source platform names that corroborate
        record_types: list of record_type values from each source
        conflicting:  True if sources disagree on this relative's identity
    """
    n = len(source_names)
    if n == 0:
        return 0.0

    if n == 1:
        base = _BASE_SCORES[1]
    elif n == 2:
        base = _BASE_SCORES[2]
    else:
        base = _BASE_SCORE_3PLUS

    has_gov = any(rt in _GOV_RECORD_TYPES for rt in record_types)
    if has_gov:
        base = min(1.0, base + _GOV_BONUS)

    if conflicting:
        base = base * _CONFLICT_MULTIPLIER

    return round(base, 4)


def _parse_relatives(
    crawler_results: list[Any],
    seed_person_id: uuid.UUID,
) -> list[dict]:
    """
    Cross-reference genealogy crawler results to produce a deduplicated
    list of relative dicts with confidence scores.

    Each input CrawlerResult.data follows the standard genealogy schema.

    Returns a list of:
    {
        "name": str,
        "birth_year": int | None,
        "rel_type": str,       # child_of / parent_of / spouse_of / sibling_of
        "confidence": float,
        "sources": list[str],  # platform names that agreed
        "record_types": list[str],
        "meta": dict,          # marriage_date, birth_record_url, etc.
        "conflict_flag": bool,
    }
    """
    # Accumulate sightings keyed by (normalised_name, rel_type)
    sightings: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for result in crawler_results:
        if not result.found:
            continue
        data = result.data
        record_type = data.get("record_type", "unknown")

        for rel_key, rel_type in _RELATIVES_TO_REL_TYPE.items():
            for relative in data.get(rel_key, []):
                name = relative.get("name") or ""
                if not name.strip():
                    continue
                norm_key = (_normalise_name(name), rel_type)
                sightings[norm_key].append({
                    "raw_name": name,
                    "birth_year": relative.get("birth_year"),
                    "marriage_date": relative.get("marriage_date"),
                    "source": result.platform,
                    "record_type": record_type,
                    "source_url": data.get("source_url"),
                })

    relatives: list[dict] = []
    for (norm_name, rel_type), sight_list in sightings.items():
        sources = [s["source"] for s in sight_list]
        record_types = [s["record_type"] for s in sight_list]

        # Conflict detection: same normalised name from same rel_type but inconsistent birth years
        birth_years = {s["birth_year"] for s in sight_list if s["birth_year"]}
        conflicting = len(birth_years) > 1

        confidence = compute_confidence(sources, record_types, conflicting)

        # Pick most common raw name
        from collections import Counter
        raw_name = Counter(s["raw_name"] for s in sight_list).most_common(1)[0][0]

        # Build meta
        meta: dict[str, Any] = {
            "sources": sources,
        }
        marriage_dates = [s["marriage_date"] for s in sight_list if s.get("marriage_date")]
        if marriage_dates:
            meta["marriage_date"] = marriage_dates[0]
        record_urls = [s["source_url"] for s in sight_list if s.get("source_url")]
        if record_urls and rel_type in ("child_of", "parent_of"):
            meta["birth_record_url"] = record_urls[0]

        relatives.append({
            "name": raw_name,
            "birth_year": next(iter(birth_years), None),
            "rel_type": rel_type,
            "confidence": confidence,
            "sources": sources,
            "record_types": record_types,
            "meta": meta,
            "conflict_flag": conflicting,
        })

    return relatives
```

---

## Task 5: GenealogyEnricher — BFS build_tree() + _find_or_create_person()

**File:** `modules/enrichers/genealogy_enricher.py` (continued — append to Task 4 content)

- [ ] **Step 1: Add _find_or_create_person() method**

Append the `GenealogyEnricher` class opening and `_find_or_create_person` to `modules/enrichers/genealogy_enricher.py`:
```python

class GenealogyEnricher:
    """Asyncio daemon: builds and maintains family trees for persons."""

    def __init__(self) -> None:
        self._running = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _run_genealogy_crawlers(
        self, person_id: uuid.UUID, session: AsyncSession
    ) -> list[Any]:
        """Look up Person name, run all 5 genealogy crawlers, return results."""
        from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
        from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
        from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
        from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
        from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler

        result_obj = await session.get(Person, person_id)
        if not result_obj or not result_obj.full_name:
            return []

        identifier = result_obj.full_name
        if result_obj.date_of_birth:
            identifier = f"{identifier} {result_obj.date_of_birth.year}"

        crawlers = [
            AncestryHintsCrawler(),
            CensusRecordsCrawler(),
            VitalsRecordsCrawler(),
            NewspapersArchiveCrawler(),
            GeniPublicCrawler(),
        ]

        results = await asyncio.gather(
            *[c.crawl(identifier) for c in crawlers],
            return_exceptions=True,
        )

        return [r for r in results if not isinstance(r, Exception)]

    async def _find_or_create_person(
        self,
        relative: dict,
        session: AsyncSession,
    ) -> Person:
        """
        Find existing Person by name + optional birth_year, or create a stub.

        Match strategy:
        1. Exact full_name match in persons table
        2. If birth_year is known, narrow by date_of_birth year
        3. If no match, INSERT a new stub Person with meta["stub"] = True
        """
        from sqlalchemy import extract, func

        name = relative["name"]
        birth_year = relative.get("birth_year")

        stmt = select(Person).where(
            func.lower(Person.full_name) == name.lower()
        )
        if birth_year:
            stmt = stmt.where(extract("year", Person.date_of_birth) == birth_year)

        result = await session.execute(stmt.limit(1))
        person = result.scalar_one_or_none()

        if person:
            return person

        # Create stub
        stub = Person(
            full_name=name,
            meta={
                "stub": True,
                "stub_source": "genealogy_enricher",
                "needs_genealogy": True,
            },
        )
        session.add(stub)
        await session.flush()  # get stub.id without committing
        return stub

    async def _create_or_update_relationship(
        self,
        person_a_id: uuid.UUID,
        person_b_id: uuid.UUID,
        rel_type: str,
        confidence: float,
        meta: dict,
        conflict_flag: bool,
        session: AsyncSession,
    ) -> None:
        """
        Upsert a Relationship row using PostgreSQL ON CONFLICT DO UPDATE.

        person_a is always the seed person for this BFS step.
        The relationship is directional: person_a <rel_type> person_b.
        """
        now = datetime.now(UTC)
        stmt = (
            pg_insert(Relationship)
            .values(
                id=uuid.uuid4(),
                person_a_id=person_a_id,
                person_b_id=person_b_id,
                rel_type=rel_type,
                score=confidence,
                evidence={
                    **meta,
                    "conflict_flag": conflict_flag,
                },
                first_seen_at=now,
                last_seen_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_relationship",
                set_={
                    "score": confidence,
                    "evidence": {
                        **meta,
                        "conflict_flag": conflict_flag,
                    },
                    "last_seen_at": now,
                },
            )
        )
        await session.execute(stmt)
```

- [ ] **Step 2: Add build_tree() BFS method**

Continue appending to the `GenealogyEnricher` class:
```python
    async def build_tree(
        self,
        seed_person_id: uuid.UUID,
        session: AsyncSession,
        max_ancestors: int = 8,
    ) -> FamilyTreeSnapshot:
        """
        BFS from seed_person_id outward.

        - Ancestors: traced up to max_ancestors generations (default 8)
        - Descendants: unlimited
        - Each visited person runs all 5 genealogy crawlers
        - Relationships stored in Relationship table with new rel_types
        - Returns a FamilyTreeSnapshot (not yet persisted — caller commits)

        Queue item: (person_id, generation, direction)
          generation < 0  → ancestor level
          generation == 0 → seed
          generation > 0  → descendant level

        For ancestors: abs(generation) is capped at max_ancestors.
        Descendants have no cap.
        """
        queue: deque[tuple[uuid.UUID, int, str]] = deque(
            [(seed_person_id, 0, "root")]
        )
        visited: set[uuid.UUID] = set()
        all_sources: set[str] = set()

        # Track tree structure for JSON serialisation
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        while queue:
            person_id, generation, direction = queue.popleft()

            if person_id in visited:
                continue
            # Cap ancestors at max_ancestors; descendants are unlimited
            if generation < 0 and abs(generation) > max_ancestors:
                continue

            visited.add(person_id)

            crawler_results = await self._run_genealogy_crawlers(person_id, session)
            for r in crawler_results:
                if r.found:
                    all_sources.add(r.platform)

            relatives = _parse_relatives(crawler_results, person_id)

            for relative in relatives:
                canonical = await self._find_or_create_person(relative, session)

                await self._create_or_update_relationship(
                    person_a_id=person_id,
                    person_b_id=canonical.id,
                    rel_type=relative["rel_type"],
                    confidence=relative["confidence"],
                    meta=relative["meta"],
                    conflict_flag=relative["conflict_flag"],
                    session=session,
                )

                # Track node + edge for snapshot JSON
                nodes[str(canonical.id)] = {
                    "id": str(canonical.id),
                    "name": canonical.full_name,
                    "birth_year": relative.get("birth_year"),
                    "rel_type": relative["rel_type"],
                    "confidence": relative["confidence"],
                    "generation": (
                        generation - 1 if relative["rel_type"] == "child_of" else generation + 1
                    ),
                }
                edges.append({
                    "source": str(person_id),
                    "target": str(canonical.id),
                    "rel_type": relative["rel_type"],
                    "confidence": relative["confidence"],
                })

                # Determine next generation depth
                if relative["rel_type"] == "child_of":
                    # Going toward ancestor
                    next_gen = generation - 1
                elif relative["rel_type"] == "parent_of":
                    # Going toward descendant
                    next_gen = generation + 1
                else:
                    # Lateral relatives (spouses, siblings) stay at same level
                    next_gen = generation

                if canonical.id not in visited:
                    queue.append((canonical.id, next_gen, direction))

        # Add seed node
        seed = await session.get(Person, seed_person_id)
        if seed:
            nodes[str(seed_person_id)] = {
                "id": str(seed_person_id),
                "name": seed.full_name,
                "birth_year": seed.date_of_birth.year if seed.date_of_birth else None,
                "rel_type": "root",
                "confidence": 1.0,
                "generation": 0,
            }

        ancestor_depths = [abs(n["generation"]) for n in nodes.values() if n["generation"] < 0]
        descendant_depths = [n["generation"] for n in nodes.values() if n["generation"] > 0]

        snapshot = FamilyTreeSnapshot(
            root_person_id=seed_person_id,
            tree_json={"nodes": list(nodes.values()), "edges": edges},
            depth_ancestors=max(ancestor_depths, default=0),
            depth_descendants=max(descendant_depths, default=0),
            source_count=len(all_sources),
            built_at=datetime.now(UTC),
            is_stale=False,
        )
        session.add(snapshot)

        # Clear needs_genealogy flag
        await session.execute(
            update(Person)
            .where(Person.id == seed_person_id)
            .values(meta=Person.meta.op("||")({"needs_genealogy": False}))
        )

        return snapshot
```

---

## Task 6: GenealogyEnricher — _save_snapshot(), daemon start() loop

**File:** `modules/enrichers/genealogy_enricher.py` (continued — final section of class)

- [ ] **Step 1: Add daemon methods to GenealogyEnricher**

Continue appending to the `GenealogyEnricher` class (these are the final methods):
```python
    async def _process_pending(self) -> None:
        """
        Find up to 10 persons with needs_genealogy=True and build their trees.
        Each person gets its own session+transaction so one failure doesn't
        block the rest.
        """
        from sqlalchemy import text

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT id FROM persons "
                    "WHERE meta->>'needs_genealogy' = 'true' "
                    "LIMIT 10"
                )
            )
            ids = [row[0] for row in result.fetchall()]

        for person_id in ids:
            try:
                async with async_session_factory() as session:
                    async with session.begin():
                        snapshot = await self.build_tree(person_id, session)
                        logger.info(
                            "Built family tree for %s — %d nodes, %d sources",
                            person_id,
                            len(snapshot.tree_json.get("nodes", [])),
                            snapshot.source_count,
                        )
            except Exception as exc:
                logger.exception("Family tree build failed for person %s: %s", person_id, exc)

    async def start(self) -> None:
        """Daemon loop: process pending persons every 5 minutes."""
        self._running = True
        logger.info("GenealogyEnricher daemon started")
        while self._running:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("GenealogyEnricher loop error: %s", exc)
            await asyncio.sleep(300)  # 5 minutes
```

---

## Task 7: worker.py — Register GenealogyEnricher Daemon

**File:** `worker.py`

- [ ] **Step 1: Add --no-genealogy flag and daemon task**

In `worker.py`, make these three targeted edits:

**Edit 1** — Add `enable_genealogy: bool` parameter to `main()` signature:
```python
# Before:
async def main(workers: int, enable_growth: bool, enable_freshness: bool):

# After:
async def main(workers: int, enable_growth: bool, enable_freshness: bool, enable_genealogy: bool):
```

**Edit 2** — Add daemon task after the freshness scheduler block (before `logger.info("Worker running...")`):
```python
    # Genealogy enricher
    if enable_genealogy:
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        ge = GenealogyEnricher()
        tasks.append(asyncio.create_task(ge.start(), name="genealogy-enricher"))
        logger.info("Started genealogy enricher")
```

**Edit 3** — Add argparse flag and pass it to `main()`:
```python
    # In argparse block:
    parser.add_argument("--no-genealogy", action="store_true", help="Disable genealogy enricher")

    # In asyncio.run() call:
    asyncio.run(
        main(
            workers=args.workers,
            enable_growth=not args.no_growth,
            enable_freshness=not args.no_freshness,
            enable_genealogy=not args.no_genealogy,
        )
    )
```

**Edit 4** — Update the log message to include genealogy:
```python
    logger.info(
        f"Worker running — {workers} dispatcher(s) + "
        f"{'growth daemon + ' if enable_growth else ''}"
        f"{'freshness scheduler + ' if enable_freshness else ''}"
        f"{'genealogy enricher' if enable_genealogy else ''}"
    )
```

---

## Task 8: API — GET /persons/{id}/family-tree + POST /family-tree/build

**File:** `api/routes/persons.py`

- [ ] **Step 1: Add imports and Pydantic response schemas**

At the top of `api/routes/persons.py`, after existing imports:
```python
from shared.models.family_tree import FamilyTreeSnapshot
from shared.models.relationship import Relationship


class FamilyTreeResponse(BaseModel):
    root_person_id: str
    tree_json: dict
    depth_ancestors: int
    depth_descendants: int
    source_count: int
    built_at: str
    is_stale: bool
    snapshot_id: str


class BuildStatusResponse(BaseModel):
    person_id: str
    status: str   # "queued" | "building" | "complete" | "not_started"
    needs_genealogy: bool
    snapshot_count: int
```

- [ ] **Step 2: GET /persons/{id}/family-tree endpoint**

Append to `api/routes/persons.py`:
```python
@router.get("/persons/{person_id}/family-tree", response_model=FamilyTreeResponse)
async def get_family_tree(
    person_id: uuid.UUID,
    depth_ancestors: int = Query(default=4, ge=1, le=8),
    depth_descendants: int = Query(default=3, ge=0),
    db: AsyncSession = DbDep,
):
    """
    Return the most recent FamilyTreeSnapshot for this person.
    If no snapshot exists, or is_stale=True, trigger a background build
    and return 202 with {"status": "building"}.
    """
    # Check if person exists
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Find most recent snapshot
    stmt = (
        select(FamilyTreeSnapshot)
        .where(FamilyTreeSnapshot.root_person_id == person_id)
        .order_by(FamilyTreeSnapshot.built_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None or snapshot.is_stale:
        # Queue rebuild
        await db.execute(
            update(Person)
            .where(Person.id == person_id)
            .values(meta=Person.meta.op("||")({"needs_genealogy": True}))
        )
        await db.commit()

        if snapshot is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=202,
                content={"status": "building", "person_id": str(person_id)},
            )

    return FamilyTreeResponse(
        root_person_id=str(snapshot.root_person_id),
        tree_json=snapshot.tree_json,
        depth_ancestors=snapshot.depth_ancestors,
        depth_descendants=snapshot.depth_descendants,
        source_count=snapshot.source_count,
        built_at=snapshot.built_at.isoformat(),
        is_stale=snapshot.is_stale,
        snapshot_id=str(snapshot.id),
    )


@router.post("/persons/{person_id}/family-tree/build", status_code=202)
async def trigger_family_tree_build(
    person_id: uuid.UUID,
    db: AsyncSession = DbDep,
):
    """
    Trigger a full family tree rebuild for this person.
    Sets needs_genealogy=True on the Person, which the GenealogyEnricher
    daemon will pick up within 5 minutes. Also marks any existing snapshot
    as is_stale=True.
    """
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Mark existing snapshots stale
    await db.execute(
        update(FamilyTreeSnapshot)
        .where(FamilyTreeSnapshot.root_person_id == person_id)
        .values(is_stale=True)
    )

    # Queue for enricher
    await db.execute(
        update(Person)
        .where(Person.id == person_id)
        .values(meta=Person.meta.op("||")({"needs_genealogy": True}))
    )
    await db.commit()

    return {"status": "queued", "person_id": str(person_id)}
```

---

## Task 9: API — GET /family-tree/status + GET /relatives

**File:** `api/routes/persons.py` (continued)

- [ ] **Step 1: GET /persons/{id}/family-tree/status**

Append to `api/routes/persons.py`:
```python
@router.get("/persons/{person_id}/family-tree/status", response_model=BuildStatusResponse)
async def get_family_tree_status(
    person_id: uuid.UUID,
    db: AsyncSession = DbDep,
):
    """
    Returns build progress state:
    - "not_started"  — no snapshot, needs_genealogy not set
    - "queued"       — needs_genealogy=True, no snapshot yet
    - "building"     — needs_genealogy=True, enricher is mid-run
    - "complete"     — latest snapshot is not stale
    """
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    needs_genealogy = bool((person.meta or {}).get("needs_genealogy"))

    stmt = select(func.count()).select_from(FamilyTreeSnapshot).where(
        FamilyTreeSnapshot.root_person_id == person_id
    )
    snapshot_count = (await db.execute(stmt)).scalar_one()

    if snapshot_count == 0 and not needs_genealogy:
        status = "not_started"
    elif needs_genealogy and snapshot_count == 0:
        status = "queued"
    elif needs_genealogy and snapshot_count > 0:
        status = "building"
    else:
        status = "complete"

    return BuildStatusResponse(
        person_id=str(person_id),
        status=status,
        needs_genealogy=needs_genealogy,
        snapshot_count=snapshot_count,
    )
```

- [ ] **Step 2: GET /persons/{id}/relatives**

Append to `api/routes/persons.py`:
```python
GENEALOGY_REL_TYPES = {
    "parent_of", "child_of", "sibling_of", "spouse_of",
    "grandparent_of", "grandchild_of", "aunt_uncle_of", "niece_nephew_of",
    "half_sibling_of", "step_parent_of", "step_child_of",
}


@router.get("/persons/{person_id}/relatives")
async def get_relatives(
    person_id: uuid.UUID,
    rel_type: str | None = Query(default=None),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    db: AsyncSession = DbDep,
):
    """
    Flat list of all genealogical relatives for this person.

    Filters:
    - rel_type: specific relationship type (optional)
    - min_confidence: minimum confidence score (default 0.0 = all)

    Returns both directions: where person is person_a OR person_b.
    """
    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # Relationships where person is person_a
    stmt_a = select(Relationship).where(
        Relationship.person_a_id == person_id,
        Relationship.rel_type.in_(GENEALOGY_REL_TYPES),
        Relationship.score >= min_confidence,
    )
    # Relationships where person is person_b
    stmt_b = select(Relationship).where(
        Relationship.person_b_id == person_id,
        Relationship.rel_type.in_(GENEALOGY_REL_TYPES),
        Relationship.score >= min_confidence,
    )

    if rel_type:
        stmt_a = stmt_a.where(Relationship.rel_type == rel_type)
        stmt_b = stmt_b.where(Relationship.rel_type == rel_type)

    results_a = (await db.execute(stmt_a)).scalars().all()
    results_b = (await db.execute(stmt_b)).scalars().all()

    # Resolve names
    all_person_ids = set()
    for r in results_a:
        all_person_ids.add(r.person_b_id)
    for r in results_b:
        all_person_ids.add(r.person_a_id)

    persons_result = await db.execute(
        select(Person).where(Person.id.in_(all_person_ids))
    )
    persons_map = {p.id: p for p in persons_result.scalars().all()}

    def _rel_dict(rel: Relationship, other_id: uuid.UUID, direction: str) -> dict:
        other = persons_map.get(other_id)
        return {
            "relationship_id": str(rel.id),
            "person_id": str(other_id),
            "person_name": other.full_name if other else None,
            "rel_type": rel.rel_type,
            "confidence": rel.score,
            "direction": direction,
            "sources": (rel.evidence or {}).get("sources", []),
            "conflict_flag": (rel.evidence or {}).get("conflict_flag", False),
            "first_seen_at": rel.first_seen_at.isoformat() if rel.first_seen_at else None,
        }

    relatives = [_rel_dict(r, r.person_b_id, "outbound") for r in results_a]
    relatives += [_rel_dict(r, r.person_a_id, "inbound") for r in results_b]
    relatives.sort(key=lambda x: (-x["confidence"], x["rel_type"]))

    return {"person_id": str(person_id), "count": len(relatives), "relatives": relatives}
```

---

## Task 10: GEDCOM Export Function + API Endpoint

**Files:**
- Create: `modules/export/gedcom.py` (new file)
- Modify: `api/routes/persons.py` (add export endpoint)

- [ ] **Step 1: Create GEDCOM export module**

Create `modules/export/gedcom.py`:
```python
"""
gedcom.py — GEDCOM 5.5.5 export for family trees.

Takes a FamilyTreeSnapshot.tree_json and produces valid GEDCOM 5.5.5 output
as a string. GEDCOM is the universal genealogy interchange format accepted
by Ancestry, FamilySearch, MyHeritage, etc.

GEDCOM structure:
    0 HEAD         — header
    0 @I1@ INDI   — individual records
    0 @F1@ FAM    — family unit records (marriage / parent-child)
    0 TRLR         — trailer
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _gedcom_date(raw: str | int | None) -> str | None:
    """Convert raw date string or year int to GEDCOM date format."""
    if not raw:
        return None
    if isinstance(raw, int):
        return str(raw)
    # Already looks like GEDCOM date
    if re.match(r"^\d{1,2}\s+[A-Z]{3}\s+\d{4}$", str(raw), re.IGNORECASE):
        return raw.upper()
    # ISO date YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(raw))
    if m:
        months = ["JAN","FEB","MAR","APR","MAY","JUN",
                  "JUL","AUG","SEP","OCT","NOV","DEC"]
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{d} {months[mo - 1]} {y}"
    # Year only
    m2 = re.match(r"^(\d{4})$", str(raw))
    if m2:
        return m2.group(1)
    return str(raw)


def _name_parts(full_name: str | None) -> tuple[str, str]:
    """Return (given_names, surname) from a full name string."""
    if not full_name:
        return ("", "")
    parts = full_name.strip().split()
    if len(parts) == 1:
        return ("", parts[0])
    return (" ".join(parts[:-1]), parts[-1])


def build_gedcom(
    root_person: dict,
    tree_json: dict,
    persons_map: dict[str, dict],
) -> str:
    """
    Build a GEDCOM 5.5.5 string from a FamilyTreeSnapshot.

    Args:
        root_person: {"id": str, "full_name": str, "date_of_birth": str|None, "gender": str|None}
        tree_json:   FamilyTreeSnapshot.tree_json — {"nodes": [...], "edges": [...]}
        persons_map: {person_id_str: {"full_name": str, "date_of_birth": str|None, ...}}
                     looked up from DB by the caller

    Returns:
        GEDCOM 5.5.5 string ready for download.
    """
    lines: list[str] = []
    now = datetime.now(timezone.utc)

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "0 HEAD",
        "1 SOUR Lycan",
        "2 VERS 1.0",
        "2 NAME Lycan OSINT",
        "1 DATE " + now.strftime("%d %b %Y").upper(),
        "1 GEDC",
        "2 VERS 5.5.5",
        "1 CHAR UTF-8",
        "1 LANG English",
    ]

    # Build ID map: person_id → INDI tag @I<n>@
    all_ids = {root_person["id"]}
    for node in tree_json.get("nodes", []):
        all_ids.add(node["id"])
    id_to_tag: dict[str, str] = {pid: f"@I{i + 1}@" for i, pid in enumerate(sorted(all_ids))}

    # ── Individual records ────────────────────────────────────────────────────
    for person_id, indi_tag in id_to_tag.items():
        if person_id == root_person["id"]:
            p_data = root_person
        else:
            p_data = persons_map.get(person_id, {})

        full_name = p_data.get("full_name") or p_data.get("name") or "Unknown"
        given, surname = _name_parts(full_name)
        gender = (p_data.get("gender") or "U").upper()[0]
        if gender not in ("M", "F"):
            gender = "U"

        lines.append(f"0 {indi_tag} INDI")
        lines.append(f"1 NAME {given} /{surname}/")
        if gender in ("M", "F"):
            lines.append(f"1 SEX {gender}")

        dob = p_data.get("date_of_birth") or p_data.get("birth_date") or p_data.get("birth_year")
        if dob:
            gedcom_dob = _gedcom_date(dob)
            if gedcom_dob:
                lines.append("1 BIRT")
                lines.append(f"2 DATE {gedcom_dob}")

        dod = p_data.get("death_date")
        if dod:
            gedcom_dod = _gedcom_date(dod)
            if gedcom_dod:
                lines.append("1 DEAT")
                lines.append(f"2 DATE {gedcom_dod}")

    # ── Family records ─────────────────────────────────────────────────────────
    # Build family units from edges: one FAM record per spouse_of pair,
    # and parent/child edges contribute to those FAM records.
    fam_index = 0
    processed_spouse_pairs: set[frozenset[str]] = set()

    edges = tree_json.get("edges", [])

    for edge in edges:
        if edge["rel_type"] != "spouse_of":
            continue
        pair = frozenset([edge["source"], edge["target"]])
        if pair in processed_spouse_pairs:
            continue
        processed_spouse_pairs.add(pair)
        fam_index += 1
        fam_tag = f"@F{fam_index}@"

        husb_id, wife_id = sorted(pair)  # deterministic ordering
        lines.append(f"0 {fam_tag} FAM")
        husb_tag = id_to_tag.get(husb_id)
        wife_tag = id_to_tag.get(wife_id)
        if husb_tag:
            lines.append(f"1 HUSB {husb_tag}")
        if wife_tag:
            lines.append(f"1 WIFE {wife_tag}")

        # Marriage date from evidence if available
        marriage_date = edge.get("meta", {}).get("marriage_date") if isinstance(edge.get("meta"), dict) else None
        if marriage_date:
            gedcom_marr = _gedcom_date(marriage_date)
            if gedcom_marr:
                lines.append("1 MARR")
                lines.append(f"2 DATE {gedcom_marr}")

        # Attach children — find parent_of edges from either spouse to same targets
        spouse_ids = {husb_id, wife_id}
        for ce in edges:
            if ce["rel_type"] == "parent_of" and ce["source"] in spouse_ids:
                child_tag = id_to_tag.get(ce["target"])
                if child_tag:
                    lines.append(f"1 CHIL {child_tag}")

    # ── Trailer ───────────────────────────────────────────────────────────────
    lines.append("0 TRLR")

    return "\r\n".join(lines) + "\r\n"
```

- [ ] **Step 2: Add GEDCOM export endpoint to api/routes/persons.py**

Append to `api/routes/persons.py`:
```python
@router.get("/persons/{person_id}/family-tree/export/gedcom")
async def export_family_tree_gedcom(
    person_id: uuid.UUID,
    db: AsyncSession = DbDep,
):
    """
    Export the latest family tree snapshot as a GEDCOM 5.5.5 file.
    Returns application/x-gedcom with Content-Disposition: attachment.
    """
    from fastapi.responses import Response

    from modules.export.gedcom import build_gedcom

    person = await db.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    stmt = (
        select(FamilyTreeSnapshot)
        .where(FamilyTreeSnapshot.root_person_id == person_id)
        .order_by(FamilyTreeSnapshot.built_at.desc())
        .limit(1)
    )
    snapshot = (await db.execute(stmt)).scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No family tree built yet. POST /family-tree/build first.")

    # Resolve all person IDs from tree_json
    node_ids = [n["id"] for n in snapshot.tree_json.get("nodes", [])]
    node_ids_uuid = []
    for nid in node_ids:
        try:
            node_ids_uuid.append(uuid.UUID(nid))
        except ValueError:
            pass

    persons_result = await db.execute(
        select(Person).where(Person.id.in_(node_ids_uuid))
    )
    persons_map = {
        str(p.id): {
            "full_name": p.full_name,
            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
            "gender": p.gender,
        }
        for p in persons_result.scalars().all()
    }

    root_data = {
        "id": str(person.id),
        "full_name": person.full_name,
        "date_of_birth": person.date_of_birth.isoformat() if person.date_of_birth else None,
        "gender": person.gender,
    }

    gedcom_str = build_gedcom(root_data, snapshot.tree_json, persons_map)
    filename = f"family_tree_{person_id}.ged"

    return Response(
        content=gedcom_str.encode("utf-8"),
        media_type="application/x-gedcom",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

---

## Task 11: D3 Hierarchical Tree View — Core View + D3 Import

**File:** `static/index.html`

- [ ] **Step 1: Add D3 v7 CDN import**

In the `<head>` section of `static/index.html`, after the `<title>` tag, add:
```html
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
```

- [ ] **Step 2: Add route for #/persons/<id>/tree**

In the `route()` method, after the existing `#/person/` handler:
```javascript
    else if (hash.startsWith('#/persons/') && hash.endsWith('/tree')) {
      document.getElementById('nav-persons')?.classList.add('active');
      const pid = hash.split('/')[2];
      this.renderFamilyTree(pid);
    }
```

- [ ] **Step 3: Add renderFamilyTree() method**

Add this method to the `App` class in `static/index.html` (after `renderGraph()`):
```javascript
  async renderFamilyTree(personId) {
    this.root.textContent = '';

    const hdr = div('page-header');
    const left = div('');
    left.append(div('page-title', 'Family Tree'), div('page-sub', 'Genealogical relationships — 8 generation ancestor trace'));
    const exportBtn = el('button', 'btn secondary', 'Export GEDCOM');
    exportBtn.style.marginLeft = 'auto';
    hdr.append(left, exportBtn);
    this.root.appendChild(hdr);

    // Controls card
    const ctrlCard = div('card');
    const ctrlBody = div('card-body');
    ctrlBody.style.cssText = 'display:flex;gap:20px;align-items:center;flex-wrap:wrap';

    // Ancestor depth slider
    const ancLabel = span('', 'Ancestors: ');
    const ancSlider = el('input');
    ancSlider.type = 'range'; ancSlider.min = '1'; ancSlider.max = '8'; ancSlider.value = '4';
    ancSlider.style.width = '120px';
    const ancVal = span('kv-val', '4');
    ancSlider.addEventListener('input', () => { ancVal.textContent = ancSlider.value; });

    // Descendant depth slider
    const descLabel = span('', 'Descendants: ');
    const descSlider = el('input');
    descSlider.type = 'range'; descSlider.min = '0'; descSlider.max = '5'; descSlider.value = '3';
    descSlider.style.width = '120px';
    const descVal = span('kv-val', '3');
    descSlider.addEventListener('input', () => { descVal.textContent = descSlider.value; });

    // Verified-only toggle
    const verLabel = el('label', '');
    const verChk = el('input'); verChk.type = 'checkbox';
    verLabel.append(verChk, span('', ' Verified only (≥0.70)'));
    verLabel.style.cursor = 'pointer';

    // Expand to graph button
    const expandBtn = el('button', 'btn secondary', 'Expand to Graph');

    ctrlBody.append(ancLabel, ancSlider, ancVal, descLabel, descSlider, descVal, verLabel, expandBtn);
    ctrlCard.appendChild(ctrlBody);
    this.root.appendChild(ctrlCard);

    // Status banner
    const statusCard = div('card');
    const statusBody = div('card-body');
    statusCard.appendChild(statusBody);
    this.root.appendChild(statusCard);

    // SVG container card
    const treeCard = div('card');
    const treeBody = div('card-body');
    treeBody.style.overflow = 'auto';
    const svgContainer = div('');
    svgContainer.id = 'family-tree-svg-container';
    svgContainer.style.cssText = 'min-height:600px;width:100%';
    treeBody.appendChild(svgContainer);
    treeCard.appendChild(treeBody);
    this.root.appendChild(treeCard);

    // Fetch + render
    const renderTree = async () => {
      svgContainer.textContent = '';
      statusBody.textContent = '';
      statusBody.appendChild(span('spinner'));

      let data;
      try {
        data = await apiGet(
          `/persons/${personId}/family-tree?depth_ancestors=${ancSlider.value}&depth_descendants=${descSlider.value}`
        );
      } catch(e) {
        statusBody.textContent = '';
        statusBody.appendChild(span('red-txt', 'Error: ' + e.message));
        return;
      }

      if (data.status === 'building') {
        statusBody.textContent = '';
        const pill = span('status-pill pending', 'Building…');
        const msg = span('', ' Tree is being assembled. Refresh in ~30 seconds.');
        statusBody.append(pill, msg);
        return;
      }

      statusBody.textContent = '';
      const pill2 = span('status-pill done', data.is_stale ? 'Stale' : 'Fresh');
      const src = span('kv-val', ` ${data.source_count} sources · ${data.depth_ancestors} ancestor generations · ${data.depth_descendants} descendant generations`);
      statusBody.append(pill2, src);

      _drawD3Tree(svgContainer, data.tree_json, parseFloat(verChk.checked ? '0.70' : '0.0'));
    };

    ancSlider.addEventListener('change', renderTree);
    descSlider.addEventListener('change', renderTree);
    verChk.addEventListener('change', renderTree);

    // GEDCOM export
    exportBtn.addEventListener('click', () => {
      window.location.href = `/persons/${personId}/family-tree/export/gedcom`;
    });

    // Expand to graph
    expandBtn.addEventListener('click', async () => {
      try {
        const d = await apiGet(`/persons/${personId}/relatives`);
        const ids = (d.relatives || []).map(r => r.person_id);
        window.location.hash = `#/graph?seed=${personId}&include=${ids.join(',')}`;
      } catch(e) {
        alert('Failed to expand: ' + e.message);
      }
    });

    await renderTree();
  }
```

---

## Task 12: D3 Tree Controls — _drawD3Tree() Implementation

**File:** `static/index.html`

- [ ] **Step 1: Add _drawD3Tree() standalone function**

Add this standalone function (outside the `App` class, in the `<script>` block) in `static/index.html`:
```javascript
function _drawD3Tree(container, treeJson, minConfidence) {
  if (!window.d3) {
    container.textContent = 'D3 library not loaded.';
    return;
  }

  const nodes = (treeJson.nodes || []).filter(n => n.confidence >= minConfidence);
  const edges = (treeJson.edges || []).filter(e =>
    e.confidence >= minConfidence &&
    nodes.some(n => n.id === e.source) &&
    nodes.some(n => n.id === e.target)
  );

  if (!nodes.length) {
    container.textContent = 'No nodes meet the confidence threshold.';
    return;
  }

  // Build d3 hierarchy: root is generation=0, parents above (negative gen), children below
  // Convert flat node list + edges into hierarchical structure
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, {...n, children: []}]));
  const rootNode = nodes.find(n => n.rel_type === 'root') || nodes[0];

  // Build adjacency: for each edge, connect source → target as parent → child in visual tree
  // Ancestors (generation < 0) are visual parents; descendants (generation > 0) are visual children
  const childrenMap = {};
  for (const edge of edges) {
    // In visual tree: lower (more negative) generation is higher up
    const src = nodeMap[edge.source];
    const tgt = nodeMap[edge.target];
    if (!src || !tgt) continue;
    if (tgt.generation < src.generation) {
      // Target is an ancestor — skip for hierarchy (handled by reverse)
      continue;
    }
    if (!childrenMap[edge.source]) childrenMap[edge.source] = [];
    childrenMap[edge.source].push(edge.target);
  }

  function buildHierarchy(id, visited = new Set()) {
    if (visited.has(id)) return null;
    visited.add(id);
    const node = nodeMap[id];
    if (!node) return null;
    const childIds = childrenMap[id] || [];
    const children = childIds.map(cid => buildHierarchy(cid, visited)).filter(Boolean);
    return { ...node, children };
  }

  const hierarchyRoot = buildHierarchy(rootNode.id);
  if (!hierarchyRoot) { container.textContent = 'Could not build tree hierarchy.'; return; }

  const width = Math.max(container.offsetWidth || 900, 900);
  const nodeHeight = 80;
  const nodeWidth = 160;

  const root = d3.hierarchy(hierarchyRoot);
  const treeLayout = d3.tree().nodeSize([nodeWidth, nodeHeight]);
  treeLayout(root);

  // Calculate bounds
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  root.each(d => {
    if (d.x < x0) x0 = d.x;
    if (d.x > x1) x1 = d.x;
    if (d.y < y0) y0 = d.y;
    if (d.y > y1) y1 = d.y;
  });

  const svgWidth = x1 - x0 + nodeWidth * 2;
  const svgHeight = y1 - y0 + nodeHeight * 4;

  const svg = d3.create('svg')
    .attr('width', svgWidth)
    .attr('height', svgHeight)
    .attr('viewBox', [x0 - nodeWidth, y0 - nodeHeight * 2, svgWidth, svgHeight])
    .style('font', '12px Inter, system-ui, sans-serif')
    .style('background', 'var(--bg2)')
    .style('border-radius', '8px');

  // Edge paths
  const link = svg.append('g').attr('fill', 'none');
  root.links().forEach(d => {
    const opacity = Math.max(0.2, (d.target.data.confidence || 0));
    const sourceCount = ((d.target.data.sources || []).length);
    link.append('path')
      .attr('d', d3.linkVertical().x(n => n.x).y(n => n.y)(d))
      .attr('stroke', 'var(--border2)')
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', opacity);

    // Source count badge on edge midpoint
    if (sourceCount > 0) {
      const mx = (d.source.x + d.target.x) / 2;
      const my = (d.source.y + d.target.y) / 2;
      const badge = svg.append('g').attr('transform', `translate(${mx},${my})`);
      badge.append('circle').attr('r', 9).attr('fill', 'var(--accent2)').attr('opacity', 0.85);
      badge.append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', '0.35em')
        .attr('fill', 'white')
        .attr('font-size', '8px')
        .text(sourceCount);
    }
  });

  // Node groups
  const node = svg.append('g')
    .selectAll('g')
    .data(root.descendants())
    .join('g')
    .attr('transform', d => `translate(${d.x},${d.y})`)
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      window.location.hash = `#/person/${d.data.id}`;
    });

  // Node background rect — opacity reflects confidence
  node.append('rect')
    .attr('x', -nodeWidth / 2 + 4)
    .attr('y', -28)
    .attr('width', nodeWidth - 8)
    .attr('height', 52)
    .attr('rx', 6)
    .attr('fill', d => d.data.rel_type === 'root' ? 'var(--accent2)' : 'var(--bg3)')
    .attr('stroke', 'var(--border2)')
    .attr('stroke-width', 1)
    .attr('opacity', d => 0.4 + (d.data.confidence || 0) * 0.6);

  // Name text
  node.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '-8px')
    .attr('fill', 'var(--text)')
    .attr('font-size', '11px')
    .attr('font-weight', d => d.data.rel_type === 'root' ? '600' : '400')
    .text(d => {
      const name = d.data.name || 'Unknown';
      return name.length > 20 ? name.slice(0, 18) + '…' : name;
    });

  // Rel_type label
  node.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '8px')
    .attr('fill', 'var(--text-dim)')
    .attr('font-size', '9px')
    .text(d => d.data.rel_type === 'root' ? 'SEED' : (d.data.rel_type || '').replace(/_/g, ' ').toUpperCase());

  // Confidence pct
  node.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '22px')
    .attr('fill', d => {
      const c = d.data.confidence || 0;
      return c >= 0.70 ? 'var(--green)' : c >= 0.40 ? 'var(--yellow)' : 'var(--red)';
    })
    .attr('font-size', '9px')
    .text(d => d.data.rel_type === 'root' ? '' : Math.round((d.data.confidence || 0) * 100) + '%');

  container.appendChild(svg.node());
}
```

---

## Task 13: Tests

**Files:**
- Create: `tests/test_enrichers/test_genealogy_enricher.py`
- Create: `tests/test_crawlers/test_genealogy_crawlers.py`

- [ ] **Step 1: BFS algorithm + confidence scoring tests**

Create `tests/test_enrichers/test_genealogy_enricher.py`:
```python
"""Tests for GenealogyEnricher: confidence scoring and _parse_relatives()."""

import uuid

import pytest

from modules.enrichers.genealogy_enricher import compute_confidence, _parse_relatives
from modules.crawlers.result import CrawlerResult


# ── compute_confidence ────────────────────────────────────────────────────────


def test_confidence_one_source_no_gov():
    assert compute_confidence(["genealogy_geni_public"], ["tree"]) == pytest.approx(0.40, abs=0.01)


def test_confidence_two_sources_no_gov():
    assert compute_confidence(
        ["genealogy_geni_public", "genealogy_ancestry_hints"], ["tree", "tree"]
    ) == pytest.approx(0.72, abs=0.01)


def test_confidence_three_plus_sources():
    assert compute_confidence(
        ["a", "b", "c"], ["tree", "tree", "tree"]
    ) == pytest.approx(0.92, abs=0.01)


def test_confidence_government_bonus_one_source():
    score = compute_confidence(["genealogy_census_records"], ["census"])
    assert score == pytest.approx(0.40 + 0.15, abs=0.01)


def test_confidence_government_bonus_capped():
    # 3 gov sources should not exceed 1.0
    score = compute_confidence(["a", "b", "c"], ["birth_cert", "census", "death_cert"])
    assert score <= 1.0


def test_confidence_conflict():
    score = compute_confidence(["a", "b"], ["tree", "tree"], conflicting=True)
    assert score < 0.72


def test_confidence_zero_sources():
    assert compute_confidence([], []) == 0.0


# ── _parse_relatives ──────────────────────────────────────────────────────────


def _make_result(platform: str, record_type: str, parents=None, children=None, spouses=None, siblings=None) -> CrawlerResult:
    return CrawlerResult(
        platform=platform,
        identifier="Test Person",
        found=True,
        data={
            "person_name": "Test Person",
            "birth_date": None,
            "birth_place": None,
            "death_date": None,
            "death_place": None,
            "parents": parents or [],
            "children": children or [],
            "spouses": spouses or [],
            "siblings": siblings or [],
            "source_url": "https://example.com",
            "record_type": record_type,
        },
        source_reliability=0.75,
    )


def test_parse_relatives_deduplication():
    """Same relative from two sources should produce one entry with higher confidence."""
    seed_id = uuid.uuid4()
    r1 = _make_result("genealogy_geni_public", "tree",
                       parents=[{"name": "John Smith", "birth_year": 1950}])
    r2 = _make_result("genealogy_ancestry_hints", "tree",
                       parents=[{"name": "John Smith", "birth_year": 1950}])

    relatives = _parse_relatives([r1, r2], seed_id)
    assert len(relatives) == 1
    rel = relatives[0]
    assert rel["rel_type"] == "child_of"
    assert len(rel["sources"]) == 2
    assert rel["confidence"] == pytest.approx(0.72, abs=0.01)


def test_parse_relatives_gov_bonus():
    """Census source should trigger government bonus."""
    seed_id = uuid.uuid4()
    r = _make_result("genealogy_census_records", "census",
                     parents=[{"name": "Mary Jones", "birth_year": 1920}])
    relatives = _parse_relatives([r], seed_id)
    assert relatives[0]["confidence"] == pytest.approx(0.40 + 0.15, abs=0.01)


def test_parse_relatives_conflict_flag():
    """Same name + same rel_type but different birth years → conflict_flag=True."""
    seed_id = uuid.uuid4()
    r1 = _make_result("genealogy_geni_public", "tree",
                       parents=[{"name": "Bob Brown", "birth_year": 1940}])
    r2 = _make_result("genealogy_ancestry_hints", "tree",
                       parents=[{"name": "Bob Brown", "birth_year": 1955}])  # different year

    relatives = _parse_relatives([r1, r2], seed_id)
    assert relatives[0]["conflict_flag"] is True


def test_parse_relatives_multiple_rel_types():
    """Parents, children, spouses, siblings all parsed from same result."""
    seed_id = uuid.uuid4()
    r = _make_result(
        "genealogy_geni_public", "tree",
        parents=[{"name": "Dad Person", "birth_year": 1950}],
        children=[{"name": "Kid Person", "birth_year": 2000}],
        spouses=[{"name": "Spouse Person", "marriage_date": "1990"}],
        siblings=[{"name": "Sib Person", "birth_year": 1975}],
    )
    relatives = _parse_relatives([r], seed_id)
    rel_types = {rel["rel_type"] for rel in relatives}
    assert rel_types == {"child_of", "parent_of", "spouse_of", "sibling_of"}


def test_parse_relatives_skips_empty_names():
    """Relatives with empty name strings should be dropped."""
    seed_id = uuid.uuid4()
    r = _make_result("genealogy_geni_public", "tree",
                     parents=[{"name": "", "birth_year": None}])
    relatives = _parse_relatives([r], seed_id)
    assert len(relatives) == 0


def test_parse_relatives_not_found_results_ignored():
    """CrawlerResult with found=False should contribute nothing."""
    seed_id = uuid.uuid4()
    r = CrawlerResult(
        platform="genealogy_geni_public",
        identifier="Test",
        found=False,
        data={},
        source_reliability=0.60,
    )
    relatives = _parse_relatives([r], seed_id)
    assert len(relatives) == 0
```

- [ ] **Step 2: Crawler mock tests**

Create `tests/test_crawlers/test_genealogy_crawlers.py`:
```python
"""Mock-based tests for all 5 genealogy crawlers."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler


def _mock_resp(json_data: dict):
    resp = MagicMock()
    resp.json.return_value = json_data
    return resp


# ── AncestryHintsCrawler ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ancestry_hints_found():
    crawler = AncestryHintsCrawler()
    mock_resp = _mock_resp({
        "results": [{
            "displayName": "John Smith",
            "birthDate": "1980",
            "birthPlace": "Texas",
            "deathDate": None,
            "deathPlace": None,
            "relatives": {
                "parents": [{"displayName": "Robert Smith", "birthYear": 1950}],
                "children": [],
                "spouses": [{"displayName": "Jane Smith", "marriageDate": "2005"}],
                "siblings": [],
            },
        }]
    })
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("John Smith 1980")

    assert result.found is True
    assert result.data["person_name"] == "John Smith"
    assert len(result.data["parents"]) == 1
    assert result.data["parents"][0]["name"] == "Robert Smith"
    assert result.data["record_type"] == "tree"


@pytest.mark.asyncio
async def test_ancestry_hints_not_found():
    crawler = AncestryHintsCrawler()
    mock_resp = _mock_resp({"results": []})
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Nobody Known")

    assert result.found is False


# ── CensusRecordsCrawler ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_census_records_found():
    crawler = CensusRecordsCrawler()
    fs_response = {
        "entries": [{
            "content": {
                "gedcomx": {
                    "persons": [
                        {
                            "id": "p1",
                            "names": [{"nameForms": [{"fullText": "Mary Jones"}]}],
                            "facts": [
                                {"type": "http://gedcomx.org/Birth",
                                 "date": {"original": "1920"},
                                 "place": {"original": "Iowa"}}
                            ],
                        }
                    ],
                    "relationships": [],
                }
            }
        }]
    }
    mock_resp = _mock_resp(fs_response)
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Mary Jones 1920")

    assert result.found is True
    assert result.data["person_name"] == "Mary Jones"
    assert result.data["birth_date"] == "1920"
    assert result.data["record_type"] == "census"


@pytest.mark.asyncio
async def test_census_records_not_found():
    crawler = CensusRecordsCrawler()
    mock_resp = _mock_resp({"entries": []})
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Nobody Known")

    assert result.found is False


# ── VitalsRecordsCrawler ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vitals_records_found():
    crawler = VitalsRecordsCrawler()
    fs_response = {
        "entries": [{
            "content": {
                "gedcomx": {
                    "persons": [{
                        "id": "v1",
                        "names": [{"nameForms": [{"fullText": "Alice Brown"}]}],
                        "facts": [
                            {"type": "http://gedcomx.org/Death",
                             "date": {"original": "1995"},
                             "place": {"original": "California"}},
                        ],
                    }],
                    "relationships": [],
                }
            }
        }]
    }
    mock_resp = _mock_resp(fs_response)
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Alice Brown")

    assert result.found is True
    assert result.data["death_date"] == "1995"
    assert result.data["record_type"] == "death_cert"


# ── NewspapersArchiveCrawler ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_newspapers_archive_found():
    crawler = NewspapersArchiveCrawler()
    loc_response = {
        "items": [{
            "ocr_eng": "John Doe, son of Robert Doe and Mary Doe, was married to Jane Smith.",
            "date": "1950-06-15",
            "place_of_publication": "Austin, Texas",
        }]
    }
    mock_resp = _mock_resp(loc_response)
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("John Doe")

    assert result.found is True
    assert len(result.data["parents"]) >= 1
    assert result.data["record_type"] == "obituary"


@pytest.mark.asyncio
async def test_newspapers_archive_not_found():
    crawler = NewspapersArchiveCrawler()
    mock_resp = _mock_resp({"items": []})
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Nobody Known")

    assert result.found is False


# ── GeniPublicCrawler ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_geni_public_found():
    crawler = GeniPublicCrawler()

    search_resp = _mock_resp({"results": [{"id": "profile-123", "name": "Tom Harris"}]})
    profile_resp = _mock_resp({
        "id": "profile-123",
        "name": "Tom Harris",
        "birth": {"date": {"year": 1965}, "place": {"name": "New York"}},
        "death": {},
        "parents": {
            "p_dad": {"name": "Bill Harris", "birth": {"date": {"year": 1935}}},
        },
        "unions": ["union-1"],
    })
    union_resp = _mock_resp({
        "partners": {"sp1": {"id": "sp-1", "name": "Carol Harris"}},
        "children": {"ch1": {"name": "Sam Harris", "birth": {"date": {"year": 1995}}}},
    })

    get_responses = [search_resp, profile_resp, union_resp]
    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        resp = get_responses[min(call_count, len(get_responses) - 1)]
        call_count += 1
        return resp

    with patch.object(crawler, '_get', side_effect=mock_get):
        result = await crawler.crawl("Tom Harris 1965")

    assert result.found is True
    assert result.data["person_name"] == "Tom Harris"
    assert len(result.data["parents"]) == 1
    assert len(result.data["spouses"]) == 1
    assert len(result.data["children"]) == 1


@pytest.mark.asyncio
async def test_geni_public_not_found():
    crawler = GeniPublicCrawler()
    mock_resp = _mock_resp({"results": []})
    with patch.object(crawler, '_get', return_value=mock_resp):
        result = await crawler.crawl("Nobody Known")

    assert result.found is False
```

---

## Dependency Notes

- D3 v7 is loaded from CDN (`cdn.jsdelivr.net`) — no npm install required; existing SPA already uses vanilla JS
- No new Python packages required: all crawlers use existing `httpx_base.HttpxCrawler` and `sqlalchemy` patterns already in the project
- `modules/export/` directory will be created implicitly when `gedcom.py` is created; add `__init__.py` if Python requires it for the import path used in `api/routes/persons.py`
- The `async_session_factory` import used in `GenealogyEnricher._process_pending()` — verify the actual import path in `shared/db.py` before wiring; pattern follows `AuditDaemon` in Phase 6

## Rel_type Reference

The following new `rel_type` values are introduced in this phase for the `relationships` table. No schema change is needed (the column is `String(50)` with no enum constraint):

| rel_type | Direction (person_a → person_b) |
|---|---|
| `parent_of` | person_a is parent of person_b |
| `child_of` | person_a is child of person_b |
| `sibling_of` | symmetric |
| `spouse_of` | symmetric |
| `grandparent_of` | person_a is grandparent of person_b |
| `grandchild_of` | person_a is grandchild of person_b |
| `aunt_uncle_of` | person_a is aunt/uncle of person_b |
| `niece_nephew_of` | person_a is niece/nephew of person_b |
| `half_sibling_of` | symmetric |
| `step_parent_of` | person_a is step-parent of person_b |
| `step_child_of` | person_a is step-child of person_b |

Note: `grandparent_of`, `grandchild_of`, `aunt_uncle_of`, `niece_nephew_of`, `half_sibling_of`, `step_parent_of`, `step_child_of` are valid stored values for manually-entered or high-confidence multi-hop derivations. The BFS crawler pipeline initially produces only `parent_of`, `child_of`, `sibling_of`, and `spouse_of` — the extended types are available for future inference passes.
