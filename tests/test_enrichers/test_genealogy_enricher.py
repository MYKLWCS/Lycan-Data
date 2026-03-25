"""
Tests for GenealogyEnricher — compute_confidence and _parse_relatives.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.genealogy_enricher import GenealogyEnricher, compute_confidence

# ── compute_confidence ─────────────────────────────────────────────────────────


def test_confidence_one_source():
    assert compute_confidence(1) == 0.40


def test_confidence_two_sources():
    assert compute_confidence(2) == 0.72


def test_confidence_three_sources():
    assert compute_confidence(3) == 0.92


def test_confidence_one_source_gov():
    assert compute_confidence(1, has_gov_record=True) == pytest.approx(0.55)


def test_confidence_three_sources_gov_capped():
    assert compute_confidence(3, has_gov_record=True) == 1.0


def test_confidence_zero_sources():
    assert compute_confidence(0) == 0.0


# ── _parse_relatives ───────────────────────────────────────────────────────────


def test_parse_relatives_parents():
    enricher = GenealogyEnricher()
    results = [
        {
            "parents": [{"name": "John Smith", "birth_year": 1940}],
            "children": [],
            "spouses": [],
            "siblings": [],
            "record_type": "census",
        }
    ]
    relatives = enricher._parse_relatives(results)
    assert len(relatives) == 1
    assert relatives[0]["rel_type"] == "parent_of"
    assert relatives[0]["name"] == "John Smith"
    assert relatives[0]["record_type"] == "census"


def test_parse_relatives_children():
    enricher = GenealogyEnricher()
    results = [
        {
            "parents": [],
            "children": [{"name": "Jane Smith", "birth_year": 1970}],
            "spouses": [],
            "siblings": [],
            "record_type": "tree",
        }
    ]
    relatives = enricher._parse_relatives(results)
    assert len(relatives) == 1
    assert relatives[0]["rel_type"] == "child_of"
    assert relatives[0]["name"] == "Jane Smith"


def test_parse_relatives_spouses():
    enricher = GenealogyEnricher()
    results = [
        {
            "parents": [],
            "children": [],
            "spouses": [{"name": "Mary Smith", "marriage_date": "1965"}],
            "siblings": [],
            "record_type": "tree",
        }
    ]
    relatives = enricher._parse_relatives(results)
    assert len(relatives) == 1
    assert relatives[0]["rel_type"] == "spouse_of"
    assert relatives[0]["name"] == "Mary Smith"


def test_parse_relatives_siblings():
    enricher = GenealogyEnricher()
    results = [
        {
            "parents": [],
            "children": [],
            "spouses": [],
            "siblings": [{"name": "Bob Smith", "birth_year": 1945}],
            "record_type": "tree",
        }
    ]
    relatives = enricher._parse_relatives(results)
    assert len(relatives) == 1
    assert relatives[0]["rel_type"] == "sibling_of"
    assert relatives[0]["name"] == "Bob Smith"


def test_parse_relatives_mixed():
    enricher = GenealogyEnricher()
    results = [
        {
            "parents": [{"name": "Dad", "birth_year": 1930}],
            "children": [{"name": "Kid", "birth_year": 1975}],
            "spouses": [{"name": "Wife", "marriage_date": None}],
            "siblings": [{"name": "Bro", "birth_year": 1948}],
            "record_type": "birth_cert",
        }
    ]
    relatives = enricher._parse_relatives(results)
    assert len(relatives) == 4
    rel_types = {r["rel_type"] for r in relatives}
    assert rel_types == {"parent_of", "child_of", "spouse_of", "sibling_of"}


def test_parse_relatives_empty():
    enricher = GenealogyEnricher()
    assert enricher._parse_relatives([]) == []


def test_parse_relatives_empty_lists():
    enricher = GenealogyEnricher()
    results = [
        {"parents": [], "children": [], "spouses": [], "siblings": [], "record_type": "tree"}
    ]
    assert enricher._parse_relatives(results) == []
