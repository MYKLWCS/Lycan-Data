"""Tests for modules/enrichers/genealogy_enricher.py"""
from __future__ import annotations
import pytest

class TestComputeConfidence:
    def test_zero_sources_returns_zero(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([]) == 0.0

    def test_one_source_returns_040(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert abs(compute_confidence([{}]) - 0.40) < 1e-9

    def test_two_sources_returns_072(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert abs(compute_confidence([{},{}]) - 0.72) < 1e-9

    def test_three_sources_returns_092(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert abs(compute_confidence([{},{},{}]) - 0.92) < 1e-9

    def test_four_sources_still_092(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert abs(compute_confidence([{},{},{},{}]) - 0.92) < 1e-9

    def test_government_bonus_one_source(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert abs(compute_confidence([{}], is_government=True) - 0.55) < 1e-9

    def test_government_bonus_three_sources_capped(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{},{},{}], is_government=True) == 1.0

    def test_no_government_flag_is_default_false(self):
        from modules.enrichers.genealogy_enricher import compute_confidence
        assert compute_confidence([{}]) == compute_confidence([{}], is_government=False)

class TestFamilyRelTypes:
    def test_parent_of_in_family_rel_types(self):
        from modules.enrichers.genealogy_enricher import FAMILY_REL_TYPES
        assert "parent_of" in FAMILY_REL_TYPES

    def test_spouse_of_in_family_rel_types(self):
        from modules.enrichers.genealogy_enricher import FAMILY_REL_TYPES
        assert "spouse_of" in FAMILY_REL_TYPES

    def test_sibling_of_in_family_rel_types(self):
        from modules.enrichers.genealogy_enricher import FAMILY_REL_TYPES
        assert "sibling_of" in FAMILY_REL_TYPES

    def test_all_eleven_rel_types_present(self):
        from modules.enrichers.genealogy_enricher import FAMILY_REL_TYPES
        expected = {"parent_of","child_of","sibling_of","spouse_of","grandparent_of",
                    "grandchild_of","aunt_uncle_of","niece_nephew_of","half_sibling_of",
                    "step_parent_of","step_child_of"}
        assert expected == FAMILY_REL_TYPES

    def test_ancestor_types_subset_of_family_types(self):
        from modules.enrichers.genealogy_enricher import ANCESTOR_TYPES, FAMILY_REL_TYPES
        assert ANCESTOR_TYPES.issubset(FAMILY_REL_TYPES)

class TestParseRelatives:
    def setup_method(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        self.enricher = GenealogyEnricher()

    def test_valid_parent_passes_through(self):
        records = [{"_platform": "census_records", "source_url": "http://x.com",
                    "parents": [{"name": "Jane Doe", "birth_year": 1950}]}]
        result = self.enricher._parse_relatives(records)
        assert len(result) == 1
        assert result[0]["rel_type"] == "parent_of"

    def test_valid_spouse_passes_through(self):
        records = [{"_platform": "census_records", "source_url": "", "spouses": [{"name": "Jane Doe"}]}]
        result = self.enricher._parse_relatives(records)
        assert len(result) == 1
        assert result[0]["rel_type"] == "spouse_of"

    def test_empty_name_excluded(self):
        records = [{"_platform": "x", "source_url": "", "parents": [{"name": ""}]}]
        assert self.enricher._parse_relatives(records) == []

    def test_empty_input_returns_empty(self):
        assert self.enricher._parse_relatives([]) == []

    def test_new_format_parent_of(self):
        records = [{"_platform": "ancestry_hints", "source_url": "http://a.com",
                    "parent_ofs_list": [{"name": "Jane Doe", "birth_year": 1950,
                        "rel_type": "parent_of", "platform": "ancestry_hints",
                        "sources": [{"platform": "ancestry_hints", "url": "http://a.com"}]}]}]
        result = self.enricher._parse_relatives(records)
        assert len(result) == 1
        assert result[0]["rel_type"] == "parent_of"
        assert result[0]["name"] == "Jane Doe"

    def test_multiple_valid_relatives(self):
        records = [{"_platform": "x", "source_url": "",
                    "parents": [{"name": "Alice"}], "spouses": [{"name": "Bob"}]}]
        assert len(self.enricher._parse_relatives(records)) == 2

class TestFindOrCreatePerson:
    def test_government_platforms_set(self):
        from modules.enrichers.genealogy_enricher import GOVERNMENT_PLATFORMS
        assert "census_records" in GOVERNMENT_PLATFORMS
        assert "vitals_records" in GOVERNMENT_PLATFORMS
        assert "ancestry_hints" not in GOVERNMENT_PLATFORMS

    def test_genealogy_platforms_list(self):
        from modules.enrichers.genealogy_enricher import GENEALOGY_PLATFORMS
        assert "ancestry_hints" in GENEALOGY_PLATFORMS
        assert "geni_public" in GENEALOGY_PLATFORMS

    def test_first_last_split_single_word(self):
        parts = "Madonna".split(None, 1)
        assert parts[0] == "Madonna" and len(parts) == 1

    def test_first_last_split_two_words(self):
        parts = "John Smith".split(None, 1)
        assert parts[0] == "John" and parts[1] == "Smith"

class TestBuildTree:
    def test_enricher_instantiates(self):
        from modules.enrichers.genealogy_enricher import GenealogyEnricher
        e = GenealogyEnricher()
        assert hasattr(e, "build_tree")
        assert hasattr(e, "_parse_relatives")
        assert hasattr(e, "_run_genealogy_crawlers")

    def test_sleep_interval_is_300(self):
        from modules.enrichers.genealogy_enricher import SLEEP_INTERVAL_SECONDS
        assert SLEEP_INTERVAL_SECONDS == 300
