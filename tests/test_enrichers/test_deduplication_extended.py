"""Extended tests for modules/enrichers/deduplication.py — ExactMatchDeduplicator,
soundex, jaro_winkler, levenshtein, FuzzyDeduplicator, _looks_like_phone."""

import pytest

from modules.enrichers.deduplication import (
    ExactMatchDeduplicator,
    FuzzyDeduplicator,
    MergeCandidate,
    _looks_like_phone,
    jaro_winkler_similarity,
    levenshtein_similarity,
    soundex,
)


# ─── ExactMatchDeduplicator — normalize_string ────────────────────────────────


def test_normalize_string_lowercases():
    d = ExactMatchDeduplicator()
    assert d.normalize_string("JOHN SMITH") == "john smith"


def test_normalize_string_strips_punctuation():
    d = ExactMatchDeduplicator()
    assert d.normalize_string("Smith, Jr.") == "smith jr"


# ─── extract_ssn_last4 ────────────────────────────────────────────────────────


def test_extract_ssn_last4_formatted():
    d = ExactMatchDeduplicator()
    assert d.extract_ssn_last4("123-45-6789") == "6789"


def test_extract_ssn_last4_short_ssn():
    d = ExactMatchDeduplicator()
    assert d.extract_ssn_last4("123") == "123"


# ─── create_composite_keys ───────────────────────────────────────────────────


def test_composite_keys_full_record():
    d = ExactMatchDeduplicator()
    record = {
        "ssn": "123-45-6789",
        "dob": "1985-06-15",
        "full_name": "John Smith",
        "email": "john@example.com",
        "phone": "2025551234",
    }
    keys = d.create_composite_keys(record)
    key_strings = [k for k, _ in keys]
    assert any(k.startswith("ssn:") for k in key_strings)
    assert any(k.startswith("email:") for k in key_strings)
    assert any(k.startswith("phone:") for k in key_strings)
    assert any(k.startswith("namedob:") for k in key_strings)


def test_composite_keys_email_without_at_excluded():
    d = ExactMatchDeduplicator()
    record = {"email": "not-an-email"}
    keys = d.create_composite_keys(record)
    assert not any(k.startswith("email:") for k, _ in keys)


def test_composite_keys_phone_too_short_excluded():
    d = ExactMatchDeduplicator()
    record = {"phone": "123"}
    keys = d.create_composite_keys(record)
    assert not any(k.startswith("phone:") for k, _ in keys)


def test_composite_keys_ein_included():
    d = ExactMatchDeduplicator()
    record = {"ein": "12-3456789"}
    keys = d.create_composite_keys(record)
    assert any(k.startswith("ein:") for k, _ in keys)


def test_composite_keys_empty_record():
    d = ExactMatchDeduplicator()
    keys = d.create_composite_keys({})
    assert keys == []


# ─── hash_key ─────────────────────────────────────────────────────────────────


def test_hash_key_is_deterministic():
    d = ExactMatchDeduplicator()
    assert d.hash_key("test") == d.hash_key("test")


def test_hash_key_different_inputs_differ():
    d = ExactMatchDeduplicator()
    assert d.hash_key("alice") != d.hash_key("bob")


# ─── check_and_mark_duplicate — in-memory (no dragonfly) ─────────────────────


def test_check_and_mark_first_occurrence_not_dup():
    d = ExactMatchDeduplicator()
    record = {"email": "alice@example.com"}
    is_dup, key = d.check_and_mark_duplicate(record)
    assert is_dup is False
    assert key == ""


def test_check_and_mark_second_occurrence_is_dup():
    d = ExactMatchDeduplicator()
    record = {"email": "alice@example.com"}
    d.check_and_mark_duplicate(record)
    is_dup, key = d.check_and_mark_duplicate(record)
    assert is_dup is True
    assert "email" in key


def test_check_and_mark_different_records_not_dup():
    d = ExactMatchDeduplicator()
    d.check_and_mark_duplicate({"email": "alice@example.com"})
    is_dup, _ = d.check_and_mark_duplicate({"email": "bob@example.com"})
    assert is_dup is False


# ─── process_batch ────────────────────────────────────────────────────────────


def test_process_batch_unique_records():
    d = ExactMatchDeduplicator()
    records = [
        {"email": "a@example.com"},
        {"email": "b@example.com"},
        {"email": "c@example.com"},
    ]
    unique, dups = d.process_batch(records)
    assert len(unique) == 3
    assert len(dups) == 0


def test_process_batch_detects_duplicate():
    d = ExactMatchDeduplicator()
    records = [
        {"email": "dup@example.com"},
        {"email": "dup@example.com"},
    ]
    unique, dups = d.process_batch(records)
    assert len(unique) == 1
    assert len(dups) == 1
    assert dups[0]["pass"] == 1


def test_process_batch_structure_of_duplicate():
    d = ExactMatchDeduplicator()
    r1 = {"email": "same@example.com", "id": "1"}
    r2 = {"email": "same@example.com", "id": "2"}
    _, dups = d.process_batch([r1, r2])
    dup = dups[0]
    assert "record" in dup
    assert "matched_key" in dup
    assert "pass" in dup


# ─── soundex ──────────────────────────────────────────────────────────────────


def test_soundex_empty():
    assert soundex("") == "0000"


def test_soundex_non_alpha():
    assert soundex("123") == "0000"


def test_soundex_robert():
    assert soundex("Robert") == "R163"


def test_soundex_rupert():
    # Rupert → R163 (same as Robert)
    assert soundex("Rupert") == soundex("Robert")


def test_soundex_smith():
    result = soundex("Smith")
    assert result.startswith("S")
    assert len(result) == 4


def test_soundex_pads_to_four():
    result = soundex("A")
    assert len(result) == 4


# ─── jaro_winkler_similarity ──────────────────────────────────────────────────


def test_jaro_winkler_identical():
    assert jaro_winkler_similarity("hello", "hello") == 1.0


def test_jaro_winkler_empty_strings():
    assert jaro_winkler_similarity("", "") == 1.0
    assert jaro_winkler_similarity("abc", "") == 0.0
    assert jaro_winkler_similarity("", "abc") == 0.0


def test_jaro_winkler_completely_different():
    score = jaro_winkler_similarity("abc", "xyz")
    assert score == 0.0


def test_jaro_winkler_similar_names():
    score = jaro_winkler_similarity("MARTHA", "MARHTA")
    assert 0.9 <= score <= 1.0


def test_jaro_winkler_prefix_boost():
    # "johnsmith" vs "johndoe" — share "john" prefix so JW > Jaro
    score_jw = jaro_winkler_similarity("johnsmith", "johndoe")
    # Score should be moderately high due to shared prefix
    assert score_jw > 0.5


def test_jaro_winkler_returns_float_in_range():
    score = jaro_winkler_similarity("Alice", "Alicia")
    assert 0.0 <= score <= 1.0


# ─── levenshtein_similarity ───────────────────────────────────────────────────


def test_levenshtein_identical():
    assert levenshtein_similarity("hello", "hello") == 1.0


def test_levenshtein_both_empty():
    assert levenshtein_similarity("", "") == 1.0


def test_levenshtein_one_empty():
    assert levenshtein_similarity("abc", "") == 0.0
    assert levenshtein_similarity("", "abc") == 0.0


def test_levenshtein_one_edit():
    # "cat" vs "bat" → edit distance 1, max len 3 → similarity 2/3
    score = levenshtein_similarity("cat", "bat")
    assert abs(score - (2 / 3)) < 0.01


def test_levenshtein_completely_different():
    score = levenshtein_similarity("abc", "xyz")
    assert score < 0.5


def test_levenshtein_in_range():
    score = levenshtein_similarity("algorithm", "altruistic")
    assert 0.0 <= score <= 1.0


# ─── _looks_like_phone ────────────────────────────────────────────────────────


def test_looks_like_phone_10_digits():
    assert _looks_like_phone("2025551234") is True


def test_looks_like_phone_formatted():
    assert _looks_like_phone("+1 (202) 555-1234") is True


def test_looks_like_phone_too_short():
    assert _looks_like_phone("12345") is False


def test_looks_like_phone_too_long():
    assert _looks_like_phone("1234567890123456") is False


def test_looks_like_phone_email_not_phone():
    assert _looks_like_phone("alice@example.com") is False


# ─── FuzzyDeduplicator ────────────────────────────────────────────────────────


def _make_person(id: str, full_name: str, dob: str = "", phones: list | None = None, emails: list | None = None, identifiers: list | None = None) -> dict:
    return {
        "id": id,
        "full_name": full_name,
        "dob": dob,
        "phones": phones or [],
        "emails": emails or [],
        "identifiers": identifiers or [],
        "addresses": [],
    }


def test_fuzzy_dedup_identical_persons():
    fd = FuzzyDeduplicator()
    persons = [
        _make_person("1", "John Smith", "1985-06-15", phones=["2025551234"]),
        _make_person("2", "John Smith", "1985-06-15", phones=["2025551234"]),
    ]
    candidates = fd.find_candidates(persons)
    assert len(candidates) >= 1
    assert candidates[0].similarity_score >= fd.MERGE_THRESHOLD


def test_fuzzy_dedup_different_persons_no_match():
    fd = FuzzyDeduplicator()
    persons = [
        _make_person("1", "Alice Wonder", "1990-01-01"),
        _make_person("2", "Bob Builder", "1965-05-10"),
    ]
    candidates = fd.find_candidates(persons)
    assert candidates == []


def test_fuzzy_dedup_shared_email_high_score():
    fd = FuzzyDeduplicator()
    persons = [
        _make_person("1", "Jane Doe", emails=["jane@example.com"]),
        _make_person("2", "Janet Doe", emails=["jane@example.com"]),
    ]
    candidates = fd.find_candidates(persons)
    assert len(candidates) >= 1
    assert candidates[0].similarity_score >= 0.90


def test_fuzzy_dedup_custom_merge_threshold():
    fd = FuzzyDeduplicator(merge_threshold=0.99)
    persons = [
        _make_person("1", "John Smith", "1985-06-15"),
        _make_person("2", "John Smith", "1985-06-15"),
    ]
    # At 0.99 threshold, name+dob alone (score ~0.70) should not trigger
    candidates = fd.find_candidates(persons)
    # Only shared phone/email early-exit reaches 0.95, so no candidates
    assert all(c.similarity_score >= 0.99 for c in candidates)


def test_fuzzy_dedup_results_sorted_descending():
    fd = FuzzyDeduplicator()
    persons = [
        _make_person("1", "John Smith", "1985-06-15", phones=["2025551234"]),
        _make_person("2", "John Smith", "1985-06-15", phones=["2025551234"]),
        _make_person("3", "Jon Smith", "1985-06-15"),
        _make_person("4", "Jonathan Smith", "1985-06-15"),
    ]
    candidates = fd.find_candidates(persons)
    for i in range(len(candidates) - 1):
        assert candidates[i].similarity_score >= candidates[i + 1].similarity_score


def test_fuzzy_dedup_returns_merge_candidate_instances():
    fd = FuzzyDeduplicator()
    persons = [
        _make_person("1", "Alice Smith", emails=["alice@test.com"]),
        _make_person("2", "Alice Smith", emails=["alice@test.com"]),
    ]
    candidates = fd.find_candidates(persons)
    for c in candidates:
        assert isinstance(c, MergeCandidate)
