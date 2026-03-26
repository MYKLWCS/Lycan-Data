"""Tests for builder and relationship_detail model instantiation."""

import uuid

from shared.models.builder_job import BuilderJob, BuilderJobPerson
from shared.models.relationship_detail import RelationshipDetail


def test_builder_job_defaults():
    job = BuilderJob()
    assert job.status == "pending"
    assert job.discovered_count == 0
    assert job.built_count == 0
    assert job.filtered_count == 0
    assert job.expanded_count == 0
    assert job.relationships_mapped == 0
    assert job.max_results == 100
    assert job.criteria == {}


def test_builder_job_custom():
    job = BuilderJob(
        criteria={"location": "Miami"},
        max_results=500,
        status="discovering",
    )
    assert job.criteria == {"location": "Miami"}
    assert job.max_results == 500
    assert job.status == "discovering"


def test_builder_job_person_defaults():
    link = BuilderJobPerson(
        job_id=uuid.uuid4(),
        person_id=uuid.uuid4(),
    )
    assert link.phase == "discovered"
    assert link.enrichment_score == 0.0
    assert link.match_score == 0.0


def test_relationship_detail_defaults():
    detail = RelationshipDetail(
        relationship_id=uuid.uuid4(),
        detailed_type="spouse",
    )
    assert detail.strength == 50
    assert detail.confidence == 0.5
    assert detail.freshness_score == 1.0
    assert detail.composite_score == 50.0
    assert detail.verification_level == "unverified"
    assert detail.source_count == 1
    assert detail.discovery_sources == []
    assert detail.conflict is False


def test_relationship_detail_custom():
    detail = RelationshipDetail(
        relationship_id=uuid.uuid4(),
        detailed_type="parent",
        strength=95,
        confidence=0.92,
        freshness_score=0.85,
        composite_score=91.2,
        discovered_via="voter_records",
        discovery_sources=["voter_records", "property_records"],
        source_count=2,
        verification_level="cross_referenced",
    )
    assert detail.detailed_type == "parent"
    assert detail.strength == 95
    assert detail.confidence == 0.92
    assert detail.source_count == 2
    assert detail.verification_level == "cross_referenced"
    assert len(detail.discovery_sources) == 2
