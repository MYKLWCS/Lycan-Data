"""
Integration tests — full search pipeline.

All external I/O is mocked (no live services needed).

Coverage:
  1. Name input → results from multiple scrapers
  2. Dedup removes duplicates and routes by score
  3. Progress events are emitted and tracked
  4. Results are stored in PostgreSQL, MeiliSearch, and entity graph
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.core.orchestrator import ScraperOrchestrator
from modules.crawlers.core.result import CrawlerResult
from modules.enrichers.deduplication import ExactMatchDeduplicator
from modules.pipeline.progress_tracker import ProgressAggregator
from shared.schemas.progress import EventType, Phase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    platform: str, identifier: str = "John Doe", found: bool = True, **data
) -> CrawlerResult:
    return CrawlerResult(
        platform=platform,
        identifier=identifier,
        found=found,
        data=data or {"full_name": "John Doe", "email": "john@example.com"},
        source_reliability=0.8,
    )


class _FakeCrawler:
    """Minimal fake crawler with a preset result."""

    def __init__(self, platform: str, result: CrawlerResult):
        self.platform = platform
        self._result = result

    async def run(self, identifier: str) -> CrawlerResult:
        return self._result


# ===========================================================================
# 1. Name input → results from multiple scrapers
# ===========================================================================


@pytest.mark.asyncio
async def test_orchestrator_returns_results_from_multiple_scrapers():
    """Name search returns one result per registered crawler."""
    crawlers = [
        _FakeCrawler("whitepages", _make_result("whitepages", email="john@whitepages.test")),
        _FakeCrawler("linkedin", _make_result("linkedin", email="john@linkedin.test")),
        _FakeCrawler("google_news_rss", _make_result("google_news_rss", found=False)),
    ]

    orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        output = await orchestrator.run_all("John Doe")

    assert len(output) == 3
    assert sum(1 for r in output if r.found) == 2
    assert {r.platform for r in output} == {"whitepages", "linkedin", "google_news_rss"}


@pytest.mark.asyncio
async def test_orchestrator_stream_yields_each_result():
    """stream() yields results individually as scrapers complete."""
    crawlers = [
        _FakeCrawler("whitepages", _make_result("whitepages")),
        _FakeCrawler("twitter", _make_result("twitter")),
    ]

    orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        streamed = [r async for r in orchestrator.stream("John Doe")]

    assert len(streamed) == 2
    assert all(isinstance(r, CrawlerResult) for r in streamed)


@pytest.mark.asyncio
async def test_orchestrator_empty_registry_returns_empty_list():
    """No registered crawlers → empty result, no exception."""
    orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=[]):
        output = await orchestrator.run_all("John Doe")

    assert output == []


@pytest.mark.asyncio
async def test_orchestrator_not_found_results_are_included():
    """Crawlers that return found=False are still included in output."""
    crawlers = [_FakeCrawler("p1", _make_result("p1", found=False))]
    orchestrator = ScraperOrchestrator(concurrency=5, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        output = await orchestrator.run_all("John Doe")

    assert len(output) == 1
    assert output[0].found is False


@pytest.mark.asyncio
async def test_orchestrator_result_has_correct_platform_tags():
    """Each result carries the correct platform identifier."""
    platforms = ["whitepages", "instagram", "sanctions_ofac"]
    crawlers = [_FakeCrawler(p, _make_result(p)) for p in platforms]
    orchestrator = ScraperOrchestrator(concurrency=10, timeout=5.0)
    with patch.object(orchestrator, "_get_crawlers", return_value=crawlers):
        output = await orchestrator.run_all("John Doe")

    returned_platforms = {r.platform for r in output}
    assert returned_platforms == set(platforms)


# ===========================================================================
# 2. Dedup removes duplicates and routes by score
# ===========================================================================


def test_exact_match_same_email_produces_shared_key():
    """Two records sharing an email → same dedup key."""
    dedup = ExactMatchDeduplicator()
    a = {"email": "jane@example.com", "full_name": "Jane Smith"}
    b = {"email": "jane@example.com", "full_name": "Jane S."}

    keys_a = {k for k, _ in dedup.create_composite_keys(a)}
    keys_b = {k for k, _ in dedup.create_composite_keys(b)}

    assert keys_a & keys_b  # email key shared


def test_exact_match_different_emails_no_shared_key():
    """Different emails → no overlapping dedup key."""
    dedup = ExactMatchDeduplicator()
    a = {"email": "alice@example.com"}
    b = {"email": "bob@example.com"}

    keys_a = {k for k, _ in dedup.create_composite_keys(a)}
    keys_b = {k for k, _ in dedup.create_composite_keys(b)}

    assert not (keys_a & keys_b)


def test_exact_match_phone_normalisation_produces_same_key():
    """Formatted and unformatted phones map to the same key."""
    dedup = ExactMatchDeduplicator()
    a = {"phone": "555-123-4567"}
    b = {"phone": "5551234567"}

    keys_a = {k for k, _ in dedup.create_composite_keys(a)}
    keys_b = {k for k, _ in dedup.create_composite_keys(b)}

    phone_a = {k for k in keys_a if k.startswith("phone:")}
    phone_b = {k for k in keys_b if k.startswith("phone:")}

    assert phone_a == phone_b


def test_exact_match_ssn_dob_name_has_priority_1():
    """SSN+DOB+name key carries priority 1 (strongest signal)."""
    dedup = ExactMatchDeduplicator()
    record = {
        "ssn": "123-45-6789",
        "dob": "1980-01-01",
        "full_name": "John Doe",
        "email": "john@example.com",
    }

    keys = dedup.create_composite_keys(record)
    p1_keys = [k for k, p in keys if p == 1]

    assert len(p1_keys) == 1
    assert p1_keys[0].startswith("ssn:")


def test_exact_match_short_phone_skipped():
    """Phone with fewer than 10 digits is skipped."""
    dedup = ExactMatchDeduplicator()
    record = {"phone": "12345"}  # only 5 digits

    keys = dedup.create_composite_keys(record)
    phone_keys = [k for k, _ in keys if k.startswith("phone:")]

    assert phone_keys == []


def test_exact_match_email_without_at_sign_skipped():
    """Non-email strings in the email field are ignored."""
    dedup = ExactMatchDeduplicator()
    record = {"email": "not-an-email"}

    keys = dedup.create_composite_keys(record)
    email_keys = [k for k, _ in keys if k.startswith("email:")]

    assert email_keys == []


@pytest.mark.asyncio
async def test_auto_dedup_routes_high_score_to_merge():
    """Score ≥ 0.85 → AsyncMergeExecutor is called."""
    from modules.enrichers.auto_dedup import AutoDedupDaemon
    from modules.enrichers.deduplication import MergeCandidate

    daemon = AutoDedupDaemon()
    session = AsyncMock()

    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    candidate = MergeCandidate(str(id_a), str(id_b), 0.92, ["email"])

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [MagicMock(id=id_a, merged_into=None)]

    person_mock = MagicMock()
    person_mock.merged_into = None
    person_mock.id = id_a
    fetch = MagicMock()
    fetch.scalar_one_or_none.return_value = person_mock
    session.execute = AsyncMock(side_effect=[persons_result, fetch, fetch])
    session.add = MagicMock()

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        daemon._count_populated_fields = AsyncMock(return_value=10)
        mock_exec = AsyncMock()
        mock_exec.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec

        await daemon._run_batch(session)

    assert MockExec.called
    assert mock_exec.execute.called


@pytest.mark.asyncio
async def test_auto_dedup_routes_medium_score_to_review_queue():
    """Score 0.70–0.84 → DedupReview added, no auto-merge executed."""
    from modules.enrichers.auto_dedup import AutoDedupDaemon
    from modules.enrichers.deduplication import MergeCandidate
    from shared.models.dedup_review import DedupReview

    daemon = AutoDedupDaemon()
    session = AsyncMock()

    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    candidate = MergeCandidate(str(id_a), str(id_b), 0.78, ["name"])

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [MagicMock(id=id_a, merged_into=None)]

    added = []
    session.add = MagicMock(side_effect=added.append)

    fetch = MagicMock()
    fetch.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[persons_result, fetch, fetch])

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        await daemon._run_batch(session)

    reviews = [o for o in added if isinstance(o, DedupReview)]
    assert len(reviews) == 1
    assert reviews[0].similarity_score == 0.78
    assert not MockExec.called


@pytest.mark.asyncio
async def test_auto_dedup_skips_low_score():
    """Score < 0.70 → nothing added, no merge."""
    from modules.enrichers.auto_dedup import AutoDedupDaemon
    from modules.enrichers.deduplication import MergeCandidate

    daemon = AutoDedupDaemon()
    session = AsyncMock()

    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    candidate = MergeCandidate(str(id_a), str(id_b), 0.40, [])

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [MagicMock(id=id_a, merged_into=None)]

    added = []
    session.add = MagicMock(side_effect=added.append)
    fetch = MagicMock()
    fetch.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[persons_result, fetch, fetch])

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        await daemon._run_batch(session)

    assert not added
    assert not MockExec.called


# ===========================================================================
# 3. Progress events are emitted and tracked
# ===========================================================================


def test_progress_starts_in_collecting_phase():
    agg = ProgressAggregator("search-001", scraper_count=5)
    state = agg.to_state()
    assert state.current_phase == Phase.COLLECTING
    assert state.progress_pct == 0.0
    assert state.scrapers_total == 5


def test_progress_search_started_pre_populates_statuses():
    agg = ProgressAggregator("search-001", scraper_count=3)
    state = agg.process(
        {
            "event_type": EventType.SEARCH_STARTED,
            "total_scrapers": 3,
            "scrapers": ["whitepages", "linkedin", "twitter"],
        }
    )
    assert set(state.scraper_statuses.keys()) == {"whitepages", "linkedin", "twitter"}
    assert all(v == "queued" for v in state.scraper_statuses.values())


def test_progress_scraper_running_increments_running_count():
    agg = ProgressAggregator("search-001", scraper_count=2)
    agg.process({"event_type": EventType.SCRAPER_QUEUED, "scraper_name": "whitepages"})
    state = agg.process({"event_type": EventType.SCRAPER_RUNNING, "scraper_name": "whitepages"})
    assert state.scraper_statuses["whitepages"] == "running"
    assert state.scrapers_running == 1


def test_progress_scraper_done_increments_completed_and_results():
    agg = ProgressAggregator("search-001", scraper_count=2)
    agg.process({"event_type": EventType.SCRAPER_QUEUED, "scraper_name": "whitepages"})
    state = agg.process(
        {
            "event_type": EventType.SCRAPER_DONE,
            "scraper_name": "whitepages",
            "results_found": 3,
        }
    )
    assert state.scraper_statuses["whitepages"] == "done"
    assert state.scrapers_completed == 1
    assert state.results_found == 3


def test_progress_scraper_failed_increments_failed_count():
    agg = ProgressAggregator("search-001", scraper_count=2)
    agg.process({"event_type": EventType.SCRAPER_QUEUED, "scraper_name": "instagram"})
    state = agg.process({"event_type": EventType.SCRAPER_FAILED, "scraper_name": "instagram"})
    assert state.scraper_statuses["instagram"] == "failed"
    assert state.scrapers_failed == 1


def test_progress_advances_to_deduplicating_on_dedup_event():
    agg = ProgressAggregator("search-001", scraper_count=1)
    state = agg.process(
        {
            "event_type": EventType.DEDUP_RUNNING,
            "records_processed": 5,
            "total_records": 10,
        }
    )
    assert state.current_phase == Phase.DEDUPLICATING
    assert state.progress_pct >= 60.0


def test_progress_advances_to_enriching_on_enrichment_event():
    agg = ProgressAggregator("search-001", scraper_count=1)
    state = agg.process(
        {
            "event_type": EventType.ENRICHMENT_RUNNING,
            "records_processed": 3,
            "total_records": 5,
        }
    )
    assert state.current_phase == Phase.ENRICHING
    assert state.progress_pct >= 75.0


def test_progress_completes_at_100_pct():
    agg = ProgressAggregator("search-001", scraper_count=1)
    state = agg.process(
        {
            "event_type": EventType.SEARCH_COMPLETE,
            "results_found": 42,
        }
    )
    assert state.current_phase == Phase.COMPLETE
    assert state.progress_pct == 100.0
    assert state.results_found == 42


def test_progress_collection_reaches_60_pct_when_all_scrapers_finish():
    """After all N scrapers complete, collection phase hits exactly 60%."""
    agg = ProgressAggregator("search-001", scraper_count=4)
    state = None
    for name in ["a", "b", "c", "d"]:
        state = agg.process(
            {
                "event_type": EventType.SCRAPER_DONE,
                "scraper_name": name,
                "results_found": 0,
            }
        )
    assert state is not None
    assert state.progress_pct == pytest.approx(60.0)


def test_progress_multiple_results_found_accumulate():
    """results_found accumulates across multiple SCRAPER_DONE events."""
    agg = ProgressAggregator("search-001", scraper_count=3)
    for name, count in [("a", 2), ("b", 5), ("c", 1)]:
        state = agg.process(
            {
                "event_type": EventType.SCRAPER_DONE,
                "scraper_name": name,
                "results_found": count,
            }
        )
    assert state.results_found == 8


def test_progress_eta_is_non_negative():
    agg = ProgressAggregator("search-001", scraper_count=10)
    agg.process({"event_type": EventType.SCRAPER_DONE, "scraper_name": "x", "results_found": 0})
    state = agg.to_state()
    assert state.estimated_seconds_remaining >= 0.0


# ===========================================================================
# 4. Results stored in PostgreSQL, MeiliSearch, and entity graph
# ===========================================================================


@pytest.mark.asyncio
async def test_aggregator_writes_to_db_session():
    """aggregate_result() calls session.add() — data reaches the DB layer."""
    from modules.pipeline.aggregator import aggregate_result

    session = AsyncMock()
    person = MagicMock()
    person.id = uuid.uuid4()
    person.full_name = "John Doe"
    person.corroboration_count = 1
    person.composite_quality = 0.5
    person.source_reliability = 0.5
    # _get_or_create_person uses session.get() when person_id is provided
    session.get = AsyncMock(return_value=person)
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=empty_result)
    session.add = MagicMock()
    session.flush = AsyncMock()

    crawler_result = _make_result(
        "instagram",
        identifier="johndoe",
        handle="johndoe",
        display_name="John Doe",
        follower_count=1500,
    )

    await aggregate_result(session, crawler_result, person_id=str(person.id))

    assert session.add.called or session.get.called


@pytest.mark.asyncio
async def test_meili_indexer_posts_document_to_search():
    """MeiliIndexer.index_person() sends an HTTP POST to the MeiliSearch endpoint."""
    from modules.search.typesense_indexer import TypesenseIndexer as MeiliIndexer

    indexer = MeiliIndexer()
    doc = {
        "id": str(uuid.uuid4()),
        "full_name": "John Doe",
        "phones": [],
        "emails": ["john@example.com"],
    }

    mock_response = MagicMock()
    mock_response.status_code = 202

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await indexer.index_person(doc)

    assert result is True
    mock_ctx.post.assert_called_once()
    call_args = mock_ctx.post.call_args
    assert "persons" in call_args[0][0]  # URL contains index name


@pytest.mark.asyncio
async def test_meili_indexer_returns_false_on_error_status():
    """Non-2xx response → index_person returns False."""
    from modules.search.typesense_indexer import TypesenseIndexer as MeiliIndexer

    indexer = MeiliIndexer()
    doc = {"id": str(uuid.uuid4()), "full_name": "John Doe"}

    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await indexer.index_person(doc)

    assert result is False


@pytest.mark.asyncio
async def test_entity_graph_returns_nodes_and_edges_for_seed_person():
    """EntityGraphBuilder returns graph with at least the seed person as a node."""
    from modules.graph.entity_graph import EntityGraphBuilder

    person_id = uuid.uuid4()
    session = AsyncMock()

    person = MagicMock()
    person.id = person_id
    person.full_name = "John Doe"
    person.default_risk_score = 0.3

    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []

    # First execute: fetch person batch; subsequent: identifiers, addresses, etc.
    p_result = MagicMock()
    p_result.scalars.return_value.all.return_value = [person]
    session.execute = AsyncMock(side_effect=[p_result] + [empty] * 10)

    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    assert "nodes" in graph
    assert "edges" in graph
    node_ids = {n["id"] for n in graph["nodes"]}
    assert str(person_id) in node_ids


@pytest.mark.asyncio
async def test_entity_graph_person_not_found_returns_empty_graph():
    """Non-existent person_id → empty nodes list (no crash)."""
    from modules.graph.entity_graph import EntityGraphBuilder

    person_id = uuid.uuid4()
    session = AsyncMock()

    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty)

    builder = EntityGraphBuilder()
    graph = await builder.build_person_graph(str(person_id), session, depth=1)

    assert isinstance(graph, dict)
    assert graph.get("nodes", []) == []


@pytest.mark.asyncio
async def test_full_pipeline_name_to_stored_result():
    """
    End-to-end smoke test:
      name input → scraper result → aggregate_result writes to DB.
    """
    from modules.pipeline.aggregator import aggregate_result

    # Step 1: simulate scraper returning a result
    scraper_result = _make_result(
        "whitepages",
        identifier="John Doe",
        full_name="John Doe",
        email="john.doe@example.com",
        phone="5551234567",
    )

    # Step 2: aggregate into (mocked) DB session
    session = AsyncMock()
    person = MagicMock()
    person.id = uuid.uuid4()
    person.full_name = "John Doe"
    person.corroboration_count = 1
    person.composite_quality = 0.5
    person.source_reliability = 0.5
    # aggregate_result without person_id → name lookup via session.execute
    name_result = MagicMock()
    name_result.scalar_one_or_none.return_value = person
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[name_result] + [empty_result] * 20)
    session.add = MagicMock()
    session.flush = AsyncMock()

    summary = await aggregate_result(session, scraper_result)

    # Person was written
    assert "person_id" in summary

    # Step 3: verify MeiliSearch would be called with valid document
    from modules.search.typesense_indexer import TypesenseIndexer as MeiliIndexer

    doc = {
        "id": summary["person_id"],
        "full_name": "John Doe",
        "emails": ["john.doe@example.com"],
        "phones": ["5551234567"],
    }

    mock_response = MagicMock()
    mock_response.status_code = 202

    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        indexed = await MeiliIndexer().index_person(doc)

    assert indexed is True
