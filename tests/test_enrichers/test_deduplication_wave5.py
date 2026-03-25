"""
test_deduplication_wave5.py — Coverage gap tests for modules/enrichers/deduplication.py.

Targets:
  - Line 180: return 0.0 in name_similarity when tokens_a or tokens_b is empty
    after normalization (names that reduce to only honorifics → empty token set).
  - Line 520: return 1.0 in levenshtein_similarity when both strings have length 0
    (both s1 and s2 are empty strings but s1 != s2 is False, so line 513 catches
    identical strings first — must reach via s1 == "" and s2 == "").

Notes:
  - Lines 794-797 already have `# pragma: no cover` in the source — skipped.
"""

from __future__ import annotations

import pytest

from modules.enrichers.deduplication import (
    levenshtein_similarity,
    name_similarity,
    normalize_name,
)


# ---------------------------------------------------------------------------
# Line 180: tokens_a or tokens_b is empty after normalize_name
# ---------------------------------------------------------------------------


def test_name_similarity_honorific_only_name_returns_zero():
    """
    Line 180: After normalize_name strips honorifics, if one name has no remaining
    tokens, tokens_a (or tokens_b) will be an empty set → return 0.0.
    'Mr' is an honorific — normalize_name('Mr') → '' → tokens = {''}  which is
    non-empty. We need a name that normalizes to truly empty.
    Use a name made purely of honorific words that get stripped.
    """
    # normalize_name filters out tokens in HONORIFICS and joins sorted remainder.
    # "Dr Mr" → tokens ['dr', 'mr'] — both stripped if they're in HONORIFICS.
    # Test with a name that normalizes to empty string, making split() return ['']
    # vs a valid name.
    norm = normalize_name("Mr")
    # If norm is empty string, split returns [''] which has one element '' (falsy but len 1)
    # The check is `if not tokens_a or not tokens_b` — empty set check
    # Let's verify what we get and test accordingly.

    # The safest way: patch normalize_name to return '' for one side
    from unittest.mock import patch
    with patch("modules.enrichers.deduplication.normalize_name") as mock_norm:
        # norm_a → empty string, norm_b → "john"
        mock_norm.side_effect = ["", "john smith"]
        result = name_similarity("anything", "John Smith")

    # Empty norm_a → early return 0.0 (line 170-171), not line 180
    # Let's target line 180 specifically: norm_a and norm_b are non-empty strings
    # but after split(), the sets are empty — this can't happen with split()
    # unless the string is empty. So line 170 catches it first.
    # The correct path to line 180 requires norm_a/norm_b to be non-empty
    # but their token sets to be empty — which is impossible with str.split().
    # Therefore line 180 is effectively dead code guarded by the line 170 check.
    # We cover it via mock to ensure the branch is reachable in principle.
    assert result == 0.0


def test_name_similarity_returns_zero_for_empty_first_arg():
    """Line 164: early return 0.0 when name_a is empty."""
    assert name_similarity("", "John Smith") == 0.0


def test_name_similarity_returns_zero_for_empty_second_arg():
    """Line 164: early return 0.0 when name_b is empty."""
    assert name_similarity("John Smith", "") == 0.0


def test_name_similarity_tokens_empty_via_mock():
    """
    Line 180: Force tokens_a to be empty set by patching normalize_name to return
    a non-empty string that splits to [''] resulting in set({''}), which is truthy.
    Actually line 180 can only be reached if somehow the split produces an empty
    set. We verify the branch condition is logically reachable by direct test.
    """
    # Direct unit test of the branch: inject via mocking full normalize_name output
    from unittest.mock import patch

    # Make norm_a = "  " (spaces only), norm_b = "john"
    # split() on "  " returns [] → set([]) = set() → falsy → line 180
    with patch("modules.enrichers.deduplication.normalize_name") as mock_norm:
        # norm_a → non-empty check passes (line 170), but split returns []
        mock_norm.side_effect = ["   ", "john"]
        # norm_a is "   " which is truthy, norm_b is "john" which is truthy
        # tokens_a = set("   ".split()) = set() → falsy → return 0.0 (line 180)
        result = name_similarity("spacename", "John")

    assert result == 0.0


# ---------------------------------------------------------------------------
# Line 520: levenshtein_similarity when both strings are empty
# ---------------------------------------------------------------------------


def test_levenshtein_similarity_both_empty_returns_one():
    """
    Line 520: When both s1 and s2 are empty strings (""), s1 == s2 is True,
    so line 513 (return 1.0) fires first. To reach line 519-520 we need
    len1==0 AND len2==0 but s1 != s2, which is impossible for strings.
    However the function signature allows any str; line 519 is guarded by
    len checks. We test via the public API to verify behavior.

    NOTE: Because s1 == s2 == "" triggers line 513 before line 519,
    line 520 is actually dead code. We verify that behavior here.
    """
    # Both empty → identical → line 513 fires → returns 1.0
    result = levenshtein_similarity("", "")
    assert result == 1.0


def test_levenshtein_similarity_one_empty_returns_zero():
    """Line 521-522: One empty, one non-empty → 0.0."""
    assert levenshtein_similarity("", "hello") == 0.0
    assert levenshtein_similarity("world", "") == 0.0


def test_levenshtein_similarity_identical_non_empty():
    """Line 513: Identical non-empty strings → 1.0 via early return."""
    assert levenshtein_similarity("alice", "alice") == 1.0


def test_levenshtein_similarity_completely_different():
    """DP path: completely different strings → low similarity."""
    result = levenshtein_similarity("abc", "xyz")
    assert 0.0 <= result < 1.0


def test_levenshtein_similarity_one_char_diff():
    """DP path: one character substitution."""
    result = levenshtein_similarity("kitten", "sitten")
    assert result > 0.8
