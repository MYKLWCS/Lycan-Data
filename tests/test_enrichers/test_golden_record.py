"""Tests for modules/enrichers/golden_record.py — golden record construction."""

import pytest

from modules.enrichers.golden_record import (
    GoldenRecord,
    GoldenRecordBuilder,
    source_rank,
)


# ── Source ranking ───────────────────────────────────────────────────────────


class TestSourceRank:
    def test_government_highest(self):
        assert source_rank("government") > source_rank("social_media")

    def test_credit_bureau_above_commercial(self):
        assert source_rank("credit_bureau") > source_rank("commercial_database")

    def test_unknown_source(self):
        assert source_rank("totally_unknown") == source_rank("unknown")

    def test_none_source(self):
        assert source_rank(None) == source_rank("unknown")


# ── GoldenRecordBuilder ─────────────────────────────────────────────────────


class TestGoldenRecordBuilder:
    def setup_method(self):
        self.builder = GoldenRecordBuilder()

    def test_empty_records(self):
        golden = self.builder.build([], canonical_id="test")
        assert golden.canonical_id == "test"
        assert golden.merged_ids == []
        assert golden.fields == {}

    def test_single_record_passthrough(self):
        records = [
            {
                "id": "1",
                "full_name": "John Smith",
                "gender": "male",
                "_source": "credit_bureau",
            }
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["full_name"] == "John Smith"
        assert golden.fields["gender"] == "male"

    def test_single_value_highest_priority_wins(self):
        """Government source should win over web scrape for name."""
        records = [
            {"id": "1", "full_name": "John M. Smith", "_source": "public_web_scrape"},
            {"id": "2", "full_name": "John Michael Smith", "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["full_name"] == "John Michael Smith"

    def test_conflict_detected(self):
        records = [
            {"id": "1", "full_name": "John Smith", "_source": "credit_bureau"},
            {"id": "2", "full_name": "Jon Smith", "_source": "social_media"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.provenance["full_name"].conflict is True

    def test_no_conflict_when_values_agree(self):
        records = [
            {"id": "1", "full_name": "John Smith", "_source": "credit_bureau"},
            {"id": "2", "full_name": "John Smith", "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.provenance["full_name"].conflict is False

    def test_multi_value_keeps_all_unique(self):
        records = [
            {"id": "1", "emails": ["john@gmail.com"], "_source": "credit_bureau"},
            {"id": "2", "emails": ["john@yahoo.com"], "_source": "social_media"},
            {"id": "3", "emails": ["john@gmail.com"], "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        emails = golden.fields["emails"]
        assert "john@gmail.com" in emails
        assert "john@yahoo.com" in emails
        assert len(emails) == 2  # no duplicates

    def test_max_value_fields(self):
        records = [
            {"id": "1", "property_count": 3, "_source": "credit_bureau"},
            {"id": "2", "property_count": 5, "_source": "property_records"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["property_count"] == 5

    def test_any_true_fields(self):
        records = [
            {"id": "1", "pep_status": False, "_source": "credit_bureau"},
            {"id": "2", "pep_status": True, "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["pep_status"] is True

    def test_any_true_all_false(self):
        records = [
            {"id": "1", "is_sanctioned": False, "_source": "credit_bureau"},
            {"id": "2", "is_sanctioned": False, "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["is_sanctioned"] is False

    def test_provenance_tracks_winning_source(self):
        records = [
            {"id": "1", "full_name": "John Smith", "_source": "social_media"},
            {"id": "2", "full_name": "John M. Smith", "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        prov = golden.provenance["full_name"]
        assert prov.winning_source == "government"
        assert "social_media" in prov.all_sources

    def test_provenance_tracks_all_values(self):
        records = [
            {"id": "1", "full_name": "John Smith", "_source": "credit_bureau"},
            {"id": "2", "full_name": "Jon Smith", "_source": "social_media"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        prov = golden.provenance["full_name"]
        assert "John Smith" in prov.all_values
        assert "Jon Smith" in prov.all_values

    def test_to_dict(self):
        records = [
            {"id": "1", "full_name": "John Smith", "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        d = golden.to_dict()
        assert d["canonical_id"] == "1"
        assert "provenance" in d
        assert "full_name" in d["provenance"]

    def test_internal_fields_excluded(self):
        """Fields starting with _ should not appear in merged output."""
        records = [
            {
                "id": "1",
                "full_name": "John Smith",
                "_source": "government",
                "_timestamp": "2025-01-01",
                "_record_id": "r1",
            },
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert "_source" not in golden.fields
        assert "_timestamp" not in golden.fields

    def test_null_values_skipped(self):
        records = [
            {"id": "1", "full_name": None, "gender": "male", "_source": "credit_bureau"},
            {"id": "2", "full_name": "John Smith", "gender": None, "_source": "government"},
        ]
        golden = self.builder.build(records, canonical_id="1")
        assert golden.fields["full_name"] == "John Smith"
        assert golden.fields["gender"] == "male"
