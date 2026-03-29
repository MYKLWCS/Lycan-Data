"""Tests for modules/enrichers/deduplication.py — 15 tests."""

import pytest

from modules.enrichers.deduplication import (
    MERGE_THRESHOLD,
    MergeCandidate,
    _normalize_email_for_dedup as normalize_email,
    _normalize_phone_for_dedup as normalize_phone,
    _normalize_username_for_dedup as normalize_username,
    find_duplicate_identifiers,
    find_duplicate_persons,
    merge_persons,
    name_similarity,
    normalize_name,
)

# ─── normalize_name ───────────────────────────────────────────────────────────


def test_normalize_name_strips_honorifics():
    """Honorifics like Mr, Mrs, Dr are removed from the token list."""
    result = normalize_name("Mr John Smith")
    assert "mr" not in result.split()
    assert "john" in result.split()
    assert "smith" in result.split()


def test_normalize_name_dr_john_smith_jr():
    """'Dr. John Smith Jr' → tokens are 'john' and 'smith', sorted."""
    result = normalize_name("Dr. John Smith Jr")
    assert result == "john smith"


# ─── name_similarity ──────────────────────────────────────────────────────────


def test_name_similarity_identical():
    assert name_similarity("John Smith", "John Smith") == 1.0


def test_name_similarity_reversed_tokens():
    """'John Smith' and 'Smith John' normalize to identical sorted tokens → 1.0."""
    assert name_similarity("John Smith", "Smith John") == 1.0


def test_name_similarity_no_overlap():
    """Completely different names → 0.0."""
    assert name_similarity("John Smith", "Jane Doe") == 0.0


def test_name_similarity_partial_overlap():
    """'John Smith' vs 'John Doe' share one token → between 0 and 1."""
    score = name_similarity("John Smith", "John Doe")
    assert 0.0 < score < 1.0


# ─── Identifier normalizers ───────────────────────────────────────────────────


def test_normalize_phone_10_digit():
    """10-digit US number gets +1 prefix."""
    result = normalize_phone("2025551234")
    assert result == "+12025551234"


def test_normalize_email_uppercase():
    """Email is lowercased and stripped."""
    result = normalize_email("  ALICE@Example.COM  ")
    assert result == "alice@example.com"


def test_normalize_username_at_prefix():
    """Leading @ is stripped and username is lowercased."""
    result = normalize_username("@JohnDoe")
    assert result == "johndoe"


# ─── find_duplicate_identifiers ───────────────────────────────────────────────


def test_find_duplicate_identifiers_same_phone():
    """Two phone identifiers that normalize identically → one MergeCandidate."""
    identifiers = [
        {"id": "1", "type": "phone", "value": "2025551234"},
        {"id": "2", "type": "phone", "value": "+1 (202) 555-1234"},
    ]
    candidates = find_duplicate_identifiers(identifiers)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.id_a == "1"
    assert c.id_b == "2"
    assert c.similarity_score == 1.0


def test_find_duplicate_identifiers_different_types_not_merged():
    """Same raw value but different types (phone vs email) → no merge candidate."""
    identifiers = [
        {"id": "1", "type": "phone", "value": "test"},
        {"id": "2", "type": "email", "value": "test"},
    ]
    candidates = find_duplicate_identifiers(identifiers)
    assert candidates == []


# ─── find_duplicate_persons ───────────────────────────────────────────────────


def test_find_duplicate_persons_same_name_and_dob():
    """Same full name + same DOB + shared identifier → similarity >= MERGE_THRESHOLD.

    Name (1.0×0.40) + DOB (0.30) + shared ident (0.15) = 0.85 >= 0.75.
    """
    persons = [
        {
            "id": "p1",
            "full_name": "John Smith",
            "dob": "1985-06-15",
            "identifiers": ["john@example.com"],
        },
        {
            "id": "p2",
            "full_name": "John Smith",
            "dob": "1985-06-15",
            "identifiers": ["john@example.com"],
        },
    ]
    candidates = find_duplicate_persons(persons)
    assert len(candidates) == 1
    assert candidates[0].similarity_score >= MERGE_THRESHOLD


def test_find_duplicate_persons_different_name_no_shared_idents():
    """Different names, no DOB, no shared identifiers → below threshold → no candidates."""
    persons = [
        {"id": "p1", "full_name": "Alice Wonder", "dob": None, "identifiers": []},
        {"id": "p2", "full_name": "Bob Builder", "dob": None, "identifiers": []},
    ]
    candidates = find_duplicate_persons(persons)
    assert candidates == []


def test_find_duplicate_persons_shared_identifier_adds_to_score():
    """Persons with a shared identifier score higher than name + DOB alone.

    Name (1.0×0.40) + DOB (0.30) = 0.70 without shared ident.
    Name (1.0×0.40) + DOB (0.30) + shared ident (0.15) = 0.85 with shared ident.
    We compare raw _person_similarity outputs directly to verify the additive effect.
    """
    from modules.enrichers.deduplication import _person_similarity

    a_no = {"id": "p1", "full_name": "John Smith", "dob": "1990-01-01", "identifiers": []}
    b_no = {"id": "p2", "full_name": "John Smith", "dob": "1990-01-01", "identifiers": []}

    a_yes = {
        "id": "p1",
        "full_name": "John Smith",
        "dob": "1990-01-01",
        "identifiers": ["alice@example.com"],
    }
    b_yes = {
        "id": "p2",
        "full_name": "John Smith",
        "dob": "1990-01-01",
        "identifiers": ["alice@example.com"],
    }

    score_no, _ = _person_similarity(a_no, b_no)
    score_yes, reasons_yes = _person_similarity(a_yes, b_yes)

    assert score_yes > score_no
    assert any("shared" in r for r in reasons_yes)


# ─── merge_persons ────────────────────────────────────────────────────────────


def test_merge_persons_structure():
    """merge_persons returns the correct canonical/duplicate merge plan."""
    plan = merge_persons("canonical-001", "duplicate-002")

    assert plan["canonical_id"] == "canonical-001"
    assert plan["duplicate_id"] == "duplicate-002"
    assert plan["action"] == "merge"
    assert plan["delete_duplicate"] is True
    assert "identifiers" in plan["reassign_tables"]
    assert "alerts" in plan["reassign_tables"]
    assert "merged_at" in plan
