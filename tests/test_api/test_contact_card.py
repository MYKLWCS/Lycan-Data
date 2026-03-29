"""Contact card API tests — new /report fields and OCEAN persistence."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Task 1: OCEAN persistence
# ---------------------------------------------------------------------------


class TestOceanPersistence:
    """BehaviouralProfile.meta receives OCEAN keys when crawler_data carries them."""

    @pytest.mark.asyncio
    async def test_ocean_written_to_meta_on_new_profile(self):
        from modules.crawlers.core.result import CrawlerResult
        from modules.pipeline.aggregator import _handle_behavioural

        session = AsyncMock()
        # No existing profile — scalar_one_or_none returns None
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=exec_result)
        session.add = MagicMock()
        session.flush = AsyncMock()

        result = CrawlerResult(
            platform="social_posts_analyzer",
            identifier="user123",
            found=True,
            data={
                "ocean_openness": 0.72,
                "ocean_conscientiousness": 0.55,
                "ocean_extraversion": 0.40,
                "ocean_agreeableness": 0.68,
                "ocean_neuroticism": 0.30,
            },
            source_reliability=0.7,
        )

        person_id = uuid.uuid4()
        await _handle_behavioural(session, result, person_id)

        # session.add should have been called with a BehaviouralProfile
        assert session.add.called
        added = session.add.call_args[0][0]
        assert added.meta["ocean_openness"] == 0.72
        assert added.meta["ocean_conscientiousness"] == 0.55
        assert added.meta["ocean_extraversion"] == 0.40
        assert added.meta["ocean_agreeableness"] == 0.68
        assert added.meta["ocean_neuroticism"] == 0.30

    @pytest.mark.asyncio
    async def test_ocean_written_to_meta_on_existing_profile(self):
        from modules.crawlers.core.result import CrawlerResult
        from modules.pipeline.aggregator import _handle_behavioural
        from shared.models.behavioural import BehaviouralProfile

        existing = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            gambling_score=0.0,
            financial_distress_score=0.0,
            fraud_score=0.0,
            drug_signal_score=0.0,
            violence_score=0.0,
            criminal_signal_score=0.0,
            meta={},
        )

        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=exec_result)

        result = CrawlerResult(
            platform="social_posts_analyzer",
            identifier="user123",
            found=True,
            data={"ocean_openness": 0.88},
            source_reliability=0.7,
        )

        await _handle_behavioural(session, result, existing.person_id)
        assert existing.meta["ocean_openness"] == 0.88
        assert existing.meta.get("ocean_conscientiousness") is None

    @pytest.mark.asyncio
    async def test_ocean_absent_leaves_meta_unchanged(self):
        from modules.crawlers.core.result import CrawlerResult
        from modules.pipeline.aggregator import _handle_behavioural
        from shared.models.behavioural import BehaviouralProfile

        existing = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            gambling_score=0.0,
            financial_distress_score=0.0,
            fraud_score=0.0,
            drug_signal_score=0.0,
            violence_score=0.0,
            criminal_signal_score=0.0,
            meta={"other_key": "preserved"},
        )

        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=exec_result)

        result = CrawlerResult(
            platform="social_posts_analyzer",
            identifier="user123",
            found=True,
            data={"gambling_language": True},
            source_reliability=0.7,
        )

        await _handle_behavioural(session, result, existing.person_id)
        assert "ocean_openness" not in existing.meta
        assert existing.meta["other_key"] == "preserved"


# ---------------------------------------------------------------------------
# Task 2: /report includes commercial_tags
# ---------------------------------------------------------------------------


class TestReportCommercialTags:
    """GET /persons/{id}/report returns commercial_tags list."""

    def _make_person(self, pid):
        from shared.models.person import Person

        p = MagicMock(spec=Person)
        p.id = pid
        p.full_name = "Jane Test"
        p.date_of_birth = None
        p.gender = None
        p.nationality = None
        p.primary_language = None
        p.bio = None
        p.profile_image_url = None
        p.relationship_score = 0.5
        p.behavioural_risk = 0.2
        p.darkweb_exposure = 0.1
        p.default_risk_score = 0.3
        p.source_reliability = 0.8
        p.freshness_score = 0.7
        p.corroboration_count = 3
        p.composite_quality = 0.75
        p.verification_status = "verified"
        p.conflict_flag = False
        p.created_at = None
        p.updated_at = None
        p.meta = {}
        # Needed by _model_to_dict
        p.__table__ = MagicMock()
        p.__table__.columns = []
        return p

    def test_report_includes_commercial_tags_key(self):
        from starlette.testclient import TestClient

        from api.deps import db_session
        from api.main import app

        pid = uuid.uuid4()
        person = self._make_person(pid)

        session = AsyncMock()
        session.get = AsyncMock(return_value=person)

        # All _fetch calls return empty list; commercial_tags query returns one tag row
        import datetime as _dt

        from shared.models.marketing import MarketingTag

        tag_row = MagicMock()
        tag_row.tag = "title_loan_candidate"
        tag_row.tag_category = "lending"
        tag_row.confidence = 0.78
        tag_row.reasoning = ["Vehicle record found", "Financial distress 62%"]
        tag_row.scored_at = _dt.datetime(2026, 3, 24, 10, 0, 0, tzinfo=_dt.timezone.utc)

        empty_exec = MagicMock()
        empty_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        tag_exec = MagicMock()
        tag_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[tag_row])))

        # sources_enabled_count uses .scalar_one()
        sources_count_exec = MagicMock()
        sources_count_exec.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        sources_count_exec.scalar_one = MagicMock(return_value=0)

        async def _execute(q):
            q_str = str(q)
            if "marketing_tag" in q_str.lower():
                return tag_exec
            if "data_sources" in q_str.lower():
                return sources_count_exec
            return empty_exec

        session.execute = _execute

        async def _dep():
            yield session

        app.dependency_overrides[db_session] = _dep
        client = TestClient(app, raise_server_exceptions=True)

        resp = client.get(f"/persons/{pid}/report")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "commercial_tags" in body
        assert isinstance(body["commercial_tags"], list)


# ---------------------------------------------------------------------------
# Task 3: /report includes connections
# ---------------------------------------------------------------------------


class TestReportConnections:
    """GET /persons/{id}/report returns connections.persons and connections.entities."""

    def test_report_connections_structure(self):
        """connections key present with persons and entities sub-keys."""
        from starlette.testclient import TestClient

        from api.deps import db_session
        from api.main import app
        from shared.models.person import Person as PersonModel
        from shared.models.relationship import Relationship

        pid = uuid.uuid4()
        related_pid = uuid.uuid4()

        session = AsyncMock()

        p = MagicMock()
        p.id = pid
        p.__table__ = MagicMock()
        p.__table__.columns = []
        p.full_name = "Test Person"
        p.date_of_birth = None
        for attr in (
            "gender",
            "nationality",
            "primary_language",
            "bio",
            "profile_image_url",
            "relationship_score",
            "behavioural_risk",
            "darkweb_exposure",
            "default_risk_score",
            "source_reliability",
            "freshness_score",
            "corroboration_count",
            "composite_quality",
            "verification_status",
            "conflict_flag",
            "created_at",
            "updated_at",
            "meta",
        ):
            setattr(p, attr, None if attr not in ("conflict_flag",) else False)
        session.get = AsyncMock(return_value=p)

        rel = MagicMock(spec=Relationship)
        rel.person_b_id = related_pid
        rel.rel_type = "co-location"
        rel.score = 0.82
        rel.evidence = {"shared_identifier_count": 3}

        related_person = MagicMock(spec=PersonModel)
        related_person.id = related_pid
        related_person.full_name = "Jane Doe"

        empty_exec = MagicMock()
        empty_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        rel_exec = MagicMock()
        rel_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rel])))

        related_exec = MagicMock()
        related_exec.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[related_person]))
        )

        sources_count_exec = MagicMock()
        sources_count_exec.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        sources_count_exec.scalar_one = MagicMock(return_value=0)

        async def _execute(q):
            # Match by query content, not position
            q_str = str(q)
            if "relationship" in q_str.lower() and "person_a_id" in q_str.lower():
                return rel_exec
            if "persons" in q_str.lower() and "in_" in q_str.lower():
                return related_exec
            if "data_sources" in q_str.lower() or "scalar_one" in q_str.lower():
                return sources_count_exec
            return empty_exec

        session.execute = _execute

        async def _dep():
            yield session

        app.dependency_overrides[db_session] = _dep
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get(f"/persons/{pid}/report")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "connections" in body
        conn = body["connections"]
        assert "persons" in conn
        assert "entities" in conn
        assert conn["persons"][0]["relationship_type"] == "co-location"
        assert conn["persons"][0]["relationship_score"] == 0.82
        assert conn["persons"][0]["shared_identifier_count"] == 3
        assert conn["persons"][0]["full_name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# Task 4: /report includes coverage
# ---------------------------------------------------------------------------


class TestReportCoverage:
    """GET /persons/{id}/report returns coverage block with live source count."""

    def test_report_coverage_structure(self):
        from starlette.testclient import TestClient

        from api.deps import db_session
        from api.main import app
        from shared.models.crawl import CrawlJob, DataSource

        pid = uuid.uuid4()

        session = AsyncMock()

        p = MagicMock()
        p.id = pid
        p.__table__ = MagicMock()
        p.__table__.columns = []
        p.full_name = "Test"
        p.date_of_birth = None
        for attr in (
            "gender",
            "nationality",
            "primary_language",
            "bio",
            "profile_image_url",
            "relationship_score",
            "behavioural_risk",
            "darkweb_exposure",
            "default_risk_score",
            "source_reliability",
            "freshness_score",
            "corroboration_count",
            "composite_quality",
            "verification_status",
            "conflict_flag",
            "created_at",
            "updated_at",
            "meta",
        ):
            setattr(p, attr, None if attr != "conflict_flag" else False)
        session.get = AsyncMock(return_value=p)

        # CrawlJob for this person
        import datetime as _dt

        job = MagicMock(spec=CrawlJob)
        job.meta = {"platform": "twitter"}
        job.completed_at = _dt.datetime(2026, 3, 20, 8, 0, 0, tzinfo=_dt.timezone.utc)
        job.status = "done"
        job.source_id = None
        job.result_count = 1

        empty_exec = MagicMock()
        empty_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        empty_exec.scalar_one = MagicMock(return_value=0)

        crawl_exec = MagicMock()
        crawl_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[job])))

        sources_enabled_exec = MagicMock()
        sources_enabled_exec.scalar_one = MagicMock(return_value=131)

        call_count = {"n": 0}

        async def _execute(q):
            call_count["n"] += 1
            # Query order: 1-16 standard _fetch calls, 17=MarketingTag, 18=Relationship,
            # 19=CrawlJob (no related person lookup when rels empty), 20=DataSource count
            if call_count["n"] == 19:  # CrawlJob query
                return crawl_exec
            if call_count["n"] == 20:  # COUNT data_sources enabled
                return sources_enabled_exec
            return empty_exec

        session.execute = _execute

        async def _dep():
            yield session

        app.dependency_overrides[db_session] = _dep
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get(f"/persons/{pid}/report")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "coverage" in body
        cov = body["coverage"]
        assert "sources_enabled" in cov
        assert "sources_attempted" in cov
        assert "sources_found" in cov
        assert "coverage_pct" in cov
        assert "crawl_history" in cov
        assert isinstance(cov["sources_enabled"], int)
        assert isinstance(cov["crawl_history"], list)
