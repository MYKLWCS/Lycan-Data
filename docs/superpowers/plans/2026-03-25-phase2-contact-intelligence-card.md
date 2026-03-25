# Contact Intelligence Card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-column person detail layout with a full-screen contact card (left rail + 4 tabbed content panes) and extend `GET /persons/{id}/report` with `commercial_tags`, `connections`, and `coverage` fields.

**Architecture:** The API extension adds three async query blocks to the existing `get_report()` function in `api/routes/persons.py`, each appended as a top-level key so the existing response shape is additive. The HTML SPA rewrites `renderPerson()` in `static/index.html` in-place — the outer routing shell (`#/persons/:id`) is unchanged, only the DOM construction function is replaced. The OCEAN fix is a surgical addition inside `_handle_behavioural()` in `modules/pipeline/aggregator.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, vanilla JS D3-less SPA

---

### Task 1: OCEAN persistence fix in aggregator.py

**Files:**
- Modify: `modules/pipeline/aggregator.py`
- Test: `tests/test_api/test_contact_card.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api/test_contact_card.py
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
        from modules.pipeline.aggregator import _handle_behavioural
        from modules.crawlers.result import CrawlerResult

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
        from modules.pipeline.aggregator import _handle_behavioural
        from modules.crawlers.result import CrawlerResult
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
        from modules.pipeline.aggregator import _handle_behavioural
        from modules.crawlers.result import CrawlerResult
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_contact_card.py::TestOceanPersistence -v`

Expected: FAIL — `assert added.meta["ocean_openness"] == 0.72` (KeyError or AttributeError because OCEAN keys are never written)

- [ ] **Step 3: Write minimal implementation**

In `modules/pipeline/aggregator.py`, locate `_handle_behavioural()`. After the block that sets `existing.last_assessed_at` (inside the `if existing:` branch) and after the `session.add(bp)` line in the `else` branch, add the OCEAN write. The full modified function:

```python
async def _handle_behavioural(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Update or create a BehaviouralProfile from social-post analysis signals."""
    data = result.data or {}

    gambling = 1.0 if data.get("gambling_language") else 0.0
    financial = 1.0 if data.get("financial_stress_language") else 0.0
    substance = 1.0 if data.get("substance_language") else 0.0
    aggression = 1.0 if data.get("aggression_language") else 0.0

    existing = (
        await session.execute(
            select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id).limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        existing.gambling_score = max(existing.gambling_score or 0.0, gambling)
        existing.financial_distress_score = max(existing.financial_distress_score or 0.0, financial)
        existing.drug_signal_score = max(existing.drug_signal_score or 0.0, substance)
        existing.violence_score = max(existing.violence_score or 0.0, aggression)
        existing.last_assessed_at = datetime.now(UTC)
        if "ocean_openness" in data:
            existing.meta["ocean_openness"] = data["ocean_openness"]
            existing.meta["ocean_conscientiousness"] = data.get("ocean_conscientiousness")
            existing.meta["ocean_extraversion"] = data.get("ocean_extraversion")
            existing.meta["ocean_agreeableness"] = data.get("ocean_agreeableness")
            existing.meta["ocean_neuroticism"] = data.get("ocean_neuroticism")
    else:
        meta: dict = {}
        if "ocean_openness" in data:
            meta["ocean_openness"] = data["ocean_openness"]
            meta["ocean_conscientiousness"] = data.get("ocean_conscientiousness")
            meta["ocean_extraversion"] = data.get("ocean_extraversion")
            meta["ocean_agreeableness"] = data.get("ocean_agreeableness")
            meta["ocean_neuroticism"] = data.get("ocean_neuroticism")
        bp = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=person_id,
            gambling_score=gambling,
            financial_distress_score=financial,
            fraud_score=0.0,
            drug_signal_score=substance,
            violence_score=aggression,
            criminal_signal_score=0.0,
            last_assessed_at=datetime.now(UTC),
            meta=meta,
        )
        session.add(bp)
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_contact_card.py::TestOceanPersistence -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/aggregator.py tests/test_api/test_contact_card.py
git commit -m "fix: persist OCEAN traits to BehaviouralProfile.meta in aggregator"
```

---

### Task 2: Extend /report with commercial_tags

**Files:**
- Modify: `api/routes/persons.py`
- Test: `tests/test_api/test_contact_card.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_api/test_contact_card.py`:

```python
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
        from api.main import app
        from api.deps import db_session

        pid = uuid.uuid4()
        person = self._make_person(pid)

        session = AsyncMock()
        session.get = AsyncMock(return_value=person)

        # All _fetch calls return empty list; commercial_tags query returns one tag row
        from shared.models.marketing import MarketingTag
        import datetime as _dt
        tag_row = MagicMock(spec=MarketingTag)
        tag_row.tag = "title_loan_candidate"
        tag_row.tag_category = "lending"
        tag_row.confidence = 0.78
        tag_row.reasoning = ["Vehicle record found", "Financial distress 62%"]
        tag_row.scored_at = _dt.datetime(2026, 3, 24, 10, 0, 0, tzinfo=_dt.timezone.utc)

        empty_exec = MagicMock()
        empty_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        tag_exec = MagicMock()
        tag_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[tag_row])))

        call_count = {"n": 0}

        async def _execute(q):
            call_count["n"] += 1
            # Return tag result on the MarketingTag query (heuristic: after all empty fetches)
            if call_count["n"] > 14:
                return tag_exec
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_contact_card.py::TestReportCommercialTags -v`

Expected: FAIL — `assert "commercial_tags" in body` (key absent)

- [ ] **Step 3: Write minimal implementation**

In `api/routes/persons.py`, add the import at the top of `get_report()` alongside the existing imports, then append a `commercial_tags` block before the `return` statement:

Add to imports inside `get_report()`:

```python
from shared.models.marketing import MarketingTag
```

Add after the `media = await _fetch(MediaAsset)` line (before the phone_idents block):

```python
    # Commercial tags
    tags_rows = await _fetch(MarketingTag)
```

Replace the `return { ... }` dict to add the new key. Insert after `"media_assets": [_model_to_dict(m) for m in media],`:

```python
        "commercial_tags": [
            {
                "tag": t.tag,
                "category": t.tag_category,
                "confidence": t.confidence,
                "reasoning": t.reasoning if isinstance(t.reasoning, list) else [],
                "scored_at": t.scored_at.isoformat() if t.scored_at else None,
            }
            for t in tags_rows
        ],
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_contact_card.py::TestReportCommercialTags -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/persons.py tests/test_api/test_contact_card.py
git commit -m "feat: add commercial_tags to GET /persons/{id}/report"
```

---

### Task 3: Extend /report with connections

**Files:**
- Modify: `api/routes/persons.py`
- Test: `tests/test_api/test_contact_card.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_api/test_contact_card.py`:

```python
# ---------------------------------------------------------------------------
# Task 3: /report includes connections
# ---------------------------------------------------------------------------

class TestReportConnections:
    """GET /persons/{id}/report returns connections.persons and connections.entities."""

    def test_report_connections_structure(self):
        """connections key present with persons and entities sub-keys."""
        from starlette.testclient import TestClient
        from api.main import app
        from api.deps import db_session
        from shared.models.relationship import Relationship
        from shared.models.person import Person as PersonModel

        pid = uuid.uuid4()
        related_pid = uuid.uuid4()

        session = AsyncMock()

        p = MagicMock()
        p.id = pid
        p.__table__ = MagicMock(); p.__table__.columns = []
        p.full_name = "Test Person"
        p.date_of_birth = None
        for attr in ("gender","nationality","primary_language","bio","profile_image_url",
                     "relationship_score","behavioural_risk","darkweb_exposure","default_risk_score",
                     "source_reliability","freshness_score","corroboration_count","composite_quality",
                     "verification_status","conflict_flag","created_at","updated_at","meta"):
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
        related_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[related_person])))

        call_count = {"n": 0}

        async def _execute(q):
            call_count["n"] += 1
            if call_count["n"] == 15:   # Relationship query
                return rel_exec
            if call_count["n"] == 16:   # related Person lookup
                return related_exec
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_contact_card.py::TestReportConnections -v`

Expected: FAIL — `assert "connections" in body`

- [ ] **Step 3: Write minimal implementation**

Inside `get_report()` in `api/routes/persons.py`, add these imports alongside the existing block imports:

```python
from shared.models.relationship import Relationship
```

Add after `tags_rows = await _fetch(MarketingTag)`:

```python
    # Connections — person relationships
    rels_res = await session.execute(
        select(Relationship).where(Relationship.person_a_id == uid)
    )
    rels = rels_res.scalars().all()

    related_ids = [r.person_b_id for r in rels]
    related_persons: dict = {}
    if related_ids:
        rp_res = await session.execute(
            select(Person).where(Person.id.in_(related_ids))
        )
        for rp in rp_res.scalars().all():
            related_persons[rp.id] = rp
```

Add to the return dict after `"commercial_tags": [...]`:

```python
        "connections": {
            "persons": [
                {
                    "person_id": str(r.person_b_id),
                    "full_name": related_persons.get(r.person_b_id, MagicPersonStub()).full_name
                        if related_persons.get(r.person_b_id) else None,
                    "relationship_type": r.rel_type,
                    "relationship_score": r.score,
                    "shared_identifier_count": (r.evidence or {}).get("shared_identifier_count", 0),
                }
                for r in rels
            ],
            "entities": [],  # Reserved for Phase 3 entity graph
        },
```

Note: remove the `MagicPersonStub()` reference — use a safe get:

```python
        "connections": {
            "persons": [
                {
                    "person_id": str(r.person_b_id),
                    "full_name": (related_persons[r.person_b_id].full_name
                                  if r.person_b_id in related_persons else None),
                    "relationship_type": r.rel_type,
                    "relationship_score": r.score,
                    "shared_identifier_count": (r.evidence or {}).get("shared_identifier_count", 0),
                }
                for r in rels
            ],
            "entities": [],
        },
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_contact_card.py::TestReportConnections -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/persons.py tests/test_api/test_contact_card.py
git commit -m "feat: add connections block to GET /persons/{id}/report"
```

---

### Task 4: Extend /report with coverage

**Files:**
- Modify: `api/routes/persons.py`
- Test: `tests/test_api/test_contact_card.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_api/test_contact_card.py`:

```python
# ---------------------------------------------------------------------------
# Task 4: /report includes coverage
# ---------------------------------------------------------------------------

class TestReportCoverage:
    """GET /persons/{id}/report returns coverage block with live source count."""

    def test_report_coverage_structure(self):
        from starlette.testclient import TestClient
        from api.main import app
        from api.deps import db_session
        from shared.models.crawl import CrawlJob, DataSource

        pid = uuid.uuid4()

        session = AsyncMock()

        p = MagicMock()
        p.id = pid
        p.__table__ = MagicMock(); p.__table__.columns = []
        p.full_name = "Test"
        p.date_of_birth = None
        for attr in ("gender","nationality","primary_language","bio","profile_image_url",
                     "relationship_score","behavioural_risk","darkweb_exposure","default_risk_score",
                     "source_reliability","freshness_score","corroboration_count","composite_quality",
                     "verification_status","conflict_flag","created_at","updated_at","meta"):
            setattr(p, attr, None if attr != "conflict_flag" else False)
        session.get = AsyncMock(return_value=p)

        # CrawlJob for this person
        import datetime as _dt
        job = MagicMock(spec=CrawlJob)
        job.meta = {"platform": "twitter"}
        job.completed_at = _dt.datetime(2026, 3, 20, 8, 0, 0, tzinfo=_dt.timezone.utc)
        job.status = "done"
        job.source_id = None

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
            if call_count["n"] == 17:   # CrawlJob query
                return crawl_exec
            if call_count["n"] == 18:   # COUNT data_sources enabled
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
        assert cov["sources_enabled"] == 131
        assert isinstance(cov["crawl_history"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api/test_contact_card.py::TestReportCoverage -v`

Expected: FAIL — `assert "coverage" in body`

- [ ] **Step 3: Write minimal implementation**

Inside `get_report()` in `api/routes/persons.py`, add imports alongside existing block imports:

```python
from shared.models.crawl import CrawlJob, DataSource
```

Add after the connections block code:

```python
    # Coverage — crawl history for this person
    crawl_jobs_res = await session.execute(
        select(CrawlJob)
        .where(CrawlJob.person_id == uid)
        .order_by(CrawlJob.completed_at.desc().nullslast())
    )
    crawl_jobs = crawl_jobs_res.scalars().all()

    sources_enabled_count = (
        await session.execute(
            select(func.count()).select_from(DataSource).where(DataSource.is_enabled.is_(True))
        )
    ).scalar_one()

    sources_attempted = len({(j.meta or {}).get("platform", str(j.id)) for j in crawl_jobs})
    sources_found = sum(
        1 for j in crawl_jobs
        if j.status in ("done", "complete", "success", "found")
        or (j.result_count or 0) > 0
    )
    coverage_pct = (
        round(sources_found / sources_enabled_count * 100)
        if sources_enabled_count > 0 else 0
    )
```

Add to the return dict after `"connections": {...}`:

```python
        "coverage": {
            "sources_enabled": sources_enabled_count,
            "sources_attempted": sources_attempted,
            "sources_found": sources_found,
            "coverage_pct": coverage_pct,
            "crawl_history": [
                {
                    "crawler": (j.meta or {}).get("platform", "unknown"),
                    "ran_at": j.completed_at.isoformat() if j.completed_at else None,
                    "status": j.status,
                    "source_reliability": None,
                }
                for j in crawl_jobs
            ],
        },
```

- [ ] **Step 4: Run test to verify passes**

Run: `pytest tests/test_api/test_contact_card.py::TestReportCoverage -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/persons.py tests/test_api/test_contact_card.py
git commit -m "feat: add coverage block to GET /persons/{id}/report"
```

---

### Task 5: Contact card HTML layout — left rail + header + tab shell

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add CSS for contact card**

In `static/index.html`, locate the existing CSS block (ends before `</style>`). Append the following CSS rules before `</style>`:

```css
/* ── Contact Card ── */
.contact-card { display:flex; flex-direction:column; height:100%; gap:0; }
.cc-header { background:var(--bg2); border-bottom:1px solid var(--border); padding:20px 28px 16px; flex-shrink:0; }
.cc-header-row { display:flex; align-items:flex-start; gap:16px; }
.cc-avatar { width:56px; height:56px; border-radius:50%; background:var(--bg3); border:1px solid var(--border2); display:flex; align-items:center; justify-content:center; font-size:22px; color:var(--text-dim); flex-shrink:0; object-fit:cover; }
.cc-title-block { flex:1; min-width:0; }
.cc-name { font-size:22px; font-weight:700; color:#e8eef5; letter-spacing:-0.02em; }
.cc-badge-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:6px; }
.cc-tag-row { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
.comm-tag { display:inline-flex; align-items:center; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600; letter-spacing:0.04em; cursor:default; position:relative; }
.comm-tag.red    { background:rgba(229,62,62,0.18); color:#fc8181; border:1px solid rgba(229,62,62,0.3); }
.comm-tag.amber  { background:rgba(246,173,85,0.15); color:#f6ad55; border:1px solid rgba(246,173,85,0.28); }
.comm-tag.blue   { background:var(--accent-lo); color:#63b3ed; border:1px solid rgba(26,110,245,0.3); }
.comm-tag.green  { background:var(--green-lo); color:var(--green); border:1px solid rgba(0,196,140,0.3); }
.comm-tag-tooltip { display:none; position:absolute; bottom:calc(100% + 6px); left:0; background:var(--bg3); border:1px solid var(--border2); padding:8px 12px; border-radius:var(--radius); font-size:11px; color:var(--text); white-space:nowrap; z-index:100; max-width:280px; white-space:normal; line-height:1.5; }
.comm-tag:hover .comm-tag-tooltip { display:block; }
.cc-close { background:none; border:none; color:var(--text-dim); font-size:18px; cursor:pointer; padding:4px 8px; line-height:1; align-self:flex-start; }
.cc-close:hover { color:var(--text); }

/* ── Contact Card Body ── */
.cc-body { display:flex; flex:1; overflow:hidden; }
.cc-rail { width:300px; min-width:300px; background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; padding:20px 0; flex-shrink:0; }
.cc-rail-section { padding:0 20px 16px; border-bottom:1px solid var(--border); margin-bottom:16px; }
.cc-rail-section:last-child { border-bottom:none; }
.cc-rail-label { font-size:10px; font-weight:600; letter-spacing:0.1em; color:var(--text-mute); text-transform:uppercase; margin-bottom:10px; }
.cc-fact-row { display:flex; justify-content:space-between; align-items:baseline; padding:3px 0; font-size:12px; }
.cc-fact-key { color:var(--text-dim); }
.cc-fact-val { color:var(--text); font-weight:500; }
.cc-fact-val a { color:var(--text); }
.cc-fact-val a:hover { color:var(--accent); }
.cc-dials { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding:4px 0; }
.cc-dial-item { text-align:center; }
.cc-dial-ring { width:54px; height:54px; margin:0 auto 4px; }
.cc-dial-label { font-size:10px; color:var(--text-dim); }
.cc-actions { display:flex; flex-direction:column; gap:6px; }
.cc-action-btn { background:var(--bg3); border:1px solid var(--border); color:var(--text); padding:7px 12px; border-radius:var(--radius); font-size:12px; cursor:pointer; font-family:var(--font); text-align:left; transition:all 0.15s; }
.cc-action-btn:hover { border-color:var(--accent); color:#e8eef5; }

/* ── Tabs ── */
.cc-main { flex:1; display:flex; flex-direction:column; overflow:hidden; }
.cc-tabs { display:flex; border-bottom:1px solid var(--border); padding:0 24px; background:var(--bg2); flex-shrink:0; }
.cc-tab { padding:12px 16px; font-size:13px; color:var(--text-dim); cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-1px; transition:all 0.15s; }
.cc-tab:hover { color:var(--text); }
.cc-tab.active { color:#e8eef5; border-bottom-color:var(--accent); }
.cc-tab-content { flex:1; overflow-y:auto; padding:24px; }
.cc-tab-pane { display:none; }
.cc-tab-pane.active { display:block; }

/* ── Identity tab rows ── */
.id-row { display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); font-size:12px; }
.id-row:last-child { border-bottom:none; }
.id-type-badge { font-size:10px; background:var(--bg3); border:1px solid var(--border); color:var(--text-dim); padding:2px 7px; border-radius:3px; white-space:nowrap; flex-shrink:0; }
.id-value { flex:1; font-family:var(--mono); color:var(--text); font-size:11px; word-break:break-all; }
.id-value a { color:var(--text); font-family:var(--mono); }
.id-value a:hover { color:var(--accent); }
.id-conf { color:var(--text-dim); font-size:10px; white-space:nowrap; }
.id-scraped { color:var(--text-mute); font-size:10px; white-space:nowrap; }

/* ── Connections tab ── */
.conn-person-card { background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius); padding:12px 14px; margin-bottom:8px; display:flex; align-items:center; gap:12px; }
.conn-person-card:hover { border-color:var(--border2); }
.conn-person-name { font-weight:600; color:#e8eef5; font-size:13px; }
.conn-person-meta { font-size:11px; color:var(--text-dim); margin-top:2px; }
.conn-entity-row { display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); font-size:12px; }

/* ── Risk tab bars ── */
.risk-signal-row { display:flex; align-items:center; gap:10px; padding:6px 0; font-size:12px; }
.risk-signal-label { width:160px; color:var(--text-dim); flex-shrink:0; }
.risk-signal-bar-wrap { flex:1; background:var(--bg3); border-radius:3px; height:6px; overflow:hidden; }
.risk-signal-bar { height:100%; border-radius:3px; transition:width 0.3s; }
.risk-signal-val { width:36px; text-align:right; color:var(--text-dim); font-size:11px; }
.ocean-section-title { font-size:11px; font-weight:600; letter-spacing:0.08em; color:var(--text-mute); text-transform:uppercase; margin:18px 0 8px; }

/* ── Activity tab ── */
.activity-row { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px solid var(--border); font-size:12px; }
.activity-crawler { font-family:var(--mono); font-size:11px; color:var(--text); width:160px; flex-shrink:0; }
.activity-status { font-size:10px; padding:2px 7px; border-radius:3px; }
.activity-status.found    { background:var(--green-lo); color:var(--green); }
.activity-status.not-found { background:var(--bg3); color:var(--text-mute); }
.activity-status.error    { background:var(--red-lo); color:var(--red); }
.activity-status.done     { background:var(--green-lo); color:var(--green); }
.coverage-bar-wrap { background:var(--bg3); border-radius:4px; height:8px; overflow:hidden; margin:8px 0; }
.coverage-bar { height:100%; background:var(--accent); border-radius:4px; transition:width 0.4s; }
```

- [ ] **Step 2: Verify CSS was added correctly**

Confirm the CSS block compiles — open the file in browser, check no syntax errors in DevTools.

- [ ] **Step 3: Replace `renderPerson()` shell**

Find the existing `renderPerson(id)` function in `static/index.html` (starts at line ~1386, ends at the matching closing `}`). Replace the entire function with the new shell that builds the card layout and wires up tabs. The full new function begins with the layout scaffold below; tab content is populated in Tasks 6–9:

```javascript
  async renderPerson(id) {
    if (this._lp) { this._lp.disconnect(); this._lp=null; }
    this.root.textContent='';

    const wrap = div('contact-card');
    this.root.appendChild(wrap);

    // ── Loading state
    const loadMsg = div('cc-header');
    loadMsg.appendChild(span('dim','Loading dossier…'));
    wrap.appendChild(loadMsg);

    let d;
    try {
      d = await apiGet('/persons/'+id+'/report');
    } catch(e) {
      wrap.textContent='';
      const errEl = div('card'); errEl.style.margin='40px auto'; errEl.style.maxWidth='500px';
      const eb = div('card-body');
      eb.appendChild(span('red','Failed to load report: '+e.message));
      errEl.appendChild(eb); wrap.appendChild(errEl);
      return;
    }

    wrap.textContent='';
    const p = d.person;

    // ── HEADER ────────────────────────────────────────────────────
    const header = div('cc-header');
    const hRow = div('cc-header-row');

    // Avatar
    if (p.profile_image_url) {
      const img = el('img','cc-avatar'); img.src=p.profile_image_url; img.alt='';
      img.onerror=()=>{ img.replaceWith(avatarEl); };
      hRow.appendChild(img);
    } else {
      const avatarEl = div('cc-avatar','◎');
      hRow.appendChild(avatarEl);
    }

    const titleBlock = div('cc-title-block');
    titleBlock.appendChild(div('cc-name', p.full_name||'Unknown'));

    // Badges
    const badgeRow = div('cc-badge-row');
    const rTag = span('tag'); rTag.style.cssText=`background:${riskColor(p.default_risk_score)};color:#fff;border:none`;
    rTag.textContent = riskTier(p.default_risk_score)+' RISK';
    const qTag = span('tag muted'); qTag.textContent = Math.round((p.composite_quality||0)*100)+' Quality';
    badgeRow.append(rTag, qTag);
    if (p.verification_status==='verified') { const vt=span('tag green','✓ VERIFIED'); badgeRow.appendChild(vt); }
    if (p.conflict_flag) { const cf=span('tag red','⚠ CONFLICT'); badgeRow.appendChild(cf); }
    titleBlock.appendChild(badgeRow);

    // Commercial tags
    if (d.commercial_tags && d.commercial_tags.length > 0) {
      const tagRow = div('cc-tag-row');
      d.commercial_tags.forEach(t => {
        const color = _commTagColor(t.tag);
        const pill = div('comm-tag '+color);
        pill.textContent = _commTagLabel(t.tag);
        const tooltip = div('comm-tag-tooltip');
        const reasons = Array.isArray(t.reasoning) ? t.reasoning : [];
        tooltip.textContent = reasons.length ? reasons.join(' · ') : t.tag;
        pill.appendChild(tooltip);
        tagRow.appendChild(pill);
      });
      titleBlock.appendChild(tagRow);
    }

    hRow.appendChild(titleBlock);

    const closeBtn = el('button','cc-close','×');
    closeBtn.onclick = ()=>{ location.hash='#/persons'; };
    hRow.appendChild(closeBtn);

    header.appendChild(hRow);
    wrap.appendChild(header);

    // ── BODY ─────────────────────────────────────────────────────
    const body = div('cc-body');

    // ── LEFT RAIL ────────────────────────────────────────────────
    const rail = div('cc-rail');

    // Quick facts
    const factsSection = div('cc-rail-section');
    factsSection.appendChild(div('cc-rail-label','Quick Facts'));
    const facts = [
      { k:'DOB', v: p.date_of_birth, link: p.date_of_birth ? '#/search?q='+encodeURIComponent(p.date_of_birth)+'&type=dob' : null },
      { k:'Gender',      v: p.gender },
      { k:'Nationality', v: p.nationality },
      { k:'Language',    v: p.primary_language },
    ];
    facts.forEach(f => {
      if (!f.v) return;
      const row = div('cc-fact-row');
      row.appendChild(div('cc-fact-key', f.k));
      const valEl = div('cc-fact-val');
      if (f.link) { const a=el('a',''); a.href=f.link; a.textContent=f.v; valEl.appendChild(a); }
      else { valEl.textContent=f.v; }
      row.appendChild(valEl);
      factsSection.appendChild(row);
    });
    rail.appendChild(factsSection);

    // Score dials
    const dialsSection = div('cc-rail-section');
    dialsSection.appendChild(div('cc-rail-label','Risk Scores'));
    const dialsGrid = div('cc-dials');
    const dialDefs = [
      {label:'Default',   score:p.default_risk_score},
      {label:'Behaviour', score:p.behavioural_risk},
      {label:'Dark Web',  score:p.darkweb_exposure},
      {label:'Relations', score:p.relationship_score},
    ];
    dialDefs.forEach(dd => {
      const item = div('cc-dial-item');
      const pct = Math.round((dd.score||0)*100);
      const color = dd.score > 0.6 ? '#e53e3e' : dd.score > 0.3 ? '#f6ad55' : '#00c48c';
      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS,'svg');
      svg.setAttribute('viewBox','0 0 54 54'); svg.setAttribute('width','54'); svg.setAttribute('height','54');
      svg.classList.add('cc-dial-ring');
      const r=22, cx=27, cy=27, circ=2*Math.PI*r;
      const trackC = document.createElementNS(svgNS,'circle');
      trackC.setAttribute('cx',cx); trackC.setAttribute('cy',cy); trackC.setAttribute('r',r);
      trackC.setAttribute('fill','none'); trackC.setAttribute('stroke','#1e2a38'); trackC.setAttribute('stroke-width','5');
      const fillC = document.createElementNS(svgNS,'circle');
      fillC.setAttribute('cx',cx); fillC.setAttribute('cy',cy); fillC.setAttribute('r',r);
      fillC.setAttribute('fill','none'); fillC.setAttribute('stroke',color); fillC.setAttribute('stroke-width','5');
      fillC.setAttribute('stroke-dasharray',circ); fillC.setAttribute('stroke-dashoffset', circ*(1-pct/100));
      fillC.setAttribute('transform',`rotate(-90 ${cx} ${cy})`);
      const txt = document.createElementNS(svgNS,'text');
      txt.setAttribute('x',cx); txt.setAttribute('y',cy+1); txt.setAttribute('text-anchor','middle');
      txt.setAttribute('dominant-baseline','middle'); txt.setAttribute('font-size','11');
      txt.setAttribute('fill','#c9d6e3'); txt.setAttribute('font-family','Inter,system-ui,sans-serif');
      txt.textContent=pct;
      svg.append(trackC, fillC, txt);
      item.appendChild(svg);
      item.appendChild(div('cc-dial-label', dd.label));
      dialsGrid.appendChild(item);
    });
    dialsSection.appendChild(dialsGrid);
    rail.appendChild(dialsSection);

    // Actions
    const actSection = div('cc-rail-section');
    actSection.appendChild(div('cc-rail-label','Actions'));
    const actions = div('cc-actions');
    const actDefs = [
      { label:'View in Graph',    href:'#/graph?entity=person&q='+id },
      { label:'Re-Enrich',        onclick: ()=>{ apiPost('/persons/'+id+'/enrich',{}).catch(()=>{}); } },
      { label:'Export Report',    onclick: ()=>{ window.open('/persons/'+id+'/report','_blank'); } },
      { label:'Flag for Review',  onclick: ()=>{ apiPost('/persons/'+id+'/flag',{}).catch(()=>{}); } },
    ];
    actDefs.forEach(a => {
      const btn = el('button','cc-action-btn', a.label);
      if (a.href) btn.onclick=()=>{ location.hash=a.href; };
      else if (a.onclick) btn.onclick=a.onclick;
      actions.appendChild(btn);
    });
    actSection.appendChild(actions);
    rail.appendChild(actSection);

    body.appendChild(rail);

    // ── MAIN TABBED AREA ─────────────────────────────────────────
    const main = div('cc-main');

    // Tab bar
    const tabBar = div('cc-tabs');
    const tabNames = ['Identity','Connections','Risk','Activity'];
    const tabPanes = {};
    tabNames.forEach((name,i) => {
      const tab = div('cc-tab', name);
      tab.dataset.tab = name;
      if (i===0) tab.classList.add('active');
      tab.onclick = ()=>{
        tabBar.querySelectorAll('.cc-tab').forEach(t=>t.classList.remove('active'));
        tab.classList.add('active');
        Object.values(tabPanes).forEach(pane=>pane.classList.remove('active'));
        tabPanes[name].classList.add('active');
      };
      tabBar.appendChild(tab);
    });
    main.appendChild(tabBar);

    const tabContent = div('cc-tab-content');
    tabNames.forEach((name,i) => {
      const pane = div('cc-tab-pane'+(i===0?' active':''));
      pane.id = 'cc-pane-'+name.toLowerCase();
      tabPanes[name] = pane;
      tabContent.appendChild(pane);
    });
    main.appendChild(tabContent);

    body.appendChild(main);
    wrap.appendChild(body);

    // Populate tabs (Tasks 6-9 fill these)
    _renderIdentityTab(tabPanes['Identity'], d);
    _renderConnectionsTab(tabPanes['Connections'], d);
    _renderRiskTab(tabPanes['Risk'], d, p);
    _renderActivityTab(tabPanes['Activity'], d);

    // Live feed — start long-polling for person enrichment
    this._startLiveFeed(id, tabPanes['Activity']);
  }
```

- [ ] **Step 4: Verify the shell renders without errors**

Load the SPA in a browser, navigate to a person. Expected: contact card frame renders with left rail + empty tabs (no JS console errors).

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat: add contact card HTML/CSS shell with left rail and tab structure"
```

---

### Task 6: Identity tab JS implementation

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add `_renderIdentityTab` helper function**

Locate the area just before `renderPerson()` (or after the last top-level helper function). Add:

```javascript
  function _renderIdentityTab(pane, d) {
    // Section: identifiers
    const h1 = div('cc-rail-label'); h1.style.marginBottom='12px'; h1.textContent='IDENTIFIERS';
    pane.appendChild(h1);

    (d.identifiers||[]).forEach(i => {
      const row = div('id-row');
      const badge = div('id-type-badge', i.type||'?');
      const valEl = div('id-value');
      const a = el('a','');
      if (i.type==='email')  { a.href='#/search?q='+encodeURIComponent(i.value)+'&type=email'; }
      else if (i.type==='phone') { a.href='#/search?q='+encodeURIComponent(i.value)+'&type=phone'; }
      else { a.href='#/search?q='+encodeURIComponent(i.value)+'&type='+encodeURIComponent(i.type); }
      a.textContent = i.value||'—';
      valEl.appendChild(a);
      if (i.type==='phone') {
        if (i.whatsapp_confirmed) { const w=span('wa-confirmed','WA ✓'); valEl.appendChild(w); }
        if (i.telegram_confirmed) { const t=span('wa-confirmed tg-confirmed','TG ✓'); valEl.appendChild(t); }
      }
      const confEl = div('id-conf', Math.round((i.confidence||0)*100)+'%');
      const relEl = div(''); relEl.appendChild(relBadge(i.source_reliability));
      const scraped = div('id-scraped', i.last_scraped_at ? fmtDate(i.last_scraped_at) : '');
      row.append(badge, valEl, confEl, relEl, scraped);
      pane.appendChild(row);
    });

    // Section: addresses
    if (d.addresses && d.addresses.length > 0) {
      const h2 = div('cc-rail-label'); h2.style.cssText='margin:18px 0 10px'; h2.textContent='ADDRESSES';
      pane.appendChild(h2);
      d.addresses.forEach(a => {
        const row = div('id-row');
        const badge = div('id-type-badge', a.is_current ? 'current' : 'historical');
        const valEl = div('id-value');
        const parts = [a.street, a.city, a.state_province, a.postal_code, a.country].filter(Boolean).join(', ');
        const mapsUrl = 'https://www.google.com/maps/search/'+encodeURIComponent(parts);
        const link = el('a',''); link.href=mapsUrl; link.target='_blank'; link.rel='noopener'; link.textContent=parts||'—';
        valEl.appendChild(link);
        const scraped = div('id-scraped', a.last_scraped_at ? fmtDate(a.last_scraped_at) : '');
        row.append(badge, valEl, scraped);
        pane.appendChild(row);
      });
    }

    // Section: social profiles
    if (d.social_profiles && d.social_profiles.length > 0) {
      const h3 = div('cc-rail-label'); h3.style.cssText='margin:18px 0 10px'; h3.textContent='SOCIAL PROFILES';
      pane.appendChild(h3);
      const _platformUrls = {
        twitter: h => 'https://twitter.com/'+h,
        instagram: h => 'https://instagram.com/'+h,
        tiktok: h => 'https://tiktok.com/@'+h,
        linkedin: h => 'https://linkedin.com/in/'+h,
        reddit: h => 'https://reddit.com/user/'+h,
        github: h => 'https://github.com/'+h,
        youtube: h => 'https://youtube.com/@'+h,
      };
      d.social_profiles.forEach(s => {
        const row = div('id-row');
        const badge = div('id-type-badge', s.platform||'?');
        const valEl = div('id-value');
        const urlFn = _platformUrls[s.platform];
        if (urlFn && s.handle) {
          const a = el('a',''); a.href=urlFn(s.handle); a.target='_blank'; a.rel='noopener';
          a.textContent = '@'+(s.handle||s.display_name||'—');
          valEl.appendChild(a);
        } else {
          valEl.textContent = s.handle||s.display_name||'—';
        }
        const scraped = div('id-scraped', s.last_scraped_at ? fmtDate(s.last_scraped_at) : '');
        row.append(badge, valEl, div('id-conf', s.is_verified?'✓ verified':''), scraped);
        pane.appendChild(row);
      });
    }

    // Section: employment
    if (d.employment && d.employment.length > 0) {
      const h4 = div('cc-rail-label'); h4.style.cssText='margin:18px 0 10px'; h4.textContent='EMPLOYMENT';
      pane.appendChild(h4);
      d.employment.forEach(e => {
        const row = div('id-row');
        const badge = div('id-type-badge', e.is_current ? 'current' : 'former');
        const valEl = div('id-value');
        const compLink = el('a','');
        compLink.href = '#/graph?entity=company&q='+encodeURIComponent(e.employer_name||'');
        compLink.textContent = e.employer_name||'Unknown';
        valEl.append(compLink);
        if (e.job_title) { const t=span('dim'); t.style.marginLeft='6px'; t.textContent=e.job_title; valEl.appendChild(t); }
        const meta = div('id-scraped');
        if (e.started_at) meta.textContent = fmtDate(e.started_at) + (e.ended_at ? ' → '+fmtDate(e.ended_at) : ' → present');
        row.append(badge, valEl, meta);
        pane.appendChild(row);
      });
    }

    // Section: aliases
    if (d.aliases && d.aliases.length > 0) {
      const h5 = div('cc-rail-label'); h5.style.cssText='margin:18px 0 10px'; h5.textContent='ALIASES';
      pane.appendChild(h5);
      d.aliases.forEach(a => {
        const row = div('id-row');
        const badge = div('id-type-badge', a.alias_type||'alias');
        const valEl = div('id-value'); valEl.textContent=a.name||'—';
        row.append(badge, valEl);
        pane.appendChild(row);
      });
    }
  }
```

- [ ] **Step 2: Verify identity tab renders**

Navigate to a person in the SPA. Click Identity tab. Expected: rows for identifiers (clickable links), addresses (Google Maps link), social profiles (platform URLs), employment (company graph links).

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: implement Identity tab with clickable fields in contact card"
```

---

### Task 7: Connections tab JS implementation

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add `_renderConnectionsTab` helper**

```javascript
  function _renderConnectionsTab(pane, d) {
    const conn = d.connections || {persons:[], entities:[]};

    // Person relationships
    const h1 = div('cc-rail-label'); h1.style.marginBottom='12px'; h1.textContent='PERSON RELATIONSHIPS';
    pane.appendChild(h1);

    if (!conn.persons || conn.persons.length === 0) {
      pane.appendChild(span('dim','No person relationships found.'));
    } else {
      conn.persons.forEach(r => {
        const card = div('conn-person-card');
        const info = div('');
        const nameLink = el('a','conn-person-name');
        nameLink.href = '#/persons/'+r.person_id;
        nameLink.textContent = r.full_name||'Unknown';
        const meta = div('conn-person-meta');
        const parts = [r.relationship_type];
        if (r.relationship_score != null) parts.push('score: '+Math.round(r.relationship_score*100)+'%');
        if (r.shared_identifier_count) parts.push(r.shared_identifier_count+' shared identifiers');
        meta.textContent = parts.join(' · ');
        info.append(nameLink, meta);
        const scorePct = Math.round((r.relationship_score||0)*100);
        const scoreEl = div('');
        scoreEl.style.cssText='margin-left:auto;font-size:18px;font-weight:700;color:'+
          (scorePct>70?'var(--green)':scorePct>40?'var(--yellow)':'var(--text-dim)');
        scoreEl.textContent = scorePct;
        card.append(info, scoreEl);
        pane.appendChild(card);
      });
    }

    // Entity connections
    if (conn.entities && conn.entities.length > 0) {
      const h2 = div('cc-rail-label'); h2.style.cssText='margin:18px 0 10px'; h2.textContent='ENTITY CONNECTIONS';
      pane.appendChild(h2);
      conn.entities.forEach(e => {
        const row = div('conn-entity-row');
        const badge = div('id-type-badge', e.entity_type||'entity');
        const valEl = div('id-value');
        if (e.entity_type==='company') {
          const a=el('a',''); a.href='#/graph?entity=company&q='+encodeURIComponent(e.label||'');
          a.textContent=e.label||'—'; valEl.appendChild(a);
        } else if (e.entity_type==='domain') {
          const a=el('a',''); a.href='https://urlscan.io/search/#'+encodeURIComponent(e.label||'');
          a.target='_blank'; a.rel='noopener'; a.textContent=e.label||'—'; valEl.appendChild(a);
        } else {
          valEl.textContent = e.label||'—';
        }
        const src = div('id-scraped', e.source||'');
        const via = div('id-conf', e.linked_via||'');
        row.append(badge, valEl, via, src);
        pane.appendChild(row);
      });
    } else if (conn.persons && conn.persons.length > 0) {
      // Only show placeholder if there are persons but no entities
      const h2 = div('cc-rail-label'); h2.style.cssText='margin:18px 0 10px'; h2.textContent='ENTITY CONNECTIONS';
      pane.appendChild(h2);
      pane.appendChild(span('dim','Entity connections not yet enriched.'));
    }
  }
```

- [ ] **Step 2: Verify connections tab renders**

Navigate to a person with relationships. Click Connections tab. Expected: person connection cards with clickable name links (`#/persons/<id>`), relationship type, score.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: implement Connections tab in contact card"
```

---

### Task 8: Risk tab JS implementation (OCEAN + behavioral signals)

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add `_renderRiskTab` helper**

```javascript
  function _renderRiskTab(pane, d, p) {
    const bp = (d.behavioural_profiles && d.behavioural_profiles.length > 0)
      ? d.behavioural_profiles[0] : null;

    // Behavioral signals
    const h1 = div('cc-rail-label'); h1.style.marginBottom='12px'; h1.textContent='BEHAVIOURAL SIGNALS';
    pane.appendChild(h1);

    const signals = bp ? [
      {label:'Gambling',          val: bp.gambling_score},
      {label:'Financial Distress',val: bp.financial_distress_score},
      {label:'Drug Signal',       val: bp.drug_signal_score},
      {label:'Violence',          val: bp.violence_score},
      {label:'Fraud',             val: bp.fraud_score},
      {label:'Criminal Signal',   val: bp.criminal_signal_score},
    ] : [];

    if (signals.length === 0 || signals.every(s=>!s.val)) {
      pane.appendChild(span('dim','No behavioural data.'));
    } else {
      signals.forEach(s => {
        const row = div('risk-signal-row');
        const lbl = div('risk-signal-label', s.label);
        const barWrap = div('risk-signal-bar-wrap');
        const bar = div('risk-signal-bar');
        const pct = Math.round((s.val||0)*100);
        bar.style.width = pct+'%';
        bar.style.background = pct>60?'var(--red)':pct>30?'var(--yellow)':'var(--accent)';
        barWrap.appendChild(bar);
        const valEl = div('risk-signal-val', pct+'%');
        row.append(lbl, barWrap, valEl);
        pane.appendChild(row);
      });
    }

    // OCEAN traits — only if persisted in meta
    const meta = bp ? (bp.meta||{}) : {};
    if (meta.ocean_openness != null) {
      pane.appendChild(div('ocean-section-title','OCEAN PERSONALITY TRAITS'));
      const oceanTraits = [
        {label:'Openness',          val: meta.ocean_openness},
        {label:'Conscientiousness', val: meta.ocean_conscientiousness},
        {label:'Extraversion',      val: meta.ocean_extraversion},
        {label:'Agreeableness',     val: meta.ocean_agreeableness},
        {label:'Neuroticism',       val: meta.ocean_neuroticism},
      ];
      oceanTraits.forEach(t => {
        if (t.val == null) return;
        const row = div('risk-signal-row');
        const lbl = div('risk-signal-label', t.label);
        const barWrap = div('risk-signal-bar-wrap');
        const bar = div('risk-signal-bar');
        const pct = Math.round((t.val||0)*100);
        bar.style.width = pct+'%';
        bar.style.background = 'var(--purple)';
        barWrap.appendChild(bar);
        const valEl = div('risk-signal-val', pct+'%');
        row.append(lbl, barWrap, valEl);
        pane.appendChild(row);
      });
    }

    // Watchlist
    if (d.watchlist_matches && d.watchlist_matches.length > 0) {
      const h2 = div('cc-rail-label'); h2.style.cssText='margin:18px 0 10px'; h2.textContent='WATCHLIST MATCHES';
      pane.appendChild(h2);
      d.watchlist_matches.forEach(w => {
        const row = div('id-row');
        const badge = div('id-type-badge red'); badge.style.cssText='background:var(--red-lo);color:var(--red);border-color:var(--red)'; badge.textContent='SANCTIONS';
        const valEl = div('id-value'); valEl.textContent=w.list_name+': '+w.match_name;
        const conf = div('id-conf', Math.round((w.match_score||0)*100)+'%');
        row.append(badge, valEl, conf);
        pane.appendChild(row);
      });
    }

    // Dark web
    if (d.darkweb_mentions && d.darkweb_mentions.length > 0) {
      const h3 = div('cc-rail-label'); h3.style.cssText='margin:18px 0 10px'; h3.textContent='DARK WEB MENTIONS';
      pane.appendChild(h3);
      d.darkweb_mentions.slice(0,5).forEach(m => {
        const row = div('id-row');
        const badge = div('id-type-badge'); badge.style.cssText='background:var(--purple-lo);color:var(--purple)'; badge.textContent=m.source_type||'darkweb';
        const valEl = div('id-value'); valEl.textContent=(m.mention_context||'').substring(0,80)||'[no preview]';
        row.append(badge, valEl);
        pane.appendChild(row);
      });
    }

    // Criminal records (from report, not extra API call)
    if (d.criminal_records && d.criminal_records.length > 0) {
      const h4 = div('cc-rail-label'); h4.style.cssText='margin:18px 0 10px'; h4.textContent='CRIMINAL RECORDS';
      pane.appendChild(h4);
      d.criminal_records.forEach(r => {
        const row = div('id-row');
        const badge = div('id-type-badge'); badge.textContent=r.offense_level||'unknown';
        badge.style.cssText = r.offense_level==='felony'?'background:var(--red-lo);color:var(--red)':'';
        const valEl = div('id-value');
        if (r.court_name) {
          const clUrl = 'https://www.courtlistener.com/?q='+encodeURIComponent(r.court_case_number||r.charge||'');
          const a=el('a',''); a.href=clUrl; a.target='_blank'; a.rel='noopener';
          a.textContent=r.charge||r.court_name||'Unknown charge'; valEl.appendChild(a);
        } else {
          valEl.textContent = r.charge||r.offense_description||'Unknown charge';
        }
        const meta2 = div('id-scraped');
        if (r.court_name) meta2.textContent=r.court_name;
        row.append(badge, valEl, meta2);
        pane.appendChild(row);
      });
    }

    // Breach records
    if (d.breach_records && d.breach_records.length > 0) {
      const h5 = div('cc-rail-label'); h5.style.cssText='margin:18px 0 10px'; h5.textContent='DATA BREACHES';
      pane.appendChild(h5);
      d.breach_records.forEach(b => {
        const row = div('id-row');
        const badge = div('id-type-badge', b.source_type||'breach');
        const valEl = div('id-value'); valEl.textContent=b.breach_name||'Unknown breach';
        const date2 = div('id-scraped', b.breach_date ? fmtDate(b.breach_date) : '');
        row.append(badge, valEl, date2);
        pane.appendChild(row);
      });
    }
  }
```

- [ ] **Step 2: Verify risk tab renders**

Click Risk tab on a person. Expected: behavioral signal bars, OCEAN section appears only when OCEAN data exists in meta, watchlist rows link-free (they are display only), criminal records link to CourtListener URL.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: implement Risk tab with OCEAN, behavioral signals, and watchlist in contact card"
```

---

### Task 9: Activity tab + coverage % implementation

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add `_renderActivityTab` helper**

```javascript
  function _renderActivityTab(pane, d) {
    const cov = d.coverage || {sources_enabled:0, sources_attempted:0, sources_found:0, coverage_pct:0, crawl_history:[]};

    // Coverage bar
    const covSection = div('');
    covSection.style.marginBottom = '20px';
    const covLabelRow = div('');
    covLabelRow.style.cssText = 'display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px';
    const covLabel = span('dim', 'Coverage: '+cov.sources_found+' of '+cov.sources_enabled+' enabled sources');
    const covPct = span(''); covPct.style.fontWeight='600'; covPct.textContent = cov.coverage_pct+'%';
    covLabelRow.append(covLabel, covPct);
    const barWrap = div('coverage-bar-wrap');
    const bar = div('coverage-bar');
    bar.style.width = cov.coverage_pct+'%';
    barWrap.appendChild(bar);
    const covMeta = div('');
    covMeta.style.cssText = 'font-size:11px;color:var(--text-mute);margin-top:6px';
    covMeta.textContent = cov.sources_attempted+' sources attempted';
    covSection.append(covLabelRow, barWrap, covMeta);
    pane.appendChild(covSection);

    // Crawl history table
    const h1 = div('cc-rail-label'); h1.style.marginBottom='10px'; h1.textContent='CRAWL HISTORY';
    pane.appendChild(h1);

    const history = cov.crawl_history||[];
    if (history.length === 0) {
      pane.appendChild(span('dim','No crawl history for this person.'));
      return;
    }

    history.forEach(job => {
      const row = div('activity-row');
      const crawlerEl = div('activity-crawler', job.crawler||'unknown');
      const statusClass = (job.status||'').includes('found')||job.status==='done'||job.status==='success'
        ? 'found'
        : (job.status||'').includes('error') ? 'error' : 'not-found';
      const statusEl = div('activity-status '+statusClass, job.status||'—');
      const dateEl = div('id-scraped', job.ran_at ? fmtDate(job.ran_at) : '—');
      const relEl = div('');
      if (job.source_reliability != null) relEl.appendChild(relBadge(job.source_reliability));
      row.append(crawlerEl, statusEl, dateEl, relEl);
      pane.appendChild(row);
    });
  }
```

- [ ] **Step 2: Verify activity tab renders**

Click Activity tab. Expected: coverage percentage bar with `sources_found / sources_enabled` denominator pulled from live DB count (not hardcoded), crawl history rows with status badges.

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: implement Activity tab with live coverage percentage in contact card"
```

---

### Task 10: Commercial tags pill badges + click handlers + helper functions

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add tag color and label helper functions**

Locate the global helper functions area in `static/index.html` (near `riskColor()`, `relBadge()`, etc.). Add:

```javascript
  function _commTagColor(tag) {
    const RED   = ['active_gambler','casino_gambler','sports_bettor','online_gambler','payday_loan_candidate'];
    const AMBER = ['title_loan_candidate','auto_loan_candidate','personal_loan_candidate','debt_consolidation'];
    const BLUE  = ['mortgage_ready','refinance_candidate','crypto_investor','real_estate_investor','retirement_planning','credit_card_candidate'];
    const GREEN = ['luxury_buyer','retiring_soon','borrower:prime'];
    if (RED.includes(tag))   return 'red';
    if (AMBER.includes(tag)) return 'amber';
    if (BLUE.includes(tag))  return 'blue';
    if (GREEN.includes(tag)) return 'green';
    if (tag.startsWith('borrower:')) return tag.includes('prime')&&!tag.includes('sub') ? 'green' : 'amber';
    return 'blue';
  }

  function _commTagLabel(tag) {
    const MAP = {
      title_loan_candidate:   'TITLE LOAN',
      payday_loan_candidate:  'PAYDAY LOAN',
      personal_loan_candidate:'PERSONAL LOAN',
      mortgage_ready:         'MORTGAGE',
      refinance_candidate:    'REFINANCE',
      auto_loan_candidate:    'AUTO LOAN',
      debt_consolidation:     'DEBT CONSOLIDATION',
      credit_card_candidate:  'CREDIT CARD',
      crypto_investor:        'CRYPTO',
      real_estate_investor:   'REAL ESTATE',
      retirement_planning:    'RETIREMENT',
      active_gambler:         'GAMBLING',
      casino_gambler:         'CASINO',
      sports_bettor:          'SPORTS BETTING',
      online_gambler:         'ONLINE GAMBLING',
      luxury_buyer:           'LUXURY BUYER',
      travel_enthusiast:      'TRAVEL',
      fitness_enthusiast:     'FITNESS',
      bargain_hunter:         'BARGAIN HUNTER',
      new_parent:             'NEW PARENT',
      newly_married:          'NEWLY MARRIED',
      recently_divorced:      'DIVORCED',
      recent_mover:           'RECENT MOVER',
      recent_graduate:        'GRADUATE',
      retiring_soon:          'RETIRING SOON',
    };
    if (MAP[tag]) return MAP[tag];
    if (tag.startsWith('borrower:')) return tag.replace('borrower:','').replace('_',' ').toUpperCase()+' BORROWER';
    return tag.replace(/_/g,' ').toUpperCase();
  }
```

- [ ] **Step 2: Verify commercial tags display**

Navigate to a person that has been tagged by the marketing tags engine. Expected: colored pill badges appear in the header beneath the person name, hovering shows reasoning tooltip.

- [ ] **Step 3: Run all contact card tests**

Run: `pytest tests/test_api/test_contact_card.py -v`

Expected: all tests PASS

- [ ] **Step 4: Run full test suite to check for regressions**

Run: `pytest tests/ -v --tb=short -q`

Expected: all previously passing tests continue to PASS

- [ ] **Step 5: Commit**

```bash
git add static/index.html tests/test_api/test_contact_card.py
git commit -m "feat: add commercial tag helpers and complete Phase 2 contact intelligence card"
```

---

## Summary of changes

| File | Change |
|------|--------|
| `modules/pipeline/aggregator.py` | OCEAN traits written to `BehaviouralProfile.meta` in `_handle_behavioural()` |
| `api/routes/persons.py` | `GET /persons/{id}/report` extended with `commercial_tags`, `connections`, `coverage` |
| `static/index.html` | `renderPerson()` replaced with full-screen contact card (left rail + 4 tabs); helper functions `_renderIdentityTab`, `_renderConnectionsTab`, `_renderRiskTab`, `_renderActivityTab`, `_commTagColor`, `_commTagLabel` added |
| `tests/test_api/test_contact_card.py` | New test file covering OCEAN persistence, commercial_tags, connections, and coverage API contracts |

## Clickable field routing table (implemented in Task 6)

| Field | Target |
|-------|--------|
| Email | `#/search?q=<email>&type=email` |
| Phone | `#/search?q=<phone>&type=phone` |
| Street address | Google Maps `https://www.google.com/maps/search/<address>` (new tab) |
| Social handle | Platform URL (new tab, per `_platformUrls` map) |
| Company name | `#/graph?entity=company&q=<name>` |
| Related person | `#/persons/<id>` |
| Criminal court | `https://www.courtlistener.com/?q=<case_number>` (new tab) |
| Domain | `https://urlscan.io/search/#<domain>` (new tab) |
| DOB | `#/search?q=<dob>&type=dob` |
