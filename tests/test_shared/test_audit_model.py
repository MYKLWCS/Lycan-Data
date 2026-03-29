"""Tests for SystemAudit model — Task 1 of Phase 6."""

import uuid
from datetime import timezone, datetime, timezone

import pytest

# Force full mapper resolution so Person's CriminalRecord relationship resolves
import shared.models  # noqa: F401


def test_system_audit_instantiation():
    from shared.models.audit import SystemAudit

    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=100,
        persons_low_coverage=10,
        persons_stale=5,
        persons_conflict=2,
        crawlers_total=8,
        crawlers_healthy=7,
        crawlers_degraded=[{"name": "example_crawler", "success_rate": 0.0}],
        tags_assigned_today=50,
        merges_today=3,
        persons_ingested_today=20,
    )
    assert sa.persons_total == 100
    assert sa.crawlers_degraded[0]["name"] == "example_crawler"
    assert isinstance(sa.meta, dict)


def test_system_audit_tablename():
    from shared.models.audit import SystemAudit

    assert SystemAudit.__tablename__ == "system_audits"


def test_system_audit_has_id():
    from shared.models.audit import SystemAudit

    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=0,
        persons_low_coverage=0,
        persons_stale=0,
        persons_conflict=0,
        crawlers_total=0,
        crawlers_healthy=0,
        crawlers_degraded=[],
        tags_assigned_today=0,
        merges_today=0,
        persons_ingested_today=0,
    )
    # id has a default factory — should be a UUID after construction
    assert sa.id is not None
    assert isinstance(sa.id, uuid.UUID)


def test_system_audit_meta_defaults_to_dict():
    from shared.models.audit import SystemAudit

    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=5,
        persons_low_coverage=1,
        persons_stale=0,
        persons_conflict=0,
        crawlers_total=3,
        crawlers_healthy=3,
        crawlers_degraded=[],
        tags_assigned_today=0,
        merges_today=0,
        persons_ingested_today=0,
    )
    assert sa.meta == {}


def test_system_audit_degraded_list():
    from shared.models.audit import SystemAudit

    degraded = [
        {"name": "crawler_a", "success_rate": 0.0},
        {"name": "crawler_b", "success_rate": 0.1},
    ]
    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=50,
        persons_low_coverage=5,
        persons_stale=2,
        persons_conflict=1,
        crawlers_total=10,
        crawlers_healthy=8,
        crawlers_degraded=degraded,
        tags_assigned_today=100,
        merges_today=5,
        persons_ingested_today=10,
    )
    assert len(sa.crawlers_degraded) == 2
    assert sa.crawlers_degraded[1]["name"] == "crawler_b"
