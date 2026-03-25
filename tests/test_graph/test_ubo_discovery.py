"""Tests for modules/graph/ubo_discovery.py — UBODiscoveryEngine.

All external HTTP calls are mocked; no live DB or Tor required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.graph.ubo_discovery import (
    CrawledCompanyData,
    PersonRef,
    UBODiscoveryEngine,
    UBOResult,
    _normalise,
    _CORP_SUFFIXES,
    _MAX_COMPANY_QUEUE_SIZE,
)


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_normalise_strips_and_lowercases():
    assert _normalise("  Acme  Corp  ") == "acme corp"


def test_normalise_collapses_spaces():
    assert _normalise("Alpha   Beta") == "alpha beta"


def test_corp_suffixes_matches_llc():
    assert _CORP_SUFFIXES.search("Acme LLC")


def test_corp_suffixes_matches_holdings():
    assert _CORP_SUFFIXES.search("Alpha Holdings Ltd")


def test_corp_suffixes_no_match_natural_person():
    assert not _CORP_SUFFIXES.search("John Smith")


def test_corp_suffixes_matches_gmbh():
    assert _CORP_SUFFIXES.search("Berlin GmbH")


# ── UBODiscoveryEngine unit helpers ───────────────────────────────────────────


class TestIsCorporateName:
    def setup_method(self):
        self.engine = UBODiscoveryEngine()

    def test_true_for_llc(self):
        assert self.engine._is_corporate_name("Alpha LLC")

    def test_true_for_limited(self):
        assert self.engine._is_corporate_name("Beta Limited")

    def test_false_for_natural_person(self):
        assert not self.engine._is_corporate_name("Jane Doe")

    def test_true_for_corp(self):
        assert self.engine._is_corporate_name("Gamma Corp")

    def test_true_for_trust(self):
        assert self.engine._is_corporate_name("Family Trust")


# ── _merge_officers ────────────────────────────────────────────────────────────


def _make_crawler_result(found: bool, officers: list[dict], error: str | None = None):
    r = MagicMock()
    r.found = found
    r.error = error
    r.data = {"officers": officers}
    return r


class TestMergeOfficers:
    def setup_method(self):
        self.engine = UBODiscoveryEngine()

    def test_merges_single_source(self):
        oc = _make_crawler_result(True, [{"name": "Alice Smith", "position": "director"}])
        officers, sources, errors = self.engine._merge_officers(oc, None, None, None, "Acme")
        assert len(officers) == 1
        assert officers[0].name == "Alice Smith"
        assert "opencorporates" in sources

    def test_deduplicates_same_person_across_sources(self):
        oc = _make_crawler_result(True, [{"name": "Bob Jones", "position": "director"}])
        ch = _make_crawler_result(True, [{"name": "Bob Jones", "position": "officer"}])
        officers, sources, errors = self.engine._merge_officers(oc, ch, None, None, "Acme")
        assert len(officers) == 1
        # companies_house has higher reliability (0.90 vs 0.85), so it wins
        assert officers[0].source == "companies_house"

    def test_records_error_when_none(self):
        _, _, errors = self.engine._merge_officers(None, None, None, None, "Acme")
        assert any("opencorporates:no_response" in e for e in errors)
        assert any("gleif:no_response" in e for e in errors)

    def test_records_error_when_result_has_error(self):
        r = _make_crawler_result(False, [], error="timeout")
        _, _, errors = self.engine._merge_officers(r, None, None, None, "Acme")
        assert any("opencorporates:timeout" in e for e in errors)

    def test_empty_officers_when_none_found(self):
        oc = _make_crawler_result(False, [])
        officers, _, _ = self.engine._merge_officers(oc, None, None, None, "Acme")
        assert officers == []

    def test_gleif_adds_to_sources_when_found(self):
        gleif = _make_crawler_result(True, [])
        gleif.data = {"completions": [{"name": "acme", "lei": "LEI123"}]}
        _, sources, _ = self.engine._merge_officers(None, None, None, gleif, "Acme")
        assert "gleif" in sources

    def test_skips_officer_with_empty_name(self):
        oc = _make_crawler_result(True, [{"name": "", "position": "director"}])
        officers, _, _ = self.engine._merge_officers(oc, None, None, None, "Acme")
        assert officers == []


# ── _identify_ubos ────────────────────────────────────────────────────────────


class TestIdentifyUBOs:
    def setup_method(self):
        self.engine = UBODiscoveryEngine()

    def _person_node(self, pid: str, label: str, depth: int) -> dict:
        return {"id": pid, "type": "person", "label": label, "depth": depth, "risk_score": 0.0}

    def test_returns_candidate_for_each_person(self):
        pid = str(uuid.uuid4())
        nodes = {pid: self._person_node(pid, "Alice", 1)}
        candidates = self.engine._identify_ubos(nodes, [], {}, {pid: ["Acme", "Alice"]}, {pid: ["director"]}, {pid: ["us"]})
        assert len(candidates) == 1
        assert candidates[0].name == "Alice"

    def test_candidates_sorted_by_depth(self):
        p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
        nodes = {
            p1: self._person_node(p1, "Shallow", 1),
            p2: self._person_node(p2, "Deep", 3),
        }
        candidates = self.engine._identify_ubos(nodes, [], {}, {}, {}, {})
        assert candidates[0].depth <= candidates[1].depth

    def test_sanctions_hit_sets_risk_score_1(self):
        pid = str(uuid.uuid4())
        nodes = {pid: self._person_node(pid, "Villain", 1)}
        sanctions = {pid: [{"list_type": "ofac", "match_name": "Villain", "confidence": 0.95}]}
        candidates = self.engine._identify_ubos(nodes, [], sanctions, {}, {}, {})
        assert candidates[0].risk_score == 1.0
        assert len(candidates[0].sanctions_hits) == 1

    def test_confidence_decreases_with_depth(self):
        p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
        nodes = {
            p1: self._person_node(p1, "Shallow", 1),
            p2: self._person_node(p2, "Deep", 5),
        }
        candidates = self.engine._identify_ubos(nodes, [], {}, {}, {}, {})
        shallow = next(c for c in candidates if c.name == "Shallow")
        deep = next(c for c in candidates if c.name == "Deep")
        assert shallow.confidence > deep.confidence


# ── _compute_risk_flags ────────────────────────────────────────────────────────


class TestComputeRiskFlags:
    def setup_method(self):
        self.engine = UBODiscoveryEngine()

    def _cd(self, jur: str | None = None) -> CrawledCompanyData:
        return CrawledCompanyData(
            company_name="Acme", jurisdiction=jur, company_numbers=[], registered_addresses=[],
            status=None, incorporation_date=None, entity_type=None, lei=None,
            officers=[], sec_filings=[], has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )

    def test_shell_company_chain_flag(self):
        flags = self.engine._compute_risk_flags([self._cd(), self._cd(), self._cd()], [], False)
        assert "shell_company_chain" in flags

    def test_no_shell_flag_when_ubos_found(self):
        from modules.graph.ubo_discovery import UBOCandidate
        ubo = UBOCandidate(name="Alice", person_id="pid", chain=[], depth=1,
                           controlling_roles=[], jurisdictions=[], confidence=0.9,
                           is_natural_person=True, sanctions_hits=[], risk_score=0.0)
        flags = self.engine._compute_risk_flags([self._cd(), self._cd(), self._cd()], [ubo], False)
        assert "shell_company_chain" not in flags

    def test_offshore_jurisdiction_flag(self):
        flags = self.engine._compute_risk_flags([self._cd("cayman islands")], [], False)
        assert "offshore_jurisdiction" in flags

    def test_offshore_flag_short_code(self):
        flags = self.engine._compute_risk_flags([self._cd("vg")], [], False)
        assert "offshore_jurisdiction" in flags

    def test_circular_ownership_flag(self):
        flags = self.engine._compute_risk_flags([], [], True)
        assert "circular_ownership" in flags

    def test_sanctions_flag(self):
        from modules.graph.ubo_discovery import UBOCandidate
        ubo = UBOCandidate(name="X", person_id="p", chain=[], depth=1, controlling_roles=[],
                           jurisdictions=[], confidence=0.5, is_natural_person=True,
                           sanctions_hits=[{"list_type": "ofac"}], risk_score=1.0)
        flags = self.engine._compute_risk_flags([], [ubo], False)
        assert "person_on_sanctions_list" in flags

    def test_deduplicates_flags(self):
        flags = self.engine._compute_risk_flags(
            [self._cd("vg"), self._cd("ky")], [], False
        )
        assert flags.count("offshore_jurisdiction") == 1


# ── _run_single_crawler ───────────────────────────────────────────────────────


class TestRunSingleCrawler:
    @pytest.mark.asyncio
    async def test_returns_none_when_crawler_not_found(self):
        engine = UBODiscoveryEngine()
        with patch("modules.graph.ubo_discovery.get_crawler", return_value=None):
            result = await engine._run_single_crawler("nonexistent", "Acme Corp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        engine = UBODiscoveryEngine()
        mock_cls = MagicMock()
        mock_cls.return_value.scrape = AsyncMock(side_effect=RuntimeError("network error"))
        with patch("modules.graph.ubo_discovery.get_crawler", return_value=mock_cls):
            result = await engine._run_single_crawler("any_platform", "Acme Corp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        engine = UBODiscoveryEngine()
        fake_result = MagicMock()
        mock_cls = MagicMock()
        mock_cls.return_value.scrape = AsyncMock(return_value=fake_result)
        with patch("modules.graph.ubo_discovery.get_crawler", return_value=mock_cls):
            result = await engine._run_single_crawler("any_platform", "Acme Corp")
        assert result is fake_result


# ── crawl_company (public alias) ──────────────────────────────────────────────


class TestCrawlCompany:
    @pytest.mark.asyncio
    async def test_returns_crawled_company_data(self):
        engine = UBODiscoveryEngine()
        with patch.object(engine, "_run_single_crawler", new_callable=AsyncMock, return_value=None):
            result = await engine.crawl_company("Acme Corp", "us")
        assert isinstance(result, CrawledCompanyData)
        assert result.company_name == "Acme Corp"

    @pytest.mark.asyncio
    async def test_extracts_lei_from_gleif(self):
        engine = UBODiscoveryEngine()
        gleif_result = MagicMock()
        gleif_result.found = True
        gleif_result.error = None
        gleif_result.data = {"completions": [{"name": "acme corp", "lei": "LEI_TEST_123"}]}

        async def _fake_crawler(platform, identifier):
            if platform == "gov_gleif":
                return gleif_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("Acme Corp", None)
        assert result.lei == "LEI_TEST_123"

    @pytest.mark.asyncio
    async def test_has_proxy_when_sec_has_def14a(self):
        engine = UBODiscoveryEngine()
        sec_result = MagicMock()
        sec_result.found = True
        sec_result.error = None
        sec_result.data = {"officers": [], "filings": [{"form_type": "DEF 14A", "date": "2024-01-01"}]}

        async def _fake_crawler(platform, identifier):
            if platform == "company_sec":
                return sec_result
            return None

        with patch.object(engine, "_run_single_crawler", side_effect=_fake_crawler):
            result = await engine.crawl_company("BigCorp Inc", "us")
        assert result.has_proxy_filing is True


# ── discover (full BFS integration) ──────────────────────────────────────────


class TestDiscover:
    @pytest.mark.asyncio
    async def test_single_company_natural_person(self):
        """Root company → 1 natural person officer → UBO identified."""
        engine = UBODiscoveryEngine()
        pid = str(uuid.uuid4())

        # Mock _crawl_company to return one natural person officer
        person_officer = PersonRef(
            name="Alice Smith", source="opencorporates", position="director",
            jurisdiction="us", company_name="Acme Corp",
        )
        crawled = CrawledCompanyData(
            company_name="Acme Corp", jurisdiction="us", company_numbers=["12345"],
            registered_addresses=["123 Main St"], status="active",
            incorporation_date="2010-01-01", entity_type="LLC", lei=None,
            officers=[person_officer], sec_filings=[], has_proxy_filing=False,
            data_sources=["opencorporates"], crawl_errors=[],
        )
        with patch.object(engine, "_crawl_company", new_callable=AsyncMock, return_value=crawled), \
             patch.object(engine, "_upsert_person", new_callable=AsyncMock, return_value=pid), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={pid: []}):
            session = AsyncMock()
            result = await engine.discover("Acme Corp", "us", max_depth=3, session=session)

        assert isinstance(result, UBOResult)
        assert result.root_company == "Acme Corp"
        assert len(result.ubo_candidates) == 1
        assert result.ubo_candidates[0].name == "Alice Smith"
        assert result.partial is False

    @pytest.mark.asyncio
    async def test_corporate_officer_triggers_recursion(self):
        """Root company → corporate officer → recurse → natural person at depth 2."""
        engine = UBODiscoveryEngine()
        pid = str(uuid.uuid4())

        corp_officer = PersonRef(
            name="Shell Holdings LLC", source="opencorporates", position="shareholder",
            jurisdiction="vg", company_name="Acme Corp",
        )
        person_officer = PersonRef(
            name="Bob Jones", source="opencorporates", position="director",
            jurisdiction="vg", company_name="Shell Holdings LLC",
        )

        crawled_root = CrawledCompanyData(
            company_name="Acme Corp", jurisdiction="us", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[corp_officer], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )
        crawled_shell = CrawledCompanyData(
            company_name="Shell Holdings LLC", jurisdiction="vg", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[person_officer], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )

        call_count = [0]

        async def _fake_crawl(name, jur):
            call_count[0] += 1
            if "shell" in name.lower():
                return crawled_shell
            return crawled_root

        with patch.object(engine, "_crawl_company", side_effect=_fake_crawl), \
             patch.object(engine, "_upsert_person", new_callable=AsyncMock, return_value=pid), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={pid: []}):
            session = AsyncMock()
            result = await engine.discover("Acme Corp", "us", max_depth=5, session=session)

        assert call_count[0] >= 2  # root + shell
        assert any(c.name == "Bob Jones" for c in result.ubo_candidates)

    @pytest.mark.asyncio
    async def test_circular_ownership_detected(self):
        """Company A → Company B → Company A (circular)."""
        engine = UBODiscoveryEngine()

        corp_b = PersonRef(
            name="Beta Corp", source="opencorporates", position="shareholder",
            jurisdiction="us", company_name="Alpha Inc",
        )
        corp_a = PersonRef(
            name="Alpha Inc", source="opencorporates", position="shareholder",
            jurisdiction="us", company_name="Beta Corp",
        )

        crawled_a = CrawledCompanyData(
            company_name="Alpha Inc", jurisdiction="us", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[corp_b], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )
        crawled_b = CrawledCompanyData(
            company_name="Beta Corp", jurisdiction="us", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[corp_a], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )

        async def _fake_crawl(name, jur):
            if "beta" in name.lower():
                return crawled_b
            return crawled_a

        with patch.object(engine, "_crawl_company", side_effect=_fake_crawl), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={}):
            session = AsyncMock()
            result = await engine.discover("Alpha Inc", "us", max_depth=5, session=session)

        assert "circular_ownership" in result.risk_flags

    @pytest.mark.asyncio
    async def test_offshore_flag_raised(self):
        pid = str(uuid.uuid4())
        engine = UBODiscoveryEngine()
        person_officer = PersonRef(
            name="Offshore Person", source="opencorporates", position="director",
            jurisdiction="vg", company_name="Offshore Co",
        )
        crawled = CrawledCompanyData(
            company_name="Offshore Co", jurisdiction="vg", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[person_officer], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )
        with patch.object(engine, "_crawl_company", new_callable=AsyncMock, return_value=crawled), \
             patch.object(engine, "_upsert_person", new_callable=AsyncMock, return_value=pid), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={pid: []}):
            result = await engine.discover("Offshore Co", "vg", max_depth=3, session=AsyncMock())

        assert "offshore_jurisdiction" in result.risk_flags

    @pytest.mark.asyncio
    async def test_sanctions_hit_flagged(self):
        pid = str(uuid.uuid4())
        engine = UBODiscoveryEngine()
        person_officer = PersonRef(
            name="Sanctioned Person", source="opencorporates", position="director",
            jurisdiction="us", company_name="Acme Corp",
        )
        crawled = CrawledCompanyData(
            company_name="Acme Corp", jurisdiction="us", company_numbers=[],
            registered_addresses=[], status="active", incorporation_date=None,
            entity_type=None, lei=None, officers=[person_officer], sec_filings=[],
            has_proxy_filing=False, data_sources=[], crawl_errors=[],
        )
        sanctions_hit = {pid: [{"list_type": "ofac", "match_name": "Sanctioned Person", "confidence": 0.98}]}

        with patch.object(engine, "_crawl_company", new_callable=AsyncMock, return_value=crawled), \
             patch.object(engine, "_upsert_person", new_callable=AsyncMock, return_value=pid), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value=sanctions_hit):
            result = await engine.discover("Acme Corp", "us", max_depth=3, session=AsyncMock())

        assert "person_on_sanctions_list" in result.risk_flags
        assert result.ubo_candidates[0].risk_score == 1.0

    @pytest.mark.asyncio
    async def test_partial_result_when_queue_cap_hit(self):
        """Engine returns partial=True when _MAX_COMPANY_QUEUE_SIZE is exceeded."""
        engine = UBODiscoveryEngine()

        # Every crawl returns a new corporate officer to keep filling the queue
        call_count = [0]

        async def _infinite_crawl(name, jur):
            call_count[0] += 1
            sub_name = f"SubCorp{call_count[0]} LLC"
            officer = PersonRef(
                name=sub_name, source="opencorporates", position="shareholder",
                jurisdiction="us", company_name=name,
            )
            return CrawledCompanyData(
                company_name=name, jurisdiction="us", company_numbers=[],
                registered_addresses=[], status="active", incorporation_date=None,
                entity_type=None, lei=None, officers=[officer], sec_filings=[],
                has_proxy_filing=False, data_sources=[], crawl_errors=[],
            )

        with patch.object(engine, "_crawl_company", side_effect=_infinite_crawl), \
             patch.object(engine, "_check_sanctions", new_callable=AsyncMock, return_value={}):
            result = await engine.discover("Root Corp", "us", max_depth=100, session=AsyncMock())

        assert result.partial is True
