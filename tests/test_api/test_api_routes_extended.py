"""
Extended API route tests — crawls, dedup, enrichment, export, financial, graph, marketing, patterns.

All DB sessions and external services are mocked via FastAPI dependency overrides and
unittest.mock.patch. Tests verify routing, HTTP status codes, response shape, and error
branches (400, 404, 409, 422, 500) only — business logic is covered by unit tests
elsewhere.

URL structure (from api/main.py):
  /crawls      → api/routes/crawls.py
  /dedup       → api/routes/dedup.py
  /enrich      → api/routes/enrichment.py
  /export      → api/routes/export.py
  /financial   → api/routes/financial.py
  /graph       → api/routes/graph.py
  /marketing   → api/routes/marketing.py
  /patterns    → api/routes/patterns.py
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"
BAD_UUID = "not-a-uuid"

# ---------------------------------------------------------------------------
# Session factory helpers (mirror the style of existing test_routes.py)
# ---------------------------------------------------------------------------


def _make_session(execute_return=None, scalars_return=None, get_return=None):
    """Build an AsyncMock session with sensible defaults for all common call patterns."""
    session = AsyncMock()

    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]), first=MagicMock(return_value=None))),
        scalar_one_or_none=MagicMock(return_value=None),
        mappings=MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                one=MagicMock(return_value={}),
            )
        ),
    )
    session.execute.return_value = execute_return if execute_return is not None else default_exec

    default_scalars = MagicMock(all=MagicMock(return_value=[]), first=MagicMock(return_value=None))
    session.scalars.return_value = scalars_return if scalars_return is not None else default_scalars

    session.get.return_value = get_return  # None → 404 by default
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()

    return session


def _override_db(session):
    """Return a FastAPI dependency override that yields the given mock session."""

    async def _dep():
        yield session

    return _dep


# ---------------------------------------------------------------------------
# Autouse fixture — clears overrides between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Reusable client builder
# ---------------------------------------------------------------------------


def _client(session=None):
    if session is not None:
        app.dependency_overrides[db_session] = _override_db(session)
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# /crawls  (api/routes/crawls.py)
# ===========================================================================


class TestCrawlsList:
    def test_list_crawls_empty(self):
        """GET /crawls returns empty list when no jobs exist."""
        client = _client(_make_session())
        r = client.get("/crawls")
        assert r.status_code == 200
        data = r.json()
        assert data["jobs"] == []
        assert data["total"] == 0

    def test_list_crawls_with_limit_param(self):
        """limit query param is respected (value within allowed range)."""
        client = _client(_make_session())
        r = client.get("/crawls?limit=10")
        assert r.status_code == 200

    def test_list_crawls_limit_too_large_rejected(self):
        """limit > 200 triggers a 422 validation error."""
        client = _client(_make_session())
        r = client.get("/crawls?limit=999")
        assert r.status_code == 422

    def test_list_crawls_status_filter(self):
        """status query param is forwarded to the DB query without error."""
        client = _client(_make_session())
        r = client.get("/crawls?status=failed")
        assert r.status_code == 200

    def test_list_crawls_returns_job_list_when_populated(self):
        """Response includes serialised jobs when DB returns rows."""
        mock_job = MagicMock()
        # Make __table__.columns iterable with one column
        col = MagicMock()
        col.name = "id"
        mock_job.__table__ = MagicMock()
        mock_job.__table__.columns = [col]
        mock_job.id = uuid.UUID(VALID_UUID)

        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_job]
        session = _make_session(execute_return=exec_result)
        client = _client(session)
        r = client.get("/crawls")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert len(data["jobs"]) == 1


class TestGetCrawl:
    def test_get_crawl_valid_uuid_not_found(self):
        """GET /crawls/{uuid} returns 404 when the job does not exist."""
        client = _client(_make_session(get_return=None))
        r = client.get(f"/crawls/{VALID_UUID}")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_get_crawl_invalid_uuid_returns_400(self):
        """GET /crawls/{bad} returns 400 for malformed UUID."""
        client = _client(_make_session())
        r = client.get(f"/crawls/{BAD_UUID}")
        assert r.status_code == 400
        assert "UUID" in r.json()["detail"]

    def test_get_crawl_found_returns_dict(self):
        """GET /crawls/{uuid} returns serialised job dict when found."""
        mock_job = MagicMock()
        col = MagicMock()
        col.name = "id"
        mock_job.__table__ = MagicMock()
        mock_job.__table__.columns = [col]
        mock_job.id = uuid.UUID(VALID_UUID)

        session = _make_session(get_return=mock_job)
        client = _client(session)
        r = client.get(f"/crawls/{VALID_UUID}")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


class TestRetryCrawl:
    def test_retry_crawl_invalid_uuid_returns_400(self):
        """POST /crawls/retry?job_id=bad returns 400."""
        client = _client(_make_session())
        r = client.post(f"/crawls/retry?job_id={BAD_UUID}")
        assert r.status_code == 400

    def test_retry_crawl_not_found_returns_404(self):
        """POST /crawls/retry?job_id=uuid returns 404 when job absent."""
        client = _client(_make_session(get_return=None))
        r = client.post(f"/crawls/retry?job_id={VALID_UUID}")
        assert r.status_code == 404

    def test_retry_crawl_non_retryable_status_returns_409(self):
        """POST /crawls/retry returns 409 when job status is not retryable (e.g. done)."""
        mock_job = MagicMock()
        mock_job.status = "done"
        session = _make_session(get_return=mock_job)
        client = _client(session)
        r = client.post(f"/crawls/retry?job_id={VALID_UUID}")
        assert r.status_code == 409
        assert "not retryable" in r.json()["detail"].lower()

    def test_retry_crawl_failed_job_re_enqueues(self):
        """POST /crawls/retry re-enqueues a failed job and returns pending status."""
        mock_job = MagicMock()
        mock_job.status = "failed"
        mock_job.meta = {"platform": "twitter"}
        mock_job.seed_identifier = "user123"
        mock_job.person_id = uuid.UUID(VALID_UUID)
        mock_job.id = uuid.UUID(VALID_UUID)
        mock_job.job_type = "twitter"

        session = _make_session(get_return=mock_job)
        client = _client(session)

        with patch("modules.dispatcher.dispatcher.dispatch_job", new=AsyncMock(return_value=None)):
            r = client.post(f"/crawls/retry?job_id={VALID_UUID}")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert data["job_id"] == VALID_UUID

    def test_retry_crawl_blocked_status_is_retryable(self):
        """POST /crawls/retry also accepts blocked status."""
        mock_job = MagicMock()
        mock_job.status = "blocked"
        mock_job.meta = {}
        mock_job.seed_identifier = ""
        mock_job.person_id = None
        mock_job.id = uuid.UUID(VALID_UUID)
        mock_job.job_type = "linkedin"

        session = _make_session(get_return=mock_job)
        client = _client(session)

        with patch("modules.dispatcher.dispatcher.dispatch_job", new=AsyncMock(return_value=None)):
            r = client.post(f"/crawls/retry?job_id={VALID_UUID}")

        assert r.status_code == 200

    def test_retry_crawl_rate_limited_status_is_retryable(self):
        """POST /crawls/retry also accepts rate_limited status."""
        mock_job = MagicMock()
        mock_job.status = "rate_limited"
        mock_job.meta = {}
        mock_job.seed_identifier = "test"
        mock_job.person_id = None
        mock_job.id = uuid.UUID(VALID_UUID)
        mock_job.job_type = "instagram"

        session = _make_session(get_return=mock_job)
        client = _client(session)

        with patch("modules.dispatcher.dispatcher.dispatch_job", new=AsyncMock(return_value=None)):
            r = client.post(f"/crawls/retry?job_id={VALID_UUID}")

        assert r.status_code == 200


# ===========================================================================
# /dedup  (api/routes/dedup.py)
# ===========================================================================


class TestDedupMerge:
    def test_merge_invalid_canonical_uuid_returns_400(self):
        """POST /dedup/merge with bad canonical_id returns 400."""
        client = _client(_make_session())
        r = client.post(
            "/dedup/merge",
            json={"canonical_id": BAD_UUID, "duplicate_id": VALID_UUID},
        )
        assert r.status_code == 400

    def test_merge_invalid_duplicate_uuid_returns_400(self):
        """POST /dedup/merge with bad duplicate_id returns 400."""
        client = _client(_make_session())
        r = client.post(
            "/dedup/merge",
            json={"canonical_id": VALID_UUID, "duplicate_id": BAD_UUID},
        )
        assert r.status_code == 400

    def test_merge_missing_body_returns_422(self):
        """POST /dedup/merge without required fields returns 422."""
        client = _client(_make_session())
        r = client.post("/dedup/merge", json={})
        assert r.status_code == 422

    def test_merge_executor_returns_merged_true(self):
        """POST /dedup/merge returns 200 when merge succeeds."""
        client = _client(_make_session())
        other_id = str(uuid.uuid4())

        with patch(
            "api.routes.dedup.AsyncMergeExecutor.execute",
            new=AsyncMock(return_value={"merged": True, "canonical_id": VALID_UUID}),
        ):
            r = client.post(
                "/dedup/merge",
                json={"canonical_id": VALID_UUID, "duplicate_id": other_id},
            )
        assert r.status_code == 200
        assert r.json()["merged"] is True

    def test_merge_executor_returns_merged_false_gives_400(self):
        """POST /dedup/merge returns 400 when executor reports merge failure."""
        client = _client(_make_session())
        other_id = str(uuid.uuid4())

        with patch(
            "api.routes.dedup.AsyncMergeExecutor.execute",
            new=AsyncMock(return_value={"merged": False, "error": "Records diverge too much"}),
        ):
            r = client.post(
                "/dedup/merge",
                json={"canonical_id": VALID_UUID, "duplicate_id": other_id},
            )
        assert r.status_code == 400
        assert "Records diverge" in r.json()["detail"]

    def test_merge_executor_raises_gives_500(self):
        """POST /dedup/merge returns 500 when executor raises an exception."""
        client = _client(_make_session())
        other_id = str(uuid.uuid4())

        with patch(
            "api.routes.dedup.AsyncMergeExecutor.execute",
            new=AsyncMock(side_effect=RuntimeError("DB exploded")),
        ):
            r = client.post(
                "/dedup/merge",
                json={"canonical_id": VALID_UUID, "duplicate_id": other_id},
            )
        assert r.status_code == 500


class TestDedupBatchCandidates:
    def test_batch_candidates_empty_list(self):
        """POST /dedup/batch-candidates with empty list returns no candidates."""
        client = _client(_make_session())
        with patch(
            "api.routes.dedup.score_person_dedup",
            new=AsyncMock(return_value=[]),
        ):
            r = client.post("/dedup/batch-candidates", json={"person_ids": []})
        assert r.status_code == 200
        data = r.json()
        assert data["candidates"] == []
        assert data["count"] == 0

    def test_batch_candidates_over_100_returns_400(self):
        """POST /dedup/batch-candidates with >100 IDs returns 400."""
        client = _client(_make_session())
        too_many = [str(uuid.uuid4()) for _ in range(101)]
        r = client.post("/dedup/batch-candidates", json={"person_ids": too_many})
        assert r.status_code == 400
        assert "100" in r.json()["detail"]

    def test_batch_candidates_bad_uuid_in_list_returns_400(self):
        """POST /dedup/batch-candidates returns 400 if any ID is malformed."""
        client = _client(_make_session())
        r = client.post(
            "/dedup/batch-candidates",
            json={"person_ids": [VALID_UUID, BAD_UUID]},
        )
        assert r.status_code == 400

    def test_batch_candidates_missing_body_returns_422(self):
        """POST /dedup/batch-candidates without body returns 422."""
        client = _client(_make_session())
        r = client.post("/dedup/batch-candidates", json={})
        assert r.status_code == 422

    def test_batch_candidates_dedup_error_skips_person(self):
        """score_person_dedup failures are swallowed; other persons still processed."""
        client = _client(_make_session())
        good_id = str(uuid.uuid4())
        bad_id = str(uuid.uuid4())

        async def _score_side_effect(pid, session):
            if pid == bad_id:
                raise RuntimeError("lookup failed")
            return []

        with patch(
            "api.routes.dedup.score_person_dedup",
            side_effect=_score_side_effect,
        ):
            r = client.post(
                "/dedup/batch-candidates",
                json={"person_ids": [good_id, bad_id]},
            )
        assert r.status_code == 200
        assert r.json()["persons_scanned"] == 2

    def test_batch_candidates_deduplicates_pairs(self):
        """Symmetric pairs are deduplicated so the same pair is only returned once."""
        client = _client(_make_session())
        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())

        cand = MagicMock()
        cand.id_a = id_a
        cand.id_b = id_b
        cand.similarity_score = 0.95
        cand.match_reasons = ["same_email"]

        async def _score(pid, session):
            return [cand]

        with patch(
            "api.routes.dedup.score_person_dedup",
            side_effect=_score,
        ):
            r = client.post(
                "/dedup/batch-candidates",
                json={"person_ids": [id_a, id_b]},
            )
        assert r.status_code == 200
        # Even though both persons returned the same pair, it appears once
        assert r.json()["count"] == 1


class TestDedupCandidatesSingle:
    def test_candidates_invalid_uuid_returns_400(self):
        """POST /dedup/{bad}/candidates returns 400."""
        client = _client(_make_session())
        r = client.post(f"/dedup/{BAD_UUID}/candidates")
        assert r.status_code == 400

    def test_candidates_empty_result(self):
        """POST /dedup/{uuid}/candidates returns empty candidates list."""
        client = _client(_make_session())
        with patch(
            "api.routes.dedup.score_person_dedup",
            new=AsyncMock(return_value=[]),
        ):
            r = client.post(f"/dedup/{VALID_UUID}/candidates")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["candidates"] == []
        assert data["count"] == 0

    def test_candidates_service_error_returns_500(self):
        """POST /dedup/{uuid}/candidates returns 500 when scorer raises."""
        client = _client(_make_session())
        with patch(
            "api.routes.dedup.score_person_dedup",
            new=AsyncMock(side_effect=Exception("scorer broke")),
        ):
            r = client.post(f"/dedup/{VALID_UUID}/candidates")
        assert r.status_code == 500

    def test_candidates_returns_formatted_list(self):
        """POST /dedup/{uuid}/candidates serialises candidate fields correctly."""
        cand = MagicMock()
        cand.id_a = VALID_UUID
        cand.id_b = str(uuid.uuid4())
        cand.similarity_score = 0.88
        cand.match_reasons = ["same_phone"]

        client = _client(_make_session())
        with patch(
            "api.routes.dedup.score_person_dedup",
            new=AsyncMock(return_value=[cand]),
        ):
            r = client.post(f"/dedup/{VALID_UUID}/candidates")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["candidates"][0]["similarity_score"] == 0.88


class TestDedupMergeHistory:
    def test_merge_history_invalid_uuid_returns_400(self):
        """GET /dedup/{bad}/merge-history returns 400."""
        client = _client(_make_session())
        r = client.get(f"/dedup/{BAD_UUID}/merge-history")
        assert r.status_code == 400

    def test_merge_history_empty(self):
        """GET /dedup/{uuid}/merge-history returns empty history when no rows."""
        session = _make_session()
        mapping_result = MagicMock()
        mapping_result.mappings.return_value.all.return_value = []
        session.execute.return_value = mapping_result

        client = _client(session)
        r = client.get(f"/dedup/{VALID_UUID}/merge-history")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["history"] == []

    def test_merge_history_db_error_returns_500(self):
        """GET /dedup/{uuid}/merge-history returns 500 when DB query fails."""
        session = _make_session()
        session.execute.side_effect = RuntimeError("DB connection lost")
        client = _client(session)
        r = client.get(f"/dedup/{VALID_UUID}/merge-history")
        assert r.status_code == 500


# ===========================================================================
# /enrich  (api/routes/enrichment.py)
# ===========================================================================


class TestEnrichmentSync:
    def _mock_report(self):
        report = MagicMock()
        report.person_id = VALID_UUID
        report.started_at = datetime.now(timezone.utc)
        report.finished_at = datetime.now(timezone.utc)
        report.total_duration_ms = 120
        report.ok_count = 3
        report.error_count = 0
        report.steps = []
        return report

    def test_enrich_invalid_uuid_returns_400(self):
        """POST /enrich/{bad}/enrich returns 400."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{BAD_UUID}/enrich")
        assert r.status_code == 400

    def test_enrich_success_returns_report(self):
        """POST /enrich/{uuid}/enrich returns enrichment report on success."""
        report = self._mock_report()
        client = _client(_make_session())
        with patch(
            "modules.pipeline.enrichment_orchestrator.EnrichmentOrchestrator.enrich_person",
            new=AsyncMock(return_value=report),
        ):
            r = client.post(f"/enrich/{VALID_UUID}/enrich")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert "ok_count" in data
        assert "error_count" in data
        assert "steps" in data

    def test_enrich_orchestrator_raises_returns_500(self):
        """POST /enrich/{uuid}/enrich returns 500 when orchestrator raises."""
        client = _client(_make_session())
        with patch(
            "modules.pipeline.enrichment_orchestrator.EnrichmentOrchestrator.enrich_person",
            new=AsyncMock(side_effect=RuntimeError("pipeline failure")),
        ):
            r = client.post(f"/enrich/{VALID_UUID}/enrich")
        assert r.status_code == 500
        assert "failed" in r.json()["detail"].lower()


class TestEnrichmentBackground:
    def test_background_enrich_invalid_uuid_returns_400(self):
        """POST /enrich/{bad}/enrich/background returns 400."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{BAD_UUID}/enrich/background")
        assert r.status_code == 400

    def test_background_enrich_returns_queued(self):
        """POST /enrich/{uuid}/enrich/background returns queued status immediately."""
        client = _client(_make_session())
        r = client.post(f"/enrich/{VALID_UUID}/enrich/background")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert data["person_id"] == VALID_UUID
        assert "message" in data


# ===========================================================================
# /export  (api/routes/export.py)
# ===========================================================================


class TestExportJson:
    def test_export_json_not_found_returns_404(self):
        """GET /export/{uuid}/json returns 404 when person absent."""
        client = _client(_make_session(get_return=None))
        r = client.get(f"/export/{VALID_UUID}/json")
        assert r.status_code == 404

    def test_export_json_invalid_uuid_returns_422(self):
        """GET /export/{bad}/json returns 422 — FastAPI validates UUID path param."""
        client = _client(_make_session())
        r = client.get(f"/export/{BAD_UUID}/json")
        assert r.status_code == 422

    def test_export_json_returns_attachment(self):
        """GET /export/{uuid}/json streams a JSON file with Content-Disposition."""
        mock_person = MagicMock()
        mock_person.id = uuid.UUID(VALID_UUID)
        mock_person.full_name = "Alice Example"
        mock_person.dob = None
        mock_person.nationality = "ZA"
        mock_person.risk_score = 0.1
        mock_person.meta = {}

        session = _make_session(get_return=mock_person)
        # db.scalars() is called three times for aliases, identifiers, socials
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        client = _client(session)
        r = client.get(f"/export/{VALID_UUID}/json")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json"
        assert "attachment" in r.headers.get("content-disposition", "")
        body = r.json()
        assert "person" in body
        assert body["person"]["full_name"] == "Alice Example"
        assert "aliases" in body
        assert "identifiers" in body
        assert "social_profiles" in body


class TestExportCsv:
    def test_export_csv_not_found_returns_404(self):
        """GET /export/{uuid}/csv returns 404 when person absent."""
        client = _client(_make_session(get_return=None))
        r = client.get(f"/export/{VALID_UUID}/csv")
        assert r.status_code == 404

    def test_export_csv_invalid_uuid_returns_422(self):
        """GET /export/{bad}/csv returns 422."""
        client = _client(_make_session())
        r = client.get(f"/export/{BAD_UUID}/csv")
        assert r.status_code == 422

    def test_export_csv_returns_csv_file(self):
        """GET /export/{uuid}/csv streams a CSV file with correct headers."""
        mock_person = MagicMock()
        mock_person.id = uuid.UUID(VALID_UUID)

        session = _make_session(get_return=mock_person)
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        client = _client(session)
        r = client.get(f"/export/{VALID_UUID}/csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        # CSV should start with the header row
        assert "type" in r.text
        assert "value" in r.text


# ===========================================================================
# /financial  (api/routes/financial.py)
# ===========================================================================


class TestFinancialScore:
    def _mock_profile(self):
        profile = MagicMock()
        profile.person_id = VALID_UUID
        profile.assessed_at = datetime.now(timezone.utc)
        profile.credit = MagicMock(
            score=720,
            risk_category="medium",
            component_breakdown={"payment_history": 0.8},
        )
        profile.aml = MagicMock(
            risk_score=0.1,
            is_pep=False,
            darkweb_mention_count=0,
        )
        profile.fraud = MagicMock(
            fraud_score=0.05,
            tier="low",
            fraud_indicators=[],
        )
        return profile

    def test_score_person_returns_profile(self):
        """POST /financial/{uuid}/score returns financial profile fields."""
        profile = self._mock_profile()
        client = _client(_make_session())
        with patch(
            "modules.enrichers.financial_aml.FinancialIntelligenceEngine.score_person",
            new=AsyncMock(return_value=profile),
        ):
            r = client.post(f"/financial/{VALID_UUID}/score")
        assert r.status_code == 200
        data = r.json()
        assert "credit_score" in data
        assert "aml_risk_score" in data
        assert "fraud_score" in data
        assert data["is_pep"] is False

    def test_score_person_engine_raises_returns_500(self):
        """POST /financial/{uuid}/score returns 500 when engine raises."""
        client = _client(_make_session())
        with patch(
            "modules.enrichers.financial_aml.FinancialIntelligenceEngine.score_person",
            new=AsyncMock(side_effect=RuntimeError("scoring broke")),
        ):
            r = client.post(f"/financial/{VALID_UUID}/score")
        assert r.status_code == 500


class TestFinancialGetAssessment:
    def test_get_assessment_invalid_uuid_returns_400(self):
        """GET /financial/{bad} returns 400 for malformed UUID."""
        client = _client(_make_session())
        r = client.get(f"/financial/{BAD_UUID}")
        assert r.status_code == 400

    def test_get_assessment_not_found_returns_404(self):
        """GET /financial/{uuid} returns 404 when no assessment exists."""
        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/financial/{VALID_UUID}")
        assert r.status_code == 404

    def test_get_assessment_found_returns_dict(self):
        """GET /financial/{uuid} returns model dict when assessment exists."""
        mock_row = MagicMock()
        col = MagicMock()
        col.name = "person_id"
        mock_row.__table__ = MagicMock()
        mock_row.__table__.columns = [col]
        mock_row.person_id = uuid.UUID(VALID_UUID)

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = mock_row
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/financial/{VALID_UUID}")
        assert r.status_code == 200


class TestFinancialAmlMatches:
    def test_get_aml_invalid_uuid_returns_400(self):
        """GET /financial/{bad}/aml returns 400."""
        client = _client(_make_session())
        r = client.get(f"/financial/{BAD_UUID}/aml")
        assert r.status_code == 400

    def test_get_aml_empty_returns_200(self):
        """GET /financial/{uuid}/aml returns empty matches list."""
        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/financial/{VALID_UUID}/aml")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["matches"] == []
        assert data["count"] == 0

    def test_get_aml_with_match_rows(self):
        """GET /financial/{uuid}/aml serialises WatchlistMatch rows."""
        mock_match = MagicMock()
        mock_match.id = uuid.uuid4()
        mock_match.list_name = "OFAC"
        mock_match.list_type = "sanctions"
        mock_match.match_score = 0.98
        mock_match.is_confirmed = True
        mock_match.created_at = datetime.now(timezone.utc)

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_match]
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/financial/{VALID_UUID}/aml")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        match = data["matches"][0]
        assert match["list_name"] == "OFAC"
        assert match["is_confirmed"] is True


class TestFinancialBorrowerScore:
    def test_borrower_score_invalid_uuid_returns_400(self):
        """POST /financial/borrower-score with bad UUID returns 400."""
        client = _client(_make_session())
        r = client.post("/financial/borrower-score", json={"person_id": BAD_UUID})
        assert r.status_code == 400

    def test_borrower_score_missing_body_returns_422(self):
        """POST /financial/borrower-score without body returns 422."""
        client = _client(_make_session())
        r = client.post("/financial/borrower-score", json={})
        assert r.status_code == 422

    def test_borrower_score_returns_score_fields(self):
        """POST /financial/borrower-score returns score, tier, products, signals."""
        mock_profile = MagicMock()
        mock_profile.score = 72.5
        mock_profile.tier = "medium"
        mock_profile.applicable_products = ["personal_loan"]
        mock_profile.signals = {"has_stable_employment": True}

        session = _make_session()
        # All four execute calls return empty scalars
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result

        with patch(
            "modules.enrichers.marketing_tags.HighInterestBorrowerScorer.score",
            return_value=mock_profile,
        ):
            client = _client(session)
            r = client.post("/financial/borrower-score", json={"person_id": VALID_UUID})

        assert r.status_code == 200
        data = r.json()
        assert data["borrower_score"] == 72.5
        assert data["tier"] == "medium"
        assert isinstance(data["applicable_products"], list)
        assert "signals" in data


# ===========================================================================
# /graph  (api/routes/graph.py)
# ===========================================================================


class TestGraphCompanySearch:
    def test_company_search_missing_name_returns_422(self):
        """GET /graph/company/search without name param returns 422."""
        client = _client(_make_session())
        r = client.get("/graph/company/search")
        assert r.status_code == 422

    def test_company_search_empty_results(self):
        """GET /graph/company/search?name=Acme returns empty list."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.search_company",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/graph/company/search?name=Acme")
        assert r.status_code == 200
        data = r.json()
        assert data["companies"] == []
        assert data["count"] == 0

    def test_company_search_with_state_filter(self):
        """GET /graph/company/search?name=Acme&state=TX forwards state param."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.search_company",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/graph/company/search?name=Acme&state=TX")
        assert r.status_code == 200


class TestGraphCompanyNetwork:
    def test_company_network_missing_name_returns_422(self):
        """GET /graph/company/network without name returns 422."""
        client = _client(_make_session())
        r = client.get("/graph/company/network")
        assert r.status_code == 422

    def test_company_network_returns_nodes_edges(self):
        """GET /graph/company/network?name=Acme returns node/edge structure."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.get_company_network",
            new=AsyncMock(return_value={"nodes": [], "edges": []}),
        ):
            r = client.get("/graph/company/network?name=Acme")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "edges" in data
        assert data["company_name"] == "Acme"


class TestGraphPersonNetwork:
    def test_person_network_valid_uuid_returns_graph(self):
        """GET /graph/person/{uuid}/network returns node/edge graph."""
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.build_person_graph",
            new=AsyncMock(return_value={"nodes": [], "edges": []}),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/network")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert "depth" in data
        assert "nodes" in data
        assert "edges" in data

    def test_person_network_depth_out_of_range_returns_422(self):
        """GET /graph/person/{uuid}/network?depth=5 returns 422 (max depth is 3)."""
        client = _client(_make_session())
        r = client.get(f"/graph/person/{VALID_UUID}/network?depth=5")
        assert r.status_code == 422

    def test_person_network_builder_raises_value_error_returns_400(self):
        """GET /graph/person/{uuid}/network returns 400 when builder raises ValueError."""
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.build_person_graph",
            new=AsyncMock(side_effect=ValueError("Person not found")),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/network")
        assert r.status_code == 400

    def test_person_network_builder_raises_generic_returns_500(self):
        """GET /graph/person/{uuid}/network returns 500 on unexpected error."""
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.build_person_graph",
            new=AsyncMock(side_effect=RuntimeError("graph DB timeout")),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/network")
        assert r.status_code == 500


class TestGraphPersonCompanies:
    def test_person_companies_returns_list(self):
        """GET /graph/person/{uuid}/companies returns companies list."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.get_person_companies",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/companies")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert "companies" in data

    def test_person_companies_value_error_returns_400(self):
        """GET /graph/person/{uuid}/companies returns 400 on ValueError."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.get_person_companies",
            new=AsyncMock(side_effect=ValueError("bad input")),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/companies")
        assert r.status_code == 400

    def test_person_companies_generic_error_returns_500(self):
        """GET /graph/person/{uuid}/companies returns 500 on unexpected error."""
        client = _client(_make_session())
        with patch(
            "modules.graph.company_intel.CompanyIntelligenceEngine.get_person_companies",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            r = client.get(f"/graph/person/{VALID_UUID}/companies")
        assert r.status_code == 500


class TestGraphFraudRings:
    def test_fraud_rings_default_payload(self):
        """POST /graph/fraud-rings with default body returns rings list."""
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.detect_fraud_rings",
            new=AsyncMock(return_value=[]),
        ):
            r = client.post("/graph/fraud-rings", json={})
        assert r.status_code == 200
        data = r.json()
        assert "rings" in data
        assert data["count"] == 0

    def test_fraud_rings_min_connections_too_large_returns_422(self):
        """POST /graph/fraud-rings with min_connections>50 returns 422."""
        client = _client(_make_session())
        r = client.post("/graph/fraud-rings", json={"min_connections": 100})
        assert r.status_code == 422

    def test_fraud_rings_min_connections_zero_returns_422(self):
        """POST /graph/fraud-rings with min_connections=0 returns 422 (ge=1)."""
        client = _client(_make_session())
        r = client.post("/graph/fraud-rings", json={"min_connections": 0})
        assert r.status_code == 422

    def test_fraud_rings_engine_error_returns_500(self):
        """POST /graph/fraud-rings returns 500 when builder raises."""
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.detect_fraud_rings",
            new=AsyncMock(side_effect=RuntimeError("graph error")),
        ):
            r = client.post("/graph/fraud-rings", json={"min_connections": 3})
        assert r.status_code == 500


class TestGraphSharedConnections:
    def test_shared_connections_fewer_than_2_returns_400(self):
        """POST /graph/shared-connections with <2 IDs returns 400."""
        client = _client(_make_session())
        r = client.post(
            "/graph/shared-connections",
            json={"person_ids": [VALID_UUID]},
        )
        assert r.status_code == 400
        assert "2" in r.json()["detail"]

    def test_shared_connections_empty_list_returns_400(self):
        """POST /graph/shared-connections with empty list returns 400."""
        client = _client(_make_session())
        r = client.post("/graph/shared-connections", json={"person_ids": []})
        assert r.status_code == 400

    def test_shared_connections_missing_body_returns_422(self):
        """POST /graph/shared-connections without body returns 422."""
        client = _client(_make_session())
        r = client.post("/graph/shared-connections", json={})
        assert r.status_code == 422

    def test_shared_connections_returns_connections(self):
        """POST /graph/shared-connections returns connections and count."""
        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.find_shared_connections",
            new=AsyncMock(return_value=[]),
        ):
            r = client.post(
                "/graph/shared-connections",
                json={"person_ids": [id_a, id_b]},
            )
        assert r.status_code == 200
        data = r.json()
        assert "connections" in data
        assert data["count"] == 0

    def test_shared_connections_engine_error_returns_500(self):
        """POST /graph/shared-connections returns 500 when builder raises."""
        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())
        client = _client(_make_session())
        with patch(
            "modules.graph.entity_graph.EntityGraphBuilder.find_shared_connections",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            r = client.post(
                "/graph/shared-connections",
                json={"person_ids": [id_a, id_b]},
            )
        assert r.status_code == 500


# ===========================================================================
# /marketing  (api/routes/marketing.py)
# ===========================================================================


class TestMarketingTagPerson:
    def test_tag_invalid_uuid_returns_400(self):
        """POST /marketing/{bad}/tag returns 400."""
        client = _client(_make_session())
        r = client.post(f"/marketing/{BAD_UUID}/tag")
        assert r.status_code == 400

    def test_tag_engine_raises_returns_500(self):
        """POST /marketing/{uuid}/tag returns 500 when engine raises."""
        client = _client(_make_session())
        with patch(
            "modules.enrichers.marketing_tags.MarketingTagsEngine.tag_person",
            new=AsyncMock(side_effect=RuntimeError("tagging failed")),
        ):
            r = client.post(f"/marketing/{VALID_UUID}/tag")
        assert r.status_code == 500

    def test_tag_returns_empty_tags_when_no_results(self):
        """POST /marketing/{uuid}/tag returns empty tag list when engine returns nothing."""
        client = _client(_make_session())
        with patch(
            "modules.enrichers.marketing_tags.MarketingTagsEngine.tag_person",
            new=AsyncMock(return_value=[]),
        ):
            r = client.post(f"/marketing/{VALID_UUID}/tag")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["tags"] == []
        assert data["tag_count"] == 0

    def test_tag_persists_new_tag_records(self):
        """POST /marketing/{uuid}/tag calls session.add for new tags."""
        tag_result = MagicMock()
        tag_result.tag = "high_income"
        tag_result.confidence = 0.9
        tag_result.reasoning = "Multiple income signals"
        tag_result.scored_at = datetime.now(timezone.utc)

        session = _make_session()
        # First execute call returns no existing tag (so we add a new one)
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result

        with patch(
            "modules.enrichers.marketing_tags.MarketingTagsEngine.tag_person",
            new=AsyncMock(return_value=[tag_result]),
        ):
            client = _client(session)
            r = client.post(f"/marketing/{VALID_UUID}/tag")

        assert r.status_code == 200
        data = r.json()
        assert data["tag_count"] == 1
        assert data["tags"][0]["tag"] == "high_income"
        # Verify session.add was called (new tag inserted)
        session.add.assert_called_once()

    def test_tag_updates_existing_tag_record(self):
        """POST /marketing/{uuid}/tag updates confidence on existing tag."""
        tag_result = MagicMock()
        tag_result.tag = "debt_prone"
        tag_result.confidence = 0.85
        tag_result.reasoning = "Credit signals"
        tag_result.scored_at = datetime.now(timezone.utc)

        existing_tag = MagicMock()
        existing_tag.confidence = 0.70

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = existing_tag
        session.execute.return_value = exec_result

        with patch(
            "modules.enrichers.marketing_tags.MarketingTagsEngine.tag_person",
            new=AsyncMock(return_value=[tag_result]),
        ):
            client = _client(session)
            r = client.post(f"/marketing/{VALID_UUID}/tag")

        assert r.status_code == 200
        # Verify the existing tag was mutated (not a new add)
        session.add.assert_not_called()
        assert existing_tag.confidence == 0.85

    def test_tag_commit_failure_returns_500(self):
        """POST /marketing/{uuid}/tag returns 500 when DB commit fails."""
        session = _make_session()
        session.commit.side_effect = RuntimeError("commit failed")
        exec_result = MagicMock()
        exec_result.scalars.return_value.first.return_value = None
        session.execute.return_value = exec_result

        tag_result = MagicMock()
        tag_result.tag = "some_tag"
        tag_result.confidence = 0.5
        tag_result.reasoning = ""
        tag_result.scored_at = None

        with patch(
            "modules.enrichers.marketing_tags.MarketingTagsEngine.tag_person",
            new=AsyncMock(return_value=[tag_result]),
        ):
            client = _client(session)
            r = client.post(f"/marketing/{VALID_UUID}/tag")

        assert r.status_code == 500
        assert "persist" in r.json()["detail"].lower()


class TestMarketingGetTags:
    def test_get_tags_invalid_uuid_returns_400(self):
        """GET /marketing/{bad}/tags returns 400."""
        client = _client(_make_session())
        r = client.get(f"/marketing/{BAD_UUID}/tags")
        assert r.status_code == 400

    def test_get_tags_empty(self):
        """GET /marketing/{uuid}/tags returns empty list when no tags exist."""
        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/marketing/{VALID_UUID}/tags")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["tags"] == []

    def test_get_tags_serialises_rows(self):
        """GET /marketing/{uuid}/tags serialises MarketingTag rows."""
        mock_tag = MagicMock()
        col = MagicMock()
        col.name = "tag"
        mock_tag.__table__ = MagicMock()
        mock_tag.__table__.columns = [col]
        mock_tag.tag = "high_income"

        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [mock_tag]
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/marketing/{VALID_UUID}/tags")
        assert r.status_code == 200
        data = r.json()
        assert len(data["tags"]) == 1


class TestMarketingPersonsByTag:
    def test_persons_by_tag_returns_empty(self):
        """GET /marketing/tags/by-tag/{name} returns empty list when no matches."""
        session = _make_session()
        session.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        client = _client(session)
        r = client.get("/marketing/tags/by-tag/high_income")
        assert r.status_code == 200
        data = r.json()
        assert data["tag"] == "high_income"
        assert data["persons"] == []
        assert data["count"] == 0

    def test_persons_by_tag_with_threshold_and_limit(self):
        """GET /marketing/tags/by-tag/{name}?threshold=0.9&limit=10 accepts params."""
        session = _make_session()
        session.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        client = _client(session)
        r = client.get("/marketing/tags/by-tag/debt_prone?threshold=0.9&limit=10")
        assert r.status_code == 200

    def test_persons_by_tag_threshold_out_of_range_returns_422(self):
        """GET /marketing/tags/by-tag/{name}?threshold=1.5 returns 422 (le=1.0)."""
        client = _client(_make_session())
        r = client.get("/marketing/tags/by-tag/tag?threshold=1.5")
        assert r.status_code == 422

    def test_persons_by_tag_limit_too_large_returns_422(self):
        """GET /marketing/tags/by-tag/{name}?limit=9999 returns 422 (le=500)."""
        client = _client(_make_session())
        r = client.get("/marketing/tags/by-tag/tag?limit=9999")
        assert r.status_code == 422


class TestMarketingBorrowerProfile:
    def test_borrower_profile_invalid_uuid_returns_400(self):
        """GET /marketing/{bad}/borrower-profile returns 400."""
        client = _client(_make_session())
        r = client.get(f"/marketing/{BAD_UUID}/borrower-profile")
        assert r.status_code == 400

    def test_borrower_profile_empty(self):
        """GET /marketing/{uuid}/borrower-profile returns empty segments list."""
        session = _make_session()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        session.execute.return_value = exec_result

        client = _client(session)
        r = client.get(f"/marketing/{VALID_UUID}/borrower-profile")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert data["segments"] == []


# ===========================================================================
# /patterns  (api/routes/patterns.py)
# ===========================================================================


class TestPatternsAnomalyDetect:
    def test_anomaly_detect_fewer_than_3_persons_returns_message(self):
        """POST /patterns/anomaly/detect with <3 persons in DB returns guidance message."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.post("/patterns/anomaly/detect", json={})
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert "3" in data["message"]
        assert data["anomalies"] == {}

    def test_anomaly_detect_min_score_out_of_range_returns_422(self):
        """POST /patterns/anomaly/detect with min_score>1.0 returns 422."""
        client = _client(_make_session())
        r = client.post("/patterns/anomaly/detect", json={"min_score": 1.5})
        assert r.status_code == 422

    def test_anomaly_detect_limit_too_large_returns_422(self):
        """POST /patterns/anomaly/detect with limit>5000 returns 422."""
        client = _client(_make_session())
        r = client.post("/patterns/anomaly/detect", json={"limit": 9999})
        assert r.status_code == 422

    def test_anomaly_detect_limit_too_small_returns_422(self):
        """POST /patterns/anomaly/detect with limit<3 returns 422 (ge=3)."""
        client = _client(_make_session())
        r = client.post("/patterns/anomaly/detect", json={"limit": 2})
        assert r.status_code == 422

    def test_anomaly_detect_with_3_persons_calls_detector(self):
        """POST /patterns/anomaly/detect with ≥3 persons calls the anomaly detector."""
        persons = []
        for _ in range(3):
            p = MagicMock()
            p.id = uuid.uuid4()
            p.full_name = "Test Person"
            p.default_risk_score = 0.5
            p.source_reliability = 0.8
            p.darkweb_exposure = 0.0
            p.behavioural_risk = 0.0
            p.relationship_score = 0.0
            persons.append(p)

        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=persons))
        client = _client(session)

        with patch(
            "modules.patterns.anomaly.StatisticalAnomalyDetector.detect_multi_field",
            return_value={},
        ):
            r = client.post("/patterns/anomaly/detect", json={})
        assert r.status_code == 200
        data = r.json()
        assert "anomalies" in data
        assert data["entities_count"] == 3

    def test_anomaly_detect_with_specific_person_ids(self):
        """POST /patterns/anomaly/detect filters by provided person_ids."""
        session = _make_session()
        session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        client = _client(session)
        r = client.post(
            "/patterns/anomaly/detect",
            json={"person_ids": [VALID_UUID]},
        )
        assert r.status_code == 200


class TestPatternsTemporalChangeVelocity:
    def test_change_velocity_invalid_uuid_returns_400(self):
        """GET /patterns/temporal/change-velocity/{bad} returns 400."""
        client = _client(_make_session())
        r = client.get(f"/patterns/temporal/change-velocity/{BAD_UUID}")
        assert r.status_code == 400

    def test_change_velocity_valid_uuid_returns_200(self):
        """GET /patterns/temporal/change-velocity/{uuid} returns velocity data."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.detect_change_velocity",
            new=AsyncMock(return_value={"events_per_day": 0.5}),
        ):
            r = client.get(f"/patterns/temporal/change-velocity/{VALID_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["person_id"] == VALID_UUID
        assert "window_days" in data
        assert "velocity" in data

    def test_change_velocity_window_days_param(self):
        """GET /patterns/temporal/change-velocity/{uuid}?window_days=90 is accepted."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.detect_change_velocity",
            new=AsyncMock(return_value={}),
        ):
            r = client.get(f"/patterns/temporal/change-velocity/{VALID_UUID}?window_days=90")
        assert r.status_code == 200
        assert r.json()["window_days"] == 90

    def test_change_velocity_window_too_large_returns_422(self):
        """GET /patterns/temporal/change-velocity/{uuid}?window_days=400 returns 422 (le=365)."""
        client = _client(_make_session())
        r = client.get(f"/patterns/temporal/change-velocity/{VALID_UUID}?window_days=400")
        assert r.status_code == 422

    def test_change_velocity_service_error_returns_500(self):
        """GET /patterns/temporal/change-velocity/{uuid} returns 500 on service error."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.detect_change_velocity",
            new=AsyncMock(side_effect=RuntimeError("query failed")),
        ):
            r = client.get(f"/patterns/temporal/change-velocity/{VALID_UUID}")
        assert r.status_code == 500


class TestPatternsTemporalAddressPatterns:
    def test_address_patterns_returns_200(self):
        """GET /patterns/temporal/address-patterns returns patterns and count."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_address_change_patterns",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/temporal/address-patterns")
        assert r.status_code == 200
        data = r.json()
        assert "patterns" in data
        assert data["count"] == 0

    def test_address_patterns_min_changes_param(self):
        """GET /patterns/temporal/address-patterns?min_changes=5 is accepted."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_address_change_patterns",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/temporal/address-patterns?min_changes=5")
        assert r.status_code == 200

    def test_address_patterns_min_changes_too_small_returns_422(self):
        """GET /patterns/temporal/address-patterns?min_changes=1 returns 422 (ge=2)."""
        client = _client(_make_session())
        r = client.get("/patterns/temporal/address-patterns?min_changes=1")
        assert r.status_code == 422

    def test_address_patterns_limit_too_large_returns_422(self):
        """GET /patterns/temporal/address-patterns?limit=999 returns 422 (le=200)."""
        client = _client(_make_session())
        r = client.get("/patterns/temporal/address-patterns?limit=999")
        assert r.status_code == 422

    def test_address_patterns_service_error_returns_500(self):
        """GET /patterns/temporal/address-patterns returns 500 on service error."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_address_change_patterns",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            r = client.get("/patterns/temporal/address-patterns")
        assert r.status_code == 500


class TestPatternsIdentifierChurn:
    def test_identifier_churn_returns_200(self):
        """GET /patterns/temporal/identifier-churn returns patterns and count."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_identifier_change_patterns",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/temporal/identifier-churn")
        assert r.status_code == 200
        data = r.json()
        assert "patterns" in data
        assert data["count"] == 0

    def test_identifier_churn_min_changes_too_large_returns_422(self):
        """GET /patterns/temporal/identifier-churn?min_changes=25 returns 422 (le=20)."""
        client = _client(_make_session())
        r = client.get("/patterns/temporal/identifier-churn?min_changes=25")
        assert r.status_code == 422

    def test_identifier_churn_service_error_returns_500(self):
        """GET /patterns/temporal/identifier-churn returns 500 on service error."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_identifier_change_patterns",
            new=AsyncMock(side_effect=RuntimeError("DB error")),
        ):
            r = client.get("/patterns/temporal/identifier-churn")
        assert r.status_code == 500


class TestPatternsRiskCoOccurring:
    def test_co_occurring_flags_returns_200(self):
        """GET /patterns/risk/co-occurring-flags returns high_risk_persons and count."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_co_occurring_risk_flags",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/risk/co-occurring-flags")
        assert r.status_code == 200
        data = r.json()
        assert "high_risk_persons" in data
        assert data["count"] == 0

    def test_co_occurring_flags_limit_param(self):
        """GET /patterns/risk/co-occurring-flags?limit=20 is accepted."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_co_occurring_risk_flags",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/risk/co-occurring-flags?limit=20")
        assert r.status_code == 200

    def test_co_occurring_flags_limit_too_large_returns_422(self):
        """GET /patterns/risk/co-occurring-flags?limit=500 returns 422 (le=200)."""
        client = _client(_make_session())
        r = client.get("/patterns/risk/co-occurring-flags?limit=500")
        assert r.status_code == 422

    def test_co_occurring_flags_service_error_returns_500(self):
        """GET /patterns/risk/co-occurring-flags returns 500 on service error."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_co_occurring_risk_flags",
            new=AsyncMock(side_effect=RuntimeError("SQL error")),
        ):
            r = client.get("/patterns/risk/co-occurring-flags")
        assert r.status_code == 500


class TestPatternsRiskNetworkAnomalies:
    def test_network_anomalies_returns_200(self):
        """GET /patterns/risk/network-anomalies returns hubs and count."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_network_anomalies",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/risk/network-anomalies")
        assert r.status_code == 200
        data = r.json()
        assert "network_hubs" in data
        assert data["count"] == 0

    def test_network_anomalies_min_connections_param(self):
        """GET /patterns/risk/network-anomalies?min_connections=20 is accepted."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_network_anomalies",
            new=AsyncMock(return_value=[]),
        ):
            r = client.get("/patterns/risk/network-anomalies?min_connections=20")
        assert r.status_code == 200

    def test_network_anomalies_min_connections_too_small_returns_422(self):
        """GET /patterns/risk/network-anomalies?min_connections=1 returns 422 (ge=3)."""
        client = _client(_make_session())
        r = client.get("/patterns/risk/network-anomalies?min_connections=1")
        assert r.status_code == 422

    def test_network_anomalies_min_connections_too_large_returns_422(self):
        """GET /patterns/risk/network-anomalies?min_connections=600 returns 422 (le=500)."""
        client = _client(_make_session())
        r = client.get("/patterns/risk/network-anomalies?min_connections=600")
        assert r.status_code == 422

    def test_network_anomalies_service_error_returns_500(self):
        """GET /patterns/risk/network-anomalies returns 500 on service error."""
        client = _client(_make_session())
        with patch(
            "modules.patterns.temporal.TemporalPatternAnalyzer.find_network_anomalies",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            r = client.get("/patterns/risk/network-anomalies")
        assert r.status_code == 500
