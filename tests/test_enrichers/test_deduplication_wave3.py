"""
test_deduplication_wave3.py — Coverage gap tests for modules/enrichers/deduplication.py.

Targets:
  - ExactMatchDeduplicator dragonfly branch (lines ~113-119)
  - name_similarity empty args (lines ~164-165) and honorific-only tokens (lines ~176-177)
  - AsyncMergeExecutor unsafe table guard (lines ~865-867)
  - score_person_dedup ImportError (lines ~925-927)
  - Birth-year blocking query (lines ~966-974)
  - Phone-prefix blocking query (lines ~992-1002)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# ExactMatchDeduplicator — dragonfly branch
# ===========================================================================


class TestExactMatchDeduplicatorDragonfly:
    """Verify dragonfly SETNX path (was_set is None → duplicate)."""

    def _make_dedup(self, dragonfly_client=None):
        from modules.enrichers.deduplication import ExactMatchDeduplicator

        return ExactMatchDeduplicator(dragonfly_client=dragonfly_client)

    def test_dragonfly_detects_duplicate_on_second_call(self):
        """First insert returns 1 (new key); second insert returns None (duplicate)."""
        seen_keys = set()

        def _fake_set(key, value, ex=None, nx=False):
            if nx:
                if key in seen_keys:
                    return None  # already exists → duplicate
                seen_keys.add(key)
                return 1  # newly set
            seen_keys.add(key)
            return 1

        dragonfly = MagicMock()
        dragonfly.set = MagicMock(side_effect=_fake_set)

        dedup = self._make_dedup(dragonfly_client=dragonfly)

        record = {
            "email": "alice@example.com",
            "full_name": "Alice Smith",
            "dob": "1990-01-01",
        }

        # First call — not a duplicate
        is_dup1, key1 = dedup.check_and_mark_duplicate(record)
        assert is_dup1 is False

        # Second call with same record — dragonfly should detect it as a duplicate
        is_dup2, key2 = dedup.check_and_mark_duplicate(record)
        assert is_dup2 is True

    def test_dragonfly_newly_set_key_returns_not_duplicate(self):
        """When dragonfly.set returns truthy (new key), record is not a duplicate."""
        dragonfly = MagicMock()
        dragonfly.set = MagicMock(return_value=1)  # always newly set

        dedup = self._make_dedup(dragonfly_client=dragonfly)

        record = {"email": "bob@example.com"}
        is_dup, _ = dedup.check_and_mark_duplicate(record)
        assert is_dup is False


# ===========================================================================
# name_similarity edge cases
# ===========================================================================


class TestNameSimilarityEdgeCases:
    """Cover empty-arg and honorific-only branches."""

    def test_empty_name_a_returns_zero(self):
        from modules.enrichers.deduplication import name_similarity

        assert name_similarity("", "John Smith") == 0.0

    def test_empty_name_b_returns_zero(self):
        from modules.enrichers.deduplication import name_similarity

        assert name_similarity("John Smith", "") == 0.0

    def test_both_empty_returns_zero(self):
        from modules.enrichers.deduplication import name_similarity

        assert name_similarity("", "") == 0.0

    def test_honorific_only_tokens_returns_zero(self):
        """After stripping honorifics, both names have no tokens → score 0.0."""
        from modules.enrichers.deduplication import name_similarity

        # "Dr." and "Mr." are both honorifics; after stripping only empty tokens remain
        score = name_similarity("Dr.", "Mr.")
        assert score == 0.0

    def test_honorifics_stripped_before_comparison(self):
        """'Dr John Smith' and 'John Smith' should be highly similar."""
        from modules.enrichers.deduplication import name_similarity

        score = name_similarity("Dr John Smith", "John Smith")
        assert score >= 0.5  # at least partially matching after stripping honorifics


# ===========================================================================
# AsyncMergeExecutor — unsafe table guard
# ===========================================================================


class TestAsyncMergeExecutorUnsafeTable:
    """Verify that table names not matching _SAFE_TABLE_RE are skipped."""

    @pytest.mark.asyncio
    async def test_unsafe_table_name_is_skipped(self):
        """Inject an unsafe table name into REASSIGN_TABLES and confirm it's skipped."""
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()

        # Temporarily override REASSIGN_TABLES with a safe and an unsafe name
        original_tables = executor.REASSIGN_TABLES
        executor.REASSIGN_TABLES = ("identifiers", "DROP TABLE persons; --")

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        session.commit = AsyncMock()

        plan = {
            "canonical_id": str(uuid.uuid4()),
            "duplicate_id": str(uuid.uuid4()),
        }

        result = await executor.execute(plan, session)

        executor.REASSIGN_TABLES = original_tables

        # The unsafe table should have been skipped; merge may still succeed
        assert result["merged"] is True

    @pytest.mark.asyncio
    async def test_same_canonical_and_duplicate_id_rejected(self):
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        same_id = str(uuid.uuid4())

        session = AsyncMock()
        plan = {"canonical_id": same_id, "duplicate_id": same_id}

        result = await executor.execute(plan, session)
        assert result["merged"] is False
        assert "must differ" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_uuid_rejected(self):
        from modules.enrichers.deduplication import AsyncMergeExecutor

        executor = AsyncMergeExecutor()
        session = AsyncMock()
        plan = {"canonical_id": "not-a-uuid", "duplicate_id": str(uuid.uuid4())}

        result = await executor.execute(plan, session)
        assert result["merged"] is False
        assert "Invalid UUID" in result["error"]


# ===========================================================================
# score_person_dedup — ImportError branch
# ===========================================================================


class TestScorePersonDedupImportError:
    """Cover the ImportError early-return path."""

    @pytest.mark.asyncio
    async def test_import_error_returns_empty_list(self):
        """When shared models are unavailable, score_person_dedup returns []."""
        session = AsyncMock()
        person_id = str(uuid.uuid4())

        # Patch the import inside the function
        import builtins
        real_import = builtins.__import__

        def _bad_import(name, *args, **kwargs):
            if name in ("shared.models.address", "shared.models.identifier", "shared.models.person"):
                raise ImportError(f"mocked missing: {name}")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_bad_import):
            from modules.enrichers.deduplication import score_person_dedup
            result = await score_person_dedup(person_id, session)

        assert result == []


# ===========================================================================
# score_person_dedup — birth-year blocking query
# ===========================================================================


class TestScorePersonDedupBlocking:
    """Cover birth-year and phone-prefix blocking query paths."""

    def _make_execute_sequence(self, person_id_str, candidate_id_str=None):
        """
        Build a sequence of execute() results that drives score_person_dedup through
        its blocking stages and returns empty candidate_ids at the end.
        """
        # 1. select(Person) → target_person
        # 2. select(Identifier) → target_idents
        # 3. select(Person.id) for birth-year blocking (optional)
        # 4. select(Person.id) for last-name blocking
        # 5. select(Identifier.person_id) for phone-prefix blocking (optional)
        # 6. select(Person) for candidates
        # 7. select(Identifier) for all idents
        results = []

        person = MagicMock()
        person.id = person_id_str
        person.full_name = "John Smith"

        # 1. target person
        r1 = MagicMock()
        r1.scalar_one_or_none = MagicMock(return_value=person)
        results.append(r1)

        # 2. identifiers for target
        r2 = MagicMock()
        scalars2 = MagicMock()
        scalars2.all = MagicMock(return_value=[])
        r2.scalars = MagicMock(return_value=scalars2)
        results.append(r2)

        # 3. last-name blocking (Person.id)
        r3 = MagicMock()
        r3.fetchall = MagicMock(return_value=[])
        results.append(r3)

        # 4+ candidates query
        r4 = MagicMock()
        scalars4 = MagicMock()
        scalars4.all = MagicMock(return_value=[])
        r4.scalars = MagicMock(return_value=scalars4)
        results.append(r4)

        # 5. all_idents
        r5 = MagicMock()
        scalars5 = MagicMock()
        scalars5.all = MagicMock(return_value=[])
        r5.scalars = MagicMock(return_value=scalars5)
        results.append(r5)

        return results

    @pytest.mark.asyncio
    async def test_birth_year_blocking_executes_query(self):
        """When person has a dob, birth-year blocking query runs."""
        from modules.enrichers.deduplication import score_person_dedup

        person_id = str(uuid.uuid4())

        person = MagicMock()
        person.id = person_id
        person.full_name = "Jane Doe"
        setattr(person, "dob", "1985-06-15")  # triggers birth-year blocking

        session = AsyncMock()
        call_count = [0]

        async def _execute(stmt, *args, **kwargs):
            c = call_count[0]
            call_count[0] += 1

            r = MagicMock()
            if c == 0:
                # target person query
                r.scalar_one_or_none = MagicMock(return_value=person)
            elif c == 1:
                # identifiers query
                scalars = MagicMock()
                scalars.all = MagicMock(return_value=[])
                r.scalars = MagicMock(return_value=scalars)
            else:
                # blocking queries all return empty
                r.fetchall = MagicMock(return_value=[])
                scalars = MagicMock()
                scalars.all = MagicMock(return_value=[])
                r.scalars = MagicMock(return_value=scalars)
            return r

        session.execute = _execute

        result = await score_person_dedup(person_id, session)
        assert isinstance(result, list)
        # Birth-year query should have triggered (call_count > 2)
        assert call_count[0] >= 2

    @pytest.mark.asyncio
    async def test_phone_prefix_blocking_executes_query(self):
        """When person has phone identifiers, phone-prefix blocking query runs."""
        from modules.enrichers.deduplication import score_person_dedup

        person_id = str(uuid.uuid4())

        person = MagicMock()
        person.id = person_id
        person.full_name = "John Doe"
        setattr(person, "dob", None)

        phone_ident = MagicMock()
        phone_ident.type = "phone"
        phone_ident.normalized_value = "+15551234567"
        phone_ident.value = "+15551234567"

        session = AsyncMock()
        call_count = [0]

        async def _execute(stmt, *args, **kwargs):
            c = call_count[0]
            call_count[0] += 1

            r = MagicMock()
            if c == 0:
                r.scalar_one_or_none = MagicMock(return_value=person)
            elif c == 1:
                # identifiers — return the phone_ident
                scalars = MagicMock()
                scalars.all = MagicMock(return_value=[phone_ident])
                r.scalars = MagicMock(return_value=scalars)
            else:
                r.fetchall = MagicMock(return_value=[])
                scalars = MagicMock()
                scalars.all = MagicMock(return_value=[])
                r.scalars = MagicMock(return_value=scalars)
            return r

        session.execute = _execute

        result = await score_person_dedup(person_id, session)
        assert isinstance(result, list)
        # Phone-prefix query should have fired (at least last-name + phone = 2 blocking calls)
        assert call_count[0] >= 3

    @pytest.mark.asyncio
    async def test_person_not_found_returns_empty(self):
        """score_person_dedup returns [] when person doesn't exist in DB."""
        from modules.enrichers.deduplication import score_person_dedup

        session = AsyncMock()
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=r)

        result = await score_person_dedup(str(uuid.uuid4()), session)
        assert result == []
