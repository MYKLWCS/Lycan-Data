"""Tests for GenealogyEnricher — 100% coverage with DB and crawler I/O mocked."""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date


# ---------------------------------------------------------------------------
# compute_confidence
# ---------------------------------------------------------------------------
class TestComputeConfidence:
    def test_zero_sources(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([]) == 0.0

    def test_one_source(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{}]) == pytest.approx(0.40)

    def test_two_sources(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{}, {}]) == pytest.approx(0.72)

    def test_three_sources(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{}, {}, {}]) == pytest.approx(0.92)

    def test_government_bonus_one_source(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{}], is_government=True) == pytest.approx(0.55)

    def test_government_bonus_three_sources_capped(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        score = compute_confidence([{}, {}, {}], is_government=True)
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_family_rel_types(self):
        from modules.enrichers.genealogy_enricher import FAMILY_REL_TYPES
        assert "parent_of" in FAMILY_REL_TYPES
        assert "spouse_of" in FAMILY_REL_TYPES
        assert "sibling_of" in FAMILY_REL_TYPES
        assert len(FAMILY_REL_TYPES) == 11

    def test_ancestor_types(self):
        from modules.enrichers.genealogy_enricher import ANCESTOR_TYPES
        assert "parent_of" in ANCESTOR_TYPES
        assert "grandparent_of" in ANCESTOR_TYPES
        assert "step_parent_of" in ANCESTOR_TYPES

    def test_government_platforms(self):
        from modules.enrichers.genealogy_enricher import GOVERNMENT_PLATFORMS
        assert "census_records" in GOVERNMENT_PLATFORMS
        assert "vitals_records" in GOVERNMENT_PLATFORMS


# ---------------------------------------------------------------------------
# Helpers for building mock session/person
# ---------------------------------------------------------------------------
def _make_person(name="John Smith", dob=None):
    person = MagicMock()
    person.id = uuid.uuid4()
    person.full_name = name
    person.date_of_birth = dob
    return person


def _make_session_factory(scalars_return=None):
    """Build an async context-manager session factory."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = scalars_return or []
    result_mock.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=result_mock)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


# ---------------------------------------------------------------------------
# _parse_relatives
# ---------------------------------------------------------------------------
class TestParseRelatives:
    @pytest.fixture
    def enricher(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        return GenealogyEnricher(factory)

    def test_parses_relationships(self, enricher):
        source_results = [
            {
                "platform": "census_records",
                "data": {
                    "records": [
                        {
                            "relationships": [
                                {"type": "parent_child", "person2": "Mary Smith"}
                            ]
                        }
                    ]
                }
            }
        ]
        relatives = enricher._parse_relatives(source_results)
        assert any(r["name"] == "Mary Smith" for r in relatives)

    def test_parses_geni_profiles(self, enricher):
        source_results = [
            {
                "platform": "geni_public",
                "data": {
                    "profiles": [{"name": "Jane Doe"}],
                    "records": [],
                }
            }
        ]
        relatives = enricher._parse_relatives(source_results)
        assert any(r["name"] == "Jane Doe" for r in relatives)

    def test_empty_name_skipped(self, enricher):
        source_results = [
            {
                "platform": "census_records",
                "data": {
                    "records": [
                        {"relationships": [{"type": "parent_child", "person2": ""}]}
                    ]
                }
            }
        ]
        relatives = enricher._parse_relatives(source_results)
        assert relatives == []

    def test_whitespace_name_included(self, enricher):
        """Whitespace name passes truthy check (consistent with source behavior)."""
        source_results = [
            {
                "platform": "census_records",
                "data": {
                    "records": [
                        {"relationships": [{"type": "parent_child", "person2": "   "}]}
                    ]
                }
            }
        ]
        relatives = enricher._parse_relatives(source_results)
        # Whitespace is truthy — included
        assert len(relatives) == 1

    def test_empty_sources(self, enricher):
        assert enricher._parse_relatives([]) == []


# ---------------------------------------------------------------------------
# build_tree
# ---------------------------------------------------------------------------
class TestBuildTree:
    @pytest.fixture
    def enricher(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        # _find_or_create_person returns a new UUID each call
        async def fake_find_or_create(name):
            return str(uuid.uuid4())
        e = GenealogyEnricher(factory)
        e._find_or_create_person = fake_find_or_create
        return e

    @pytest.mark.asyncio
    async def test_empty_relatives_tree(self, enricher):
        person = _make_person()
        tree = await enricher.build_tree(person, [])
        assert len(tree["nodes"]) == 1
        assert tree["edges"] == []
        assert tree["depth_ancestors"] == 0
        assert tree["depth_descendants"] == 0

    @pytest.mark.asyncio
    async def test_ancestor_edge(self, enricher):
        person = _make_person()
        relatives = [{"name": "Father Smith", "rel_type": "parent_of"}]
        tree = await enricher.build_tree(person, relatives)
        assert len(tree["nodes"]) == 2
        assert len(tree["edges"]) == 1
        assert tree["depth_ancestors"] >= 1

    @pytest.mark.asyncio
    async def test_descendant_edge(self, enricher):
        person = _make_person()
        relatives = [{"name": "Child Smith", "rel_type": "child_of"}]
        tree = await enricher.build_tree(person, relatives)
        assert len(tree["nodes"]) == 2
        assert tree["depth_descendants"] >= 1

    @pytest.mark.asyncio
    async def test_depth_limit_ancestor(self, enricher):
        """Relatives beyond generation -8 are skipped."""
        person = _make_person()
        # Build 10 ancestor relatives to exceed limit
        relatives = [{"name": f"Ancestor{i}", "rel_type": "parent_of"} for i in range(10)]
        tree = await enricher.build_tree(person, relatives)
        # Some should be skipped due to depth limit
        assert len(tree["nodes"]) <= 10

    @pytest.mark.asyncio
    async def test_duplicate_relative_skipped(self, enricher):
        person = _make_person()
        # Same name twice
        relatives = [
            {"name": "Father Smith", "rel_type": "parent_of"},
            {"name": "Father Smith", "rel_type": "parent_of"},
        ]
        tree = await enricher.build_tree(person, relatives)
        # Second should be skipped by 'processed' set
        assert len(tree["nodes"]) == 2


# ---------------------------------------------------------------------------
# _compute_depths
# ---------------------------------------------------------------------------
class TestComputeDepths:
    @pytest.fixture
    def enricher(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        return GenealogyEnricher(factory)

    def test_mixed_generations(self, enricher):
        nodes = {
            "a": {"generation": 0},
            "b": {"generation": -1},
            "c": {"generation": -3},
            "d": {"generation": 2},
        }
        depths = enricher._compute_depths(nodes)
        assert depths["ancestors"] == 3
        assert depths["descendants"] == 2

    def test_all_zero(self, enricher):
        nodes = {"a": {"generation": 0}}
        depths = enricher._compute_depths(nodes)
        assert depths["ancestors"] == 0
        assert depths["descendants"] == 0


# ---------------------------------------------------------------------------
# _find_or_create_person
# ---------------------------------------------------------------------------
class TestFindOrCreatePerson:
    @pytest.fixture
    def enricher_with_factory(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        return GenealogyEnricher(factory), session, factory

    @pytest.mark.asyncio
    async def test_existing_person_found(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        existing = MagicMock()
        existing.id = uuid.UUID("12345678-1234-5678-1234-567812345678")

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = existing
        session.execute = AsyncMock(return_value=result_mock)

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        enricher = GenealogyEnricher(factory)
        pid = await enricher._find_or_create_person("John Smith")
        assert pid == "12345678-1234-5678-1234-567812345678"

    @pytest.mark.asyncio
    async def test_creates_new_person(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        new_person = MagicMock()
        new_person.id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

        call_count = 0

        session = AsyncMock()

        async def mock_execute(stmt):
            result_mock = MagicMock()
            result_mock.scalars.return_value.first.return_value = None
            return result_mock

        session.execute = AsyncMock(side_effect=mock_execute)
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = new_person.id

        session.refresh = AsyncMock(side_effect=mock_refresh)

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        enricher = GenealogyEnricher(factory)
        pid = await enricher._find_or_create_person("New Person")
        assert session.add.called

    @pytest.mark.asyncio
    async def test_race_condition_fallback(self):
        """On commit failure, fetch again; if still not found, use name as ID."""
        from modules.enrichers.genealogy_enricher import GenealogyEnricher

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=result_mock)
        session.add = MagicMock()
        session.commit = AsyncMock(side_effect=Exception("unique violation"))
        session.rollback = AsyncMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        enricher = GenealogyEnricher(factory)
        pid = await enricher._find_or_create_person("Race Person")
        assert pid == "Race Person"  # fallback

    @pytest.mark.asyncio
    async def test_race_condition_finds_after_rollback(self):
        """On commit failure, fetch again finds existing person."""
        from modules.enrichers.genealogy_enricher import GenealogyEnricher

        existing = MagicMock()
        existing.id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        call_count = 0

        session = AsyncMock()

        async def mock_execute(stmt):
            nonlocal call_count
            result_mock = MagicMock()
            # First call returns None, second returns existing
            if call_count == 0:
                result_mock.scalars.return_value.first.return_value = None
            else:
                result_mock.scalars.return_value.first.return_value = existing
            call_count += 1
            return result_mock

        session.execute = AsyncMock(side_effect=mock_execute)
        session.add = MagicMock()
        session.commit = AsyncMock(side_effect=Exception("unique violation"))
        session.rollback = AsyncMock()

        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        enricher = GenealogyEnricher(factory)
        pid = await enricher._find_or_create_person("Race Person 2")
        assert pid == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# _run_genealogy_crawlers
# ---------------------------------------------------------------------------
class TestRunGenealogycrawlers:
    @pytest.mark.asyncio
    async def test_found_results(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        mock_result = MagicMock()
        mock_result.found = True
        mock_result.data = {"records": [{"full_name": "John"}]}

        mock_crawler_instance = MagicMock()
        mock_crawler_instance.scrape = AsyncMock(return_value=mock_result)
        mock_crawler_cls = MagicMock(return_value=mock_crawler_instance)

        with patch("modules.crawlers.registry.get_crawler", return_value=mock_crawler_cls):
            results = await enricher._run_genealogy_crawlers("John Smith:1920")

        assert len(results) == 5  # 5 platforms
        assert all(r["platform"] in ["ancestry_hints", "census_records", "geni_public",
                                      "newspapers_archive", "vitals_records"] for r in results)

    @pytest.mark.asyncio
    async def test_not_found_excluded(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        mock_result = MagicMock()
        mock_result.found = False

        mock_crawler_instance = MagicMock()
        mock_crawler_instance.scrape = AsyncMock(return_value=mock_result)
        mock_crawler_cls = MagicMock(return_value=mock_crawler_instance)

        with patch("modules.crawlers.registry.get_crawler", return_value=mock_crawler_cls):
            results = await enricher._run_genealogy_crawlers("John Smith:1920")

        assert results == []

    @pytest.mark.asyncio
    async def test_none_crawler_skipped(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        with patch("modules.crawlers.registry.get_crawler", return_value=None):
            results = await enricher._run_genealogy_crawlers("John Smith:1920")

        assert results == []

    @pytest.mark.asyncio
    async def test_crawler_exception_handled(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        mock_crawler_instance = MagicMock()
        mock_crawler_instance.scrape = AsyncMock(side_effect=Exception("network error"))
        mock_crawler_cls = MagicMock(return_value=mock_crawler_instance)

        with patch("modules.crawlers.registry.get_crawler", return_value=mock_crawler_cls):
            results = await enricher._run_genealogy_crawlers("John Smith:1920")

        assert results == []


# ---------------------------------------------------------------------------
# _save_tree
# ---------------------------------------------------------------------------
class TestSaveTree:
    @pytest.mark.asyncio
    async def test_saves_snapshot(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        person = _make_person()
        tree = {"nodes": [], "edges": [], "depth_ancestors": 2, "depth_descendants": 1}
        source_results = [{"platform": "census_records", "data": {}}]

        await enricher._save_tree(person, tree, source_results)
        assert session.add.called
        assert session.commit.called

    @pytest.mark.asyncio
    async def test_government_platform_bonus(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        person = _make_person()
        tree = {"nodes": [], "edges": [], "depth_ancestors": 0, "depth_descendants": 0}
        source_results = [{"platform": "vitals_records", "data": {}}]

        # Should not raise
        await enricher._save_tree(person, tree, source_results)
        assert session.commit.called


# ---------------------------------------------------------------------------
# _process_pending
# ---------------------------------------------------------------------------
class TestProcessPending:
    @pytest.mark.asyncio
    async def test_empty_persons(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory(scalars_return=[])
        enricher = GenealogyEnricher(factory)

        # Should run without error on empty list
        with patch.object(enricher, "_enrich_person", new=AsyncMock()) as mock_enrich:
            await enricher._process_pending()
        mock_enrich.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_persons(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher

        person = _make_person("Alice Smith", dob=date(1990, 5, 1))
        factory, session = _make_session_factory(scalars_return=[person])
        enricher = GenealogyEnricher(factory)

        with patch.object(enricher, "_enrich_person", new=AsyncMock()) as mock_enrich:
            await enricher._process_pending()
        mock_enrich.assert_called_once_with(person)

    @pytest.mark.asyncio
    async def test_exception_per_person_handled(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher

        person = _make_person()
        factory, session = _make_session_factory(scalars_return=[person])
        enricher = GenealogyEnricher(factory)

        with patch.object(enricher, "_enrich_person", new=AsyncMock(side_effect=Exception("fail"))):
            # Should not raise — per-person exception is caught
            await enricher._process_pending()


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------
class TestStart:
    @pytest.mark.asyncio
    async def test_start_calls_process_pending(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        call_count = 0

        async def mock_process():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt("stop test")

        with patch.object(enricher, "_process_pending", new=mock_process):
            with patch("asyncio.sleep", new=AsyncMock()):
                try:
                    await enricher.start()
                except KeyboardInterrupt:
                    pass

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_start_continues_on_exception(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, _ = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        call_count = 0

        async def mock_process():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            if call_count >= 2:
                raise KeyboardInterrupt("stop")

        with patch.object(enricher, "_process_pending", new=mock_process):
            with patch("asyncio.sleep", new=AsyncMock()):
                try:
                    await enricher.start()
                except KeyboardInterrupt:
                    pass

        assert call_count >= 2


# ---------------------------------------------------------------------------
# _enrich_person integration
# ---------------------------------------------------------------------------
class TestEnrichPerson:
    @pytest.mark.asyncio
    async def test_enrich_person_with_dob(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        person = _make_person("John Smith", dob=date(1920, 6, 15))

        with patch.object(enricher, "_run_genealogy_crawlers", new=AsyncMock(return_value=[])), \
             patch.object(enricher, "_save_tree", new=AsyncMock()) as mock_save:
            await enricher._enrich_person(person)
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_person_without_dob(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        factory, session = _make_session_factory()
        enricher = GenealogyEnricher(factory)

        person = _make_person("Jane Doe", dob=None)

        with patch.object(enricher, "_run_genealogy_crawlers", new=AsyncMock(return_value=[])), \
             patch.object(enricher, "_save_tree", new=AsyncMock()) as mock_save:
            await enricher._enrich_person(person)
        mock_save.assert_called_once()
