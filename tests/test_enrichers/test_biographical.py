"""
Tests for modules/enrichers/biographical.py — 15 tests covering DOB
extraction, marital status, children count, parent status and profile building.
"""
from __future__ import annotations
from datetime import date

import pytest

from modules.enrichers.biographical import (
    BiographicalProfile,
    build_biographical_profile,
    extract_children,
    extract_dob,
    extract_marital_status,
    extract_parent_status,
)


# ── extract_dob ───────────────────────────────────────────────────────────────

class TestExtractDob:
    def test_iso_date_format(self):
        """ISO 8601 date is parsed correctly."""
        dob, confidence, sources = extract_dob(["Born on 1990-03-15 in Texas"], ["src"])
        assert dob == date(1990, 3, 15)
        assert confidence > 0.0

    def test_month_name_format(self):
        """'March 15, 1990' long-form date is parsed."""
        dob, confidence, sources = extract_dob(["DOB March 15, 1990"], ["src"])
        assert dob == date(1990, 3, 15)
        assert confidence > 0.0

    def test_slash_date_format(self):
        """MM/DD/YYYY slash format is parsed."""
        dob, confidence, sources = extract_dob(["Date of birth: 03/15/1990"], ["src"])
        assert dob == date(1990, 3, 15)

    def test_two_digit_year_over_30(self):
        """Two-digit year >30 is treated as 1900s."""
        dob, confidence, sources = extract_dob(["DOB: 03/15/90"], ["src"])
        assert dob is not None
        assert dob.year == 1990

    def test_two_digit_year_under_30(self):
        """Two-digit year <=30 is treated as 2000s."""
        dob, confidence, sources = extract_dob(["DOB: 05/20/05"], ["src"])
        assert dob is not None
        assert dob.year == 2005

    def test_two_sources_agree_confidence(self):
        """Two sources with the same date yield confidence >= 0.80."""
        texts = ["born 1990-03-15", "DOB: 03/15/1990"]
        sources = ["src_a", "src_b"]
        dob, confidence, matched = extract_dob(texts, sources)
        assert dob == date(1990, 3, 15)
        assert confidence >= 0.80
        assert len(matched) == 2

    def test_no_date_returns_none(self):
        """Text with no date produces (None, 0.0, [])."""
        dob, confidence, sources = extract_dob(["Hello world, no date here!"])
        assert dob is None
        assert confidence == 0.0
        assert sources == []

    def test_three_sources_agree_confidence_capped(self):
        """Three agreeing sources cap confidence at 1.0."""
        texts = ["1990-03-15", "March 15, 1990", "03/15/1990"]
        dob, confidence, matched = extract_dob(texts)
        assert dob == date(1990, 3, 15)
        assert confidence == 1.0
        assert len(matched) == 3

    def test_conflicting_dates_picks_most_common(self):
        """When dates conflict, the most common date wins."""
        texts = [
            "born 1990-03-15",
            "DOB: 03/15/1990",
            "born 1985-07-22",
        ]
        dob, confidence, matched = extract_dob(texts)
        assert dob == date(1990, 3, 15)


# ── extract_marital_status ────────────────────────────────────────────────────

class TestExtractMaritalStatus:
    def test_married_keyword(self):
        status = extract_marital_status(["happily married for 10 years"])
        assert status == "married"

    def test_widowed_priority_over_married(self):
        """'widowed' takes priority even when 'married' also appears."""
        status = extract_marital_status(["was married, now widowed after late husband passed away"])
        assert status == "widowed"

    def test_divorced(self):
        status = extract_marital_status(["went through a difficult divorce last year"])
        assert status == "divorced"

    def test_no_signal_returns_none(self):
        status = extract_marital_status(["I enjoy hiking and coding"])
        assert status is None


# ── extract_children ──────────────────────────────────────────────────────────

class TestExtractChildren:
    def test_explicit_count_kids(self):
        """'3 kids' extracts count 3."""
        count = extract_children(["proud father of 3 kids"])
        assert count == 3

    def test_my_son_and_daughter(self):
        """'my son' + 'my daughter' counts 2 children."""
        count = extract_children(["my son Jake started school, my daughter Lily too"])
        assert count == 2

    def test_no_children_signal_returns_none(self):
        count = extract_children(["I love travelling alone"])
        assert count is None

    def test_children_keyword_unknown_count(self):
        """'my kids' without number returns None (stored as unknown via -1 sentinel)."""
        # extract_children returns -1 for unknown count → build_biographical_profile maps to None
        result = extract_children(["I love spending time with my kids"])
        assert result == -1


# ── extract_parent_status ─────────────────────────────────────────────────────

class TestExtractParentStatus:
    def test_father_deceased_signal(self):
        result = extract_parent_status(["miss my dad who passed away last year"])
        assert result["father_deceased"] is True
        assert result["mother_deceased"] is None

    def test_no_deceased_signal_all_none(self):
        result = extract_parent_status(["my parents are both healthy and active"])
        assert result["father_deceased"] is None
        assert result["mother_deceased"] is None

    def test_mother_deceased_signal(self):
        result = extract_parent_status(["rest in peace mom, we miss you every day"])
        assert result["mother_deceased"] is True


# ── build_biographical_profile ────────────────────────────────────────────────

class TestBuildBiographicalProfile:
    def test_returns_biographical_profile_instance(self):
        profile = build_biographical_profile(["born 1985-06-20"])
        assert isinstance(profile, BiographicalProfile)

    def test_profile_dob_populated(self):
        profile = build_biographical_profile(["DOB: 05/10/1988"])
        assert profile.dob == date(1988, 5, 10)
        assert profile.dob_confidence > 0.0

    def test_profile_marital_status_populated(self):
        profile = build_biographical_profile(["happily married with kids"])
        assert profile.marital_status == "married"

    def test_profile_siblings_from_people_search(self):
        """Relatives from people_search_data are stored as siblings."""
        profile = build_biographical_profile(
            ["some text"],
            people_search_data={"relatives": ["Alice Smith", "Bob Smith"]},
        )
        assert "Alice Smith" in profile.siblings
        assert "Bob Smith" in profile.siblings

    def test_children_count_from_explicit_statement(self):
        profile = build_biographical_profile(["father of 2 sons"])
        assert profile.children_count == 2
