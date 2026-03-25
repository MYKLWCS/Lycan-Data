"""
test_ubo_discovery_db.py — DB-layer and BFS edge-case coverage for ubo_discovery.

Covers the lines the unit test file misses:
  - _upsert_person (person exists / not exists, emp exists / not exists)
  - _check_sanctions (empty list, rows returned)
  - BFS: depth >= max_depth branch
  - _crawl_company: GLEIF lei fallback, oc companies loop, GLEIF error flag
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.graph.ubo_discovery import (
    CrawledCompanyData,
    PersonRef,
    UBODiscoveryEngine,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_session():
    """Return a mock AsyncSession that returns nothing by default."""
    session = AsyncMock()
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    empty.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _make_person_mock(person_id: uuid.UUID, name: str):
    p = MagicMock()
    p.id = person_id
    p.full_name = name
    p.meta = {}
    return p


# ── _upsert_person ────────────────────────────────────────────────────────────


class TestUpsertPerson:
    @pytest.mark.asyncio
    async def test_creates_new_person_when_not_found(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        new_id = uuid.uuid4()

        added_person = None

        def _capture_add(obj):
            nonlocal added_person
            if hasattr(obj, "full_name"):
                obj.id = new_id
                added_person = obj

        session.add.side_effect = _capture_add

        result = await engine._upsert_person("New Person", "Acme Corp", "director", session)
        assert session.flush.called
        assert added_person is not None
        assert added_person.full_name == "New Person"

    @pytest.mark.asyncio
    async def test_returns_existing_person_id_when_found(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        existing_id = uuid.uuid4()
        existing_person = _make_person_mock(existing_id, "Alice Smith")

        # First execute returns the person, second returns no employment
        exec_person = MagicMock()
        exec_person.scalar_one_or_none.return_value = existing_person
        exec_emp = MagicMock()
        exec_emp.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(side_effect=[exec_person, exec_emp])

        result = await engine._upsert_person("Alice Smith", "Acme Corp", "director", session)
        assert result == str(existing_id)

    @pytest.mark.asyncio
    async def test_skips_employment_insert_when_emp_exists(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        existing_id = uuid.uuid4()
        existing_person = _make_person_mock(existing_id, "Bob Jones")
        existing_emp = MagicMock()

        exec_person = MagicMock()
        exec_person.scalar_one_or_none.return_value = existing_person
        exec_emp = MagicMock()
        exec_emp.scalar_one_or_none.return_value = existing_emp

        session.execute = AsyncMock(side_effect=[exec_person, exec_emp])

        result = await engine._upsert_person("Bob Jones", "Acme Corp", "officer", session)
        assert result == str(existing_id)
        # session.add should only be called for the person (but person exists, so not at all)
        # The key assertion: no EmploymentHistory added
        added_types = [type(call_args[0][0]).__name__ for call_args in session.add.call_args_list]
        assert "EmploymentHistory" not in added_types


# ── _check_sanctions ──────────────────────────────────────────────────────────


class TestCheckSanctions:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_empty_list(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        result = await engine._check_sanctions([], session)
        assert result == {}
        # Should not touch the DB
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_hits_for_no_matches(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        pid = str(uuid.uuid4())

        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=exec_result)

        result = await engine._check_sanctions([pid], session)
        assert result == {pid: []}

    @pytest.mark.asyncio
    async def test_maps_watchlist_rows_to_person_ids(self):
        engine = UBODiscoveryEngine()
        session = _make_session()
        pid = str(uuid.uuid4())

        row = MagicMock()
        row.person_id = uuid.UUID(pid)
        row.list_type = "ofac"
        row.match_name = "Test Person"
        row.confidence = 0.95

        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=exec_result)

        result = await engine._check_sanctions([pid], session)
        assert len(result[pid]) == 1
        assert result[pid][0]["list_type"] == "ofac"
        assert result[pid][0]["confidence"] == 0.95


# ── BFS: depth >= max_depth ───────────────────────────────────────────────────


class TestBFSDepthLimit:
    @pytest.mark.asyncio
    async def test_depth_zero_skips_crawl(self):
        """With max_depth=0 the root company node is added but no crawl runs."""
        engine = UBODiscoveryEngine()

        crawl_called = []

        async def _spy_crawl(name, jur):
            crawl_called.append(name)
            return CrawledCompanyData(
                company_name=name, jurisdiction=jur, company_numbers=[],
                registered_addresses=[], status=None, incorporation_date=None,
                entity_type=None, lei=None, officers=[], sec_filings=[],
                has_proxy_filing=False, data_sources=[], crawl_errors=[],
            )

        with patch.object(engine, "_crawl_company", side_effect=_spy_crawl), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={}):
            result = await engine.discover("RootCorp", "us", max_depth=0, session=AsyncMock())

        # depth=0 >= max_depth=0 → continue, no crawl
        assert crawl_called == []
        # Company node still added to the graph
        assert any(n["label"] == "RootCorp" for n in result.nodes)


# ── _crawl_company: GLEIF lei fallback ────────────────────────────────────────


class TestCrawlCompanyGleifFallback:
    @pytest.mark.asyncio
    async def test_gleif_fallback_lei_when_no_exact_name_match(self):
        """Line 311: lei = completions[0].get('lei') when no exact match."""
        engine = UBODiscoveryEngine()

        gleif_result = MagicMock()
        gleif_result.found = True
        gleif_result.error = None
        # Name in completions does NOT match "Acme Corp" exactly
        gleif_result.data = {
            "completions": [{"name": "different company name", "lei": "FALLBACK_LEI_123"}]
        }

        async def _fake_crawler(platform, identifier):
            if platform == "gov_gleif":
                return gleif_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("Acme Corp", None)

        assert result.lei == "FALLBACK_LEI_123"

    @pytest.mark.asyncio
    async def test_gleif_error_recorded_in_crawl_errors(self):
        """Line 443: gleif error appended to crawl_errors."""
        engine = UBODiscoveryEngine()

        gleif_result = MagicMock()
        gleif_result.found = False
        gleif_result.error = "rate_limited"

        async def _fake_crawler(platform, identifier):
            if platform == "gov_gleif":
                return gleif_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("Acme Corp", None)

        assert any("gleif:rate_limited" in e for e in result.crawl_errors)


# ── _crawl_company: OC companies loop ────────────────────────────────────────


class TestCrawlCompanyOCLoop:
    @pytest.mark.asyncio
    async def test_extracts_metadata_from_oc_companies(self):
        """Lines 326, 336-347: OC result with companies list populates metadata."""
        engine = UBODiscoveryEngine()

        oc_result = MagicMock()
        oc_result.found = True
        oc_result.error = None
        oc_result.data = {
            "companies": [
                {
                    "jurisdiction": "us_de",
                    "registered_address": "123 Main St, Delaware",
                    "company_number": "DE-987654",
                    "status": "active",
                    "incorporation_date": "2005-06-15",
                    "company_type": "LLC",
                },
                # Second entry — jurisdiction already found, so skip
                {
                    "jurisdiction": "us_ny",
                    "registered_address": "456 Broad St, NY",
                    "company_number": "NY-111222",
                    "status": "dissolved",  # status already set, skip
                    "incorporation_date": "2006-01-01",  # incorp already set, skip
                    "company_type": "Corporation",  # entity_type already set, skip
                },
            ],
            "officers": [],
        }

        async def _fake_crawler(platform, identifier):
            if platform == "company_opencorporates":
                return oc_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("Acme Corp", None)

        assert result.jurisdiction == "us_de"
        assert "123 Main St, Delaware" in result.registered_addresses
        assert "456 Broad St, NY" in result.registered_addresses
        assert "DE-987654" in result.company_numbers
        assert result.status == "active"
        assert result.incorporation_date == "2005-06-15"
        assert result.entity_type == "LLC"

    @pytest.mark.asyncio
    async def test_oc_jurisdiction_not_overwritten_when_passed(self):
        """If jurisdiction passed explicitly, OC jurisdiction is not used."""
        engine = UBODiscoveryEngine()

        oc_result = MagicMock()
        oc_result.found = True
        oc_result.error = None
        oc_result.data = {
            "companies": [{"jurisdiction": "us_de"}],
            "officers": [],
        }

        async def _fake_crawler(platform, identifier):
            if platform == "company_opencorporates":
                return oc_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("Acme Corp", "gb")

        # Passed jurisdiction takes precedence
        assert result.jurisdiction == "gb"
