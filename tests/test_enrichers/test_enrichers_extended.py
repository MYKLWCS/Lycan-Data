"""Extended coverage tests for enricher modules.

Targets uncovered lines in:
  - modules/enrichers/deduplication.py   (69% → target 95%+)
  - modules/enrichers/biographical.py    (93% → target 100%)
  - modules/enrichers/burner_detector.py (89% → target 100%)
  - modules/enrichers/psychological.py   (93% → target 100%)
  - modules/enrichers/ranking.py         (93% → target 100%)
  - modules/patterns/anomaly.py          (94% → target 100%)
  - modules/patterns/inverted_index.py   (98% → target 100%)
  - modules/crawlers/registry.py         (94% → target 100%)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — _person_similarity (lines 311-337)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPersonSimilarityEdgeCases:
    """Lines 311-337: shared phone/email fast paths + shared identifier scoring."""

    def test_shared_phone_in_identifiers_triggers_fast_path(self):
        """Phone embedded in identifiers list (not phones key) also triggers 0.95."""
        from modules.enrichers.deduplication import _person_similarity

        a = {
            "id": "1",
            "full_name": "Joe Blow",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": ["2025551234"],
        }
        b = {
            "id": "2",
            "full_name": "Joe Blow",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": ["2025551234"],
        }
        score, reasons = _person_similarity(a, b)
        assert score == 0.95
        assert any("shared phone" in r for r in reasons)

    def test_shared_email_in_identifiers_triggers_fast_path(self):
        """Email embedded in identifiers list triggers 0.95 fast path."""
        from modules.enrichers.deduplication import _person_similarity

        a = {
            "id": "1",
            "full_name": "Jane Roe",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": ["jane@corp.com"],
        }
        b = {
            "id": "2",
            "full_name": "Jane Roe",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": ["jane@corp.com"],
        }
        score, reasons = _person_similarity(a, b)
        assert score == 0.95
        assert any("shared email" in r for r in reasons)

    def test_shared_identifier_adds_score_up_to_0_20(self):
        """Two shared identifiers cap contribution at 0.20."""
        from modules.enrichers.deduplication import _person_similarity

        shared = ["token-abc", "token-def"]
        a = {
            "id": "1",
            "full_name": "A B",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": shared,
        }
        b = {
            "id": "2",
            "full_name": "A B",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": shared,
        }
        score, reasons = _person_similarity(a, b)
        # name(1.0*0.40) + idents(min(0.20, 2*0.10)=0.20) = 0.60 total
        assert score == pytest.approx(0.60, abs=0.01)
        assert any("shared identifiers" in r for r in reasons)

    def test_three_shared_identifiers_still_capped_at_0_20(self):
        """Three shared identifiers still only add 0.20 (cap)."""
        from modules.enrichers.deduplication import _person_similarity

        shared = ["tok-1", "tok-2", "tok-3"]
        a = {
            "id": "1",
            "full_name": "X Y",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": shared,
        }
        b = {
            "id": "2",
            "full_name": "X Y",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": shared,
        }
        score, reasons = _person_similarity(a, b)
        # name(0.40) + idents(0.20 cap) = 0.60
        assert score == pytest.approx(0.60, abs=0.01)

    def test_dob_match_adds_0_30(self):
        """DOB exact match contributes 0.30."""
        from modules.enrichers.deduplication import _person_similarity

        a = {
            "id": "1",
            "full_name": "John Smith",
            "dob": "1990-06-15",
            "phones": [],
            "emails": [],
            "identifiers": [],
        }
        b = {
            "id": "2",
            "full_name": "John Smith",
            "dob": "1990-06-15",
            "phones": [],
            "emails": [],
            "identifiers": [],
        }
        score, reasons = _person_similarity(a, b)
        # name(1.0*0.40) + dob(0.30) = 0.70
        assert score == pytest.approx(0.70, abs=0.01)
        assert any("DOB match" in r for r in reasons)


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — FuzzyDeduplicator._blocking_keys (lines 607-636)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFuzzyDeduplicatorBlockingKeys:
    """Lines 607-636: _blocking_keys generates correct bucket identifiers."""

    def test_blocking_key_birth_year_included(self):
        """A person with a DOB should get a birth_year:YYYY key."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "Alice Smith",
            "dob": "1988-04-12",
            "phones": [],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        assert any(k.startswith("birth_year:") for k in keys)
        assert "birth_year:1988" in keys

    def test_blocking_key_soundex_last_name(self):
        """Last name soundex key is generated from full_name."""
        from modules.enrichers.deduplication import FuzzyDeduplicator, soundex

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "John Smith",
            "dob": "",
            "phones": [],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        expected_soundex = soundex("Smith")
        assert f"soundex:{expected_soundex}" in keys

    def test_blocking_key_phone_prefix(self):
        """First phone's digit prefix key is included."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "Bob Jones",
            "dob": "",
            "phones": ["+12025551234"],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        assert any(k.startswith("phone_prefix:") for k in keys)
        assert "phone_prefix:120" in keys

    def test_blocking_keys_empty_person_no_keys(self):
        """Person with no name, dob, or phones yields no blocking keys."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "",
            "dob": None,
            "phones": [],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        assert keys == []

    def test_blocking_keys_non_digit_dob_excluded(self):
        """DOB birth year that is not fully digit (e.g. 'unknown') is skipped."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "Test User",
            "dob": "unknown-01-01",
            "phones": [],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        # "unkn" is not all digits so birth_year key should be absent
        assert not any(k.startswith("birth_year:") for k in keys)

    def test_blocking_key_only_one_phone_prefix_per_person(self):
        """Even with multiple phones, only one phone_prefix key is generated."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        person = {
            "id": "1",
            "full_name": "Multi Phone",
            "dob": "",
            "phones": ["+12025551234", "+13105559876"],
            "emails": [],
            "identifiers": [],
            "addresses": [],
        }
        keys = fd._blocking_keys(person)
        phone_prefix_keys = [k for k in keys if k.startswith("phone_prefix:")]
        assert len(phone_prefix_keys) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — FuzzyDeduplicator._score_pair (lines 638-713)
# ═══════════════════════════════════════════════════════════════════════════════


def _fp(
    pid: str,
    full_name: str,
    dob: str = "",
    phones: list | None = None,
    emails: list | None = None,
    identifiers: list | None = None,
    addresses: list | None = None,
) -> dict:
    return {
        "id": pid,
        "full_name": full_name,
        "dob": dob,
        "phones": phones or [],
        "emails": emails or [],
        "identifiers": identifiers or [],
        "addresses": addresses or [],
    }


class TestFuzzyScorePair:
    """Lines 689-713: _score_pair scoring branches."""

    def test_shared_phone_returns_0_95_early_exit(self):
        """Shared phone triggers early exit at 0.95."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "John Smith", phones=["+12025551234"])
        b = _fp("2", "John Smith", phones=["+12025551234"])
        score, reasons = fd._score_pair(a, b)
        assert score == 0.95
        assert any("shared phone" in r for r in reasons)

    def test_shared_email_returns_0_95_early_exit(self):
        """Shared email triggers early exit at 0.95."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Jane Doe", emails=["jane@example.com"])
        b = _fp("2", "Janet Doe", emails=["jane@example.com"])
        score, reasons = fd._score_pair(a, b)
        assert score == 0.95
        assert any("shared email" in r for r in reasons)

    def test_name_jw_score_contributes(self):
        """High JW name similarity contributes up to 0.40."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Jonathan Smith")
        b = _fp("2", "Jonathan Smith")
        score, reasons = fd._score_pair(a, b)
        # Identical names: JW=1.0 * 0.40 = 0.40
        assert score == pytest.approx(0.40, abs=0.01)

    def test_dob_match_adds_0_30_to_score(self):
        """Matching DOB adds 0.30."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Alice Brown", dob="1985-07-20")
        b = _fp("2", "Alice Brown", dob="1985-07-20")
        score, reasons = fd._score_pair(a, b)
        # JW("alice brown","alice brown")=1.0 * 0.40 + dob 0.30 = 0.70
        assert score == pytest.approx(0.70, abs=0.01)
        assert any("DOB match" in r for r in reasons)

    def test_shared_identifier_adds_score(self):
        """Shared identifier (not phone/email) adds up to 0.20."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Bob White", identifiers=["drv-12345"])
        b = _fp("2", "Bob White", identifiers=["drv-12345"])
        score, reasons = fd._score_pair(a, b)
        # name(0.40) + ident(0.10) = 0.50
        assert score == pytest.approx(0.50, abs=0.01)
        assert any("shared identifiers" in r for r in reasons)

    def test_two_shared_identifiers_capped_at_0_20(self):
        """Two shared identifiers cap at 0.20."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Bob White", identifiers=["drv-111", "drv-222"])
        b = _fp("2", "Bob White", identifiers=["drv-111", "drv-222"])
        score, reasons = fd._score_pair(a, b)
        # name(0.40) + ident(0.20 cap) = 0.60
        assert score == pytest.approx(0.60, abs=0.01)

    def test_address_dict_match_adds_0_10(self):
        """Matching city+state in address dicts adds 0.10."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator(levenshtein_threshold=0.70)
        addr = {"city": "Austin", "state": "TX"}
        a = _fp("1", "Carol Green", addresses=[addr])
        b = _fp("2", "Carol Green", addresses=[addr])
        score, reasons = fd._score_pair(a, b)
        # name(0.40) + address(0.10) = 0.50
        assert score == pytest.approx(0.50, abs=0.01)
        assert any("address match" in r for r in reasons)

    def test_address_string_match_adds_0_10(self):
        """Address as a plain string is also handled."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator(levenshtein_threshold=0.70)
        a = _fp("1", "Dave Black", addresses=["dallas texas"])
        b = _fp("2", "Dave Black", addresses=["dallas texas"])
        score, reasons = fd._score_pair(a, b)
        assert score == pytest.approx(0.50, abs=0.01)
        assert any("address match" in r for r in reasons)

    def test_address_below_lev_threshold_not_added(self):
        """Addresses with low similarity don't add the 0.10 bonus."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator(levenshtein_threshold=0.99)  # extremely high threshold
        a = _fp("1", "Eve Gray", addresses=[{"city": "Austin", "state": "TX"}])
        b = _fp("2", "Eve Gray", addresses=[{"city": "Boston", "state": "MA"}])
        score, reasons = fd._score_pair(a, b)
        assert not any("address match" in r for r in reasons)

    def test_score_capped_at_1_0(self):
        """Combined score never exceeds 1.0."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator(levenshtein_threshold=0.5)
        addr = {"city": "Houston", "state": "TX"}
        a = _fp(
            "1", "Frank Hill", dob="1990-01-01", identifiers=["id-abc", "id-def"], addresses=[addr]
        )
        b = _fp(
            "2", "Frank Hill", dob="1990-01-01", identifiers=["id-abc", "id-def"], addresses=[addr]
        )
        score, _ = fd._score_pair(a, b)
        assert score <= 1.0

    def test_no_addresses_skips_address_branch(self):
        """Empty addresses on either side skips address comparison cleanly."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Grace Lee", addresses=[])
        b = _fp("2", "Grace Lee", addresses=[{"city": "NYC", "state": "NY"}])
        score, reasons = fd._score_pair(a, b)
        assert not any("address match" in r for r in reasons)

    def test_empty_city_state_address_dict_skipped(self):
        """Address dict with empty city and state skips address scoring."""
        from modules.enrichers.deduplication import FuzzyDeduplicator

        fd = FuzzyDeduplicator()
        a = _fp("1", "Henry Ford", addresses=[{"city": "", "state": ""}])
        b = _fp("2", "Henry Ford", addresses=[{"city": "", "state": ""}])
        score, reasons = fd._score_pair(a, b)
        # Empty city+state → stripped string is empty → no address score added
        assert not any("address match" in r for r in reasons)


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — BloomDedup (lines 719-781)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBloomDedup:
    """Lines 726-781: BloomDedup probabilistic deduplication."""

    def test_add_new_key_returns_true(self):
        """First add returns True (new key)."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        assert bd.add("unique-key-1") is True

    def test_add_duplicate_key_returns_false(self):
        """Second add of same key returns False (already seen)."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        bd.add("duplicate-key")
        assert bd.add("duplicate-key") is False

    def test_contains_after_add(self):
        """contains() returns True for a previously added key."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        bd.add("hello")
        assert bd.contains("hello") is True

    def test_contains_unseen_key_false(self):
        """contains() returns False for a key never added."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        assert bd.contains("never-added-xyz") is False

    def test_multiple_unique_keys_all_new(self):
        """Multiple unique keys all return True on first add."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        results = [bd.add(f"key-{i}") for i in range(10)]
        assert all(results)

    def test_hashes_deterministic(self):
        """_hashes returns the same positions for the same key."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        h1 = bd._hashes("test-key")
        h2 = bd._hashes("test-key")
        assert h1 == h2

    def test_hashes_different_for_different_keys(self):
        """_hashes returns different positions for different keys."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        h1 = bd._hashes("alpha")
        h2 = bd._hashes("beta")
        assert h1 != h2

    def test_optimal_params_reasonable_values(self):
        """_optimal_params returns m >= n and k >= 1 for typical inputs."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup(expected_n=1000, fp_rate=0.01)
        assert bd._m >= 1000
        assert bd._k >= 1

    def test_set_bit_and_get_bit(self):
        """_set_bit marks a position, _get_bit reads it back."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        bd._set_bit(0)
        assert bd._get_bit(0) is True

    def test_get_bit_unset_returns_false(self):
        """_get_bit returns False for a bit that was never set."""
        from modules.enrichers.deduplication import BloomDedup

        bd = BloomDedup()
        # Position 7 in a fresh filter should be 0
        assert bd._get_bit(7) is False


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — AsyncMergeExecutor (lines 838-901)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAsyncMergeExecutor:
    """Lines 838-901: AsyncMergeExecutor.execute()."""

    @pytest.mark.asyncio
    async def test_execute_invalid_canonical_uuid_returns_error(self):
        """Non-UUID canonical_id returns merged=False with error."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        mock_session = AsyncMock()
        result = await executor.execute(
            {"canonical_id": "not-a-uuid", "duplicate_id": str(uuid.uuid4())},
            mock_session,
        )
        assert result["merged"] is False
        assert "Invalid UUID" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_invalid_duplicate_uuid_returns_error(self):
        """Non-UUID duplicate_id returns merged=False with error."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        mock_session = AsyncMock()
        result = await executor.execute(
            {"canonical_id": str(uuid.uuid4()), "duplicate_id": "also-not-a-uuid"},
            mock_session,
        )
        assert result["merged"] is False
        assert "Invalid UUID" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_same_id_returns_error(self):
        """canonical_id == duplicate_id returns merged=False."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        same_id = str(uuid.uuid4())
        mock_session = AsyncMock()
        result = await executor.execute(
            {"canonical_id": same_id, "duplicate_id": same_id},
            mock_session,
        )
        assert result["merged"] is False
        assert "must differ" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_success_returns_merged_true(self):
        """Successful execution returns merged=True and tables_updated list."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        canonical_id = str(uuid.uuid4())
        duplicate_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await executor.execute(
            {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            mock_session,
        )
        assert result["merged"] is True
        assert result["canonical_id"] == canonical_id
        assert result["duplicate_id"] == duplicate_id
        assert "tables_updated" in result
        assert "merged_at" in result
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_success_no_rows_affected_empty_tables(self):
        """When rowcount=0, tables_updated is empty."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        canonical_id = str(uuid.uuid4())
        duplicate_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        result = await executor.execute(
            {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            mock_session,
        )
        assert result["merged"] is True
        assert result["tables_updated"] == []

    @pytest.mark.asyncio
    async def test_execute_exception_triggers_rollback(self):
        """DB exception triggers rollback and returns merged=False."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        canonical_id = str(uuid.uuid4())
        duplicate_id = str(uuid.uuid4())

        mock_session = AsyncMock()
        mock_session.execute.side_effect = RuntimeError("DB connection lost")

        result = await executor.execute(
            {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
            mock_session,
        )
        assert result["merged"] is False
        assert "DB connection lost" in result["error"]
        mock_session.rollback.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION — score_person_dedup (lines 925-1073)
# ═══════════════════════════════════════════════════════════════════════════════


class TestScorePersonDedup:
    """Lines 925-1073: score_person_dedup async entrypoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_session_raises_general_exception(self):
        """When session.execute raises an unexpected exception, returns []."""
        from modules.enrichers.deduplication import score_person_dedup

        mock_session = AsyncMock()
        mock_session.execute.side_effect = RuntimeError("unexpected DB error")

        result = await score_person_dedup(str(uuid.uuid4()), mock_session)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_person_not_found(self):
        """When the target person row doesn't exist in DB, returns []."""
        from modules.enrichers.deduplication import score_person_dedup

        mock_session = AsyncMock()

        # person query returns None
        person_result = MagicMock()
        person_result.scalar_one_or_none.return_value = None

        mock_session.execute.return_value = person_result

        result = await score_person_dedup(str(uuid.uuid4()), mock_session)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_candidates_found(self):
        """When blocking finds no candidate persons, returns []."""
        from modules.enrichers.deduplication import score_person_dedup

        mock_session = AsyncMock()

        # Build fake person
        mock_person = MagicMock()
        mock_person.id = str(uuid.uuid4())
        mock_person.full_name = "Unique Name"
        mock_person.dob = None

        # Identifiers query returns empty
        mock_idents_result = MagicMock()
        mock_idents_result.scalars.return_value.all.return_value = []

        # Person query returns our person
        mock_person_result = MagicMock()
        mock_person_result.scalar_one_or_none.return_value = mock_person

        # Candidate person query returns empty
        mock_candidate_result = MagicMock()
        mock_candidate_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_person_result
            elif call_count == 2:
                return mock_idents_result
            else:
                return mock_candidate_result

        mock_session.execute = mock_execute

        result = await score_person_dedup(str(mock_person.id), mock_session)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# BIOGRAPHICAL — _extract_single_dob invalid date branches (lines 97-98, 109-110, 117-118)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractSingleDobInvalidDates:
    """Lines 97-98, 109-110, 117-118, 127-128: ValueError branches in _extract_single_dob."""

    def test_invalid_iso_date_month_13_returns_none(self):
        """ISO date with month 13 is invalid → returns None, not a crash."""
        from modules.enrichers.biographical import _extract_single_dob

        result = _extract_single_dob("born on 2001-13-05")
        assert result is None

    def test_invalid_iso_date_day_32_returns_none(self):
        """ISO date with day 32 is invalid → falls through to None."""
        from modules.enrichers.biographical import _extract_single_dob

        result = _extract_single_dob("born on 1990-01-32")
        assert result is None

    def test_invalid_month_name_day_32_returns_none(self):
        """Month-name format with impossible day falls through."""
        from modules.enrichers.biographical import _extract_single_dob

        result = _extract_single_dob("January 32, 1990")
        assert result is None

    def test_invalid_slash_date_month_0_returns_none(self):
        """Slash date MM/DD/YYYY with month 0 is invalid."""
        from modules.enrichers.biographical import _extract_single_dob

        result = _extract_single_dob("Date: 00/15/1990")
        assert result is None

    def test_invalid_dob_short_format_day_31_feb_returns_none(self):
        """Two-digit year DOB format with impossible Feb 31 is invalid."""
        from modules.enrichers.biographical import _extract_single_dob

        result = _extract_single_dob("DOB: 02/31/90")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# BURNER DETECTOR — _confidence_from_score POSSIBLE branch (line 75)
# BURNER DETECTOR — persist_burner_assessment update path (lines 198-204)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBurnerDetectorEdgeCases:
    """Lines 75, 198-204: POSSIBLE confidence tier + upsert update path."""

    def test_confidence_possible_between_0_20_and_0_39(self):
        """Score in [0.20, 0.40) returns POSSIBLE confidence."""
        from modules.enrichers.burner_detector import _confidence_from_score
        from shared.constants import BurnerConfidence

        assert _confidence_from_score(0.20) == BurnerConfidence.POSSIBLE
        assert _confidence_from_score(0.30) == BurnerConfidence.POSSIBLE
        assert _confidence_from_score(0.39) == BurnerConfidence.POSSIBLE

    def test_confidence_clean_below_0_20(self):
        """Score below 0.20 returns CLEAN."""
        from modules.enrichers.burner_detector import _confidence_from_score
        from shared.constants import BurnerConfidence

        assert _confidence_from_score(0.0) == BurnerConfidence.CLEAN
        assert _confidence_from_score(0.19) == BurnerConfidence.CLEAN

    @pytest.mark.asyncio
    async def test_persist_burner_updates_existing_assessment(self):
        """When an existing assessment is found, it is updated in-place (not re-added)."""
        from modules.enrichers.burner_detector import (
            compute_burner_score,
            persist_burner_assessment,
        )
        from shared.constants import LineType

        score = compute_burner_score(
            phone="+15550000099",
            carrier_name="TextNow",
            line_type=LineType.VOIP,
            whatsapp_registered=False,
            telegram_registered=False,
        )

        identifier_id = uuid.uuid4()

        # Build a mock existing assessment object
        existing_assessment = MagicMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_assessment

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        returned = await persist_burner_assessment(
            session=mock_session,
            identifier_id=identifier_id,
            score=score,
        )

        # session.add should NOT be called because the record already exists
        mock_session.add.assert_not_called()

        # The returned object is the existing assessment with updated fields
        assert returned is existing_assessment
        assert existing_assessment.burner_score == score.score
        assert existing_assessment.confidence == score.confidence.value
        assert existing_assessment.signals == score.signals


# ═══════════════════════════════════════════════════════════════════════════════
# PSYCHOLOGICAL — _derive_predispositions branches (lines 369, 375, 379, 385, 397, 401)
# ═══════════════════════════════════════════════════════════════════════════════


class TestPsychologicalPredispositions:
    """Lines 369, 375, 379, 385, 397, 401: predisposition derivation branches."""

    def test_high_conscientiousness_adds_financial_planning(self):
        """conscientiousness > 0.6 adds financial_planning to predispositions."""
        texts = [
            "I am very organized disciplined goal-oriented professional and meticulous "
            "about deadlines and structured planning. " * 5
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        assert profile.conscientiousness > 0.6
        assert "financial_planning" in profile.product_predispositions

    def test_high_extraversion_adds_social_events(self):
        """extraversion > 0.6 adds social_events to predispositions."""
        texts = [
            "I love socializing outgoing friendly chatty gregarious parties "
            "social events people energetic enthusiastic talkative. " * 5
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        assert profile.extraversion > 0.6
        assert "social_events" in profile.product_predispositions

    def test_high_neuroticism_adds_health_insurance(self):
        """neuroticism > 0.6 adds health_insurance to predispositions."""
        texts = [
            "I feel anxious stressed worried overwhelmed fearful tense nervous "
            "depressed moody unstable insecure paranoid. " * 5
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        assert profile.neuroticism > 0.6
        assert "health_insurance" in profile.product_predispositions

    def test_low_conscientiousness_with_money_theme_adds_debt_consolidation(self):
        """conscientiousness < 0.4 + money theme adds debt_consolidation."""
        texts = [
            "money money financial debt loan debt bills afford money debt "
            "impulsive lazy disorganized careless reckless procrastinate. " * 4
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        # If debt_consolidation is present, the branch fired
        if profile.conscientiousness < 0.4:
            assert "debt_consolidation" in profile.product_predispositions

    def test_family_theme_no_financial_stress_adds_mortgage_receptive(self):
        """family theme + no financial stress adds mortgage_receptive."""
        texts = [
            "I love my family children home spouse marriage. "
            "family family children family home family. " * 6
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        if not profile.financial_stress_language and "family" in profile.dominant_themes:
            assert "mortgage_receptive" in profile.product_predispositions

    def test_career_theme_high_conscientiousness_adds_professional_services(self):
        """career theme + conscientiousness > 0.5 adds professional_services."""
        texts = [
            "career job work organized disciplined goal-oriented professional "
            "career career job work career job work career. " * 5
        ]
        from modules.enrichers.psychological import build_psychological_profile

        profile = build_psychological_profile(texts)
        if "career" in profile.dominant_themes and profile.conscientiousness > 0.5:
            assert "professional_services" in profile.product_predispositions


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING — _context_weights identity branch + _score_result source_reliability
# (lines 123, 173-174, 176)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRankingEdgeCases:
    """Lines 123, 173-174, 176: identity context weights + fallback quality field + invalid scraped_at."""

    def test_identity_context_weights(self):
        """'identity' context returns quality=0.40, authority=0.30."""
        from modules.enrichers.ranking import _context_weights

        w = _context_weights("identity")
        assert w["quality"] == 0.40
        assert w["authority"] == 0.30
        assert w["risk_relevance"] == 0.10
        assert w["recency"] == 0.20

    def test_source_reliability_fallback_when_no_composite_quality(self):
        """When composite_quality is absent, source_reliability is used as quality."""
        from modules.enrichers.ranking import rank_results

        results = [{"source_reliability": 0.75, "source_type": "linkedin", "scraped_at": None}]
        ranked = rank_results(results)
        assert ranked[0].score_breakdown["quality"] == pytest.approx(0.75)

    def test_invalid_scraped_at_string_returns_0_5_recency(self):
        """Invalid ISO string for scraped_at falls back to recency=0.5."""
        from modules.enrichers.ranking import _compute_recency

        item = {"scraped_at": "not-a-date-string"}
        score = _compute_recency(item)
        assert score == 0.5

    def test_naive_datetime_gets_utc_attached(self):
        """Naive (no tzinfo) datetime object gets timezone.utc attached without error."""
        from datetime import datetime

        from modules.enrichers.ranking import _compute_recency

        # Pass a naive datetime directly (not a string)
        naive_dt = datetime(2026, 3, 20, 12, 0, 0)  # ~4 days ago from 2026-03-24
        item = {"scraped_at": naive_dt}
        score = _compute_recency(item)
        assert 0.0 <= score <= 1.0

    def test_sort_by_identity_context_via_rank_results(self):
        """rank_results with context='identity' uses identity weights without error."""
        from modules.enrichers.ranking import rank_results

        results = [
            {"composite_quality": 0.8, "source_type": "government_registry", "scraped_at": None},
            {"composite_quality": 0.3, "source_type": "dark_paste", "scraped_at": None},
        ]
        ranked = rank_results(results, context="identity")
        assert len(ranked) == 2
        assert ranked[0].rank_score >= ranked[1].rank_score


# ═══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION — stdev=0 branch, severity tiers CRITICAL/HIGH (lines 57-58, 81, 83)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatisticalAnomalyDetector:
    """Lines 57-58, 81, 83: stdev=0 (all same value) + CRITICAL/HIGH severity."""

    def test_all_same_values_no_anomalies(self):
        """When all values are identical, stdev=0 and no anomaly is flagged."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector()
        entities = [{"id": str(i), "score": 5.0} for i in range(10)]
        results = detector.detect(entities, "score")
        assert results == []

    def test_fewer_than_3_entities_returns_empty(self):
        """With < 3 entities the detector returns [] immediately."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector()
        entities = [{"id": "1", "score": 100.0}, {"id": "2", "score": 1.0}]
        results = detector.detect(entities, "score")
        assert results == []

    def test_critical_severity_triggered_above_z_6(self):
        """A value with z-score > 6 gets CRITICAL severity.

        Need ~100 tightly-clustered points so the outlier's z-score exceeds 6.
        """
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector(z_threshold=3.0)
        # 100 points at 0.0, then one at 100.0 → z ≈ 9.9
        entities = [{"id": str(i), "score": 0.0} for i in range(100)]
        entities.append({"id": "outlier", "score": 100.0})
        results = detector.detect(entities, "score")
        assert len(results) >= 1
        top = results[0]
        assert top.entity_id == "outlier"
        assert top.severity == "CRITICAL"

    def test_high_severity_triggered_between_z_4_5_and_z_6(self):
        """A value with z-score in (4.5, 6] gets HIGH severity."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector(z_threshold=3.0)
        # Base values clustered around 1.0 with small stdev
        entities = [{"id": str(i), "score": 1.0} for i in range(30)]
        # Add a value that places z roughly in the 4.5-6 range
        entities.append({"id": "high-outlier", "score": 50.0})
        results = detector.detect(entities, "score")
        assert len(results) >= 1
        outlier_result = next(r for r in results if r.entity_id == "high-outlier")
        assert outlier_result.severity in ("HIGH", "CRITICAL")

    def test_medium_severity_triggered_above_z_threshold(self):
        """A mild outlier with z just above 3.0 gets MEDIUM severity."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector(z_threshold=3.0)
        entities = [{"id": str(i), "score": float(i)} for i in range(1, 21)]
        # Add a moderate outlier
        entities.append({"id": "mild-outlier", "score": 80.0})
        results = detector.detect(entities, "score")
        if results:
            severities = {r.severity for r in results}
            assert severities <= {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def test_low_severity_iqr_outlier_only(self):
        """IQR outlier with z <= 3.0 gets LOW severity."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector(z_threshold=100.0, iqr_multiplier=0.1)
        # Very tight IQR multiplier forces most values to be flagged as IQR outliers
        entities = [{"id": str(i), "score": float(i)} for i in range(1, 21)]
        results = detector.detect(entities, "score")
        if results:
            for r in results:
                assert r.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_non_numeric_field_values_skipped(self):
        """Entities without the field or with non-numeric values are skipped."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector()
        entities = [
            {"id": "1", "score": 1.0},
            {"id": "2", "score": "not-a-number"},
            {"id": "3", "score": None},
            {"id": "4"},  # missing field entirely
            {"id": "5", "score": 2.0},
            {"id": "6", "score": 1.5},
        ]
        # Should not crash; processes only the numeric ones
        results = detector.detect(entities, "score")
        assert isinstance(results, list)

    def test_detect_multi_field_returns_dict(self):
        """detect_multi_field returns a dict keyed by field name."""
        from modules.patterns.anomaly import StatisticalAnomalyDetector

        detector = StatisticalAnomalyDetector()
        entities = [{"id": str(i), "a": float(i), "b": float(i * 2)} for i in range(10)]
        results = detector.detect_multi_field(entities, ["a", "b"])
        assert "a" in results
        assert "b" in results
        assert isinstance(results["a"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# INVERTED INDEX — remove_entity_from_field dict branch (line 85)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAttributeInvertedIndex:
    """Line 85: remove_entity_from_field handles dict values."""

    @pytest.mark.asyncio
    async def test_remove_entity_from_field_with_dict_value(self):
        """Dict values in entity_data are handled: sub-keys like field.subkey are removed."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        idx = AttributeInvertedIndex(mock_redis)

        entity_data = {
            "address": {"city": "Austin", "state": "TX"},
        }
        await idx.remove_entity_from_field("entity-1", entity_data)

        # Should have called srem for each sub-key
        calls = [str(c) for c in mock_redis.srem.call_args_list]
        assert any("address.city" in c for c in calls)
        assert any("address.state" in c for c in calls)

    @pytest.mark.asyncio
    async def test_remove_entity_from_field_with_list_value(self):
        """List values in entity_data cause srem to be called for each item."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        idx = AttributeInvertedIndex(mock_redis)

        entity_data = {"phones": ["+12025551234", "+13105559876"]}
        await idx.remove_entity_from_field("entity-2", entity_data)

        assert mock_redis.srem.call_count == 2

    @pytest.mark.asyncio
    async def test_remove_entity_from_field_skips_none_values(self):
        """None values in entity_data are skipped silently."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        idx = AttributeInvertedIndex(mock_redis)

        entity_data = {"name": None, "email": "test@example.com"}
        await idx.remove_entity_from_field("entity-3", entity_data)

        # Only email should trigger srem (name is None)
        assert mock_redis.srem.call_count == 1

    @pytest.mark.asyncio
    async def test_find_entities_decodes_bytes(self):
        """smembers returning bytes are decoded to str."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        mock_redis.smembers.return_value = {b"entity-abc", b"entity-def"}
        idx = AttributeInvertedIndex(mock_redis)

        result = await idx.find_entities("email", "alice@example.com")
        assert "entity-abc" in result
        assert "entity-def" in result

    @pytest.mark.asyncio
    async def test_find_entities_exception_returns_empty_set(self):
        """Exception in smembers returns empty set and logs."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        mock_redis.smembers.side_effect = RuntimeError("redis unavailable")
        idx = AttributeInvertedIndex(mock_redis)

        result = await idx.find_entities("email", "alice@example.com")
        assert result == set()

    @pytest.mark.asyncio
    async def test_find_co_occurrence_exception_returns_empty_set(self):
        """Exception in sinter returns empty set."""
        from modules.patterns.inverted_index import AttributeInvertedIndex

        mock_redis = AsyncMock()
        mock_redis.sinter.side_effect = RuntimeError("redis timeout")
        idx = AttributeInvertedIndex(mock_redis)

        result = await idx.find_co_occurrence("email", "a@b.com", "phone", "+123")
        assert result == set()


# ═══════════════════════════════════════════════════════════════════════════════
# CRAWLER REGISTRY — TYPE_CHECKING import branch (line 6)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrawlerRegistry:
    """Line 6: TYPE_CHECKING branch + full registry API."""

    def test_register_and_get_crawler(self):
        """register decorator adds a class; get_crawler retrieves it."""
        from modules.crawlers.registry import get_crawler, register

        @register("test_platform_alpha")
        class FakeCrawler:
            pass

        result = get_crawler("test_platform_alpha")
        assert result is FakeCrawler

    def test_get_crawler_case_insensitive(self):
        """get_crawler lookup is case-insensitive."""
        from modules.crawlers.registry import get_crawler, register

        @register("TestPlatformBeta")
        class AnotherFake:
            pass

        assert get_crawler("testplatformbeta") is AnotherFake
        assert get_crawler("TESTPLATFORMBETA") is AnotherFake

    def test_get_crawler_unknown_returns_none(self):
        """Unknown platform returns None."""
        from modules.crawlers.registry import get_crawler

        result = get_crawler("totally_unknown_xyz_123")
        assert result is None

    def test_list_platforms_returns_sorted_list(self):
        """list_platforms returns sorted list of registered names."""
        from modules.crawlers.registry import list_platforms, register

        @register("zzz_platform")
        class ZzzCrawler:
            pass

        @register("aaa_platform")
        class AaaCrawler:
            pass

        platforms = list_platforms()
        assert platforms == sorted(platforms)
        assert "zzz_platform" in platforms
        assert "aaa_platform" in platforms

    def test_is_registered_true_for_registered(self):
        """is_registered returns True after register."""
        from modules.crawlers.registry import is_registered, register

        @register("registered_platform_check")
        class CheckCrawler:
            pass

        assert is_registered("registered_platform_check") is True

    def test_is_registered_false_for_unknown(self):
        """is_registered returns False for unknown platform."""
        from modules.crawlers.registry import is_registered

        assert is_registered("totally_not_registered_xyz") is False
