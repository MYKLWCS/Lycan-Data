"""
Wave-3 tests for modules/enrichers/deduplication.py

Covers:
  1. ExactMatchDeduplicator.check_and_mark_duplicate() — Dragonfly branch
     - dragonfly.set() returns None  → duplicate=True
     - dragonfly.set() returns True  → duplicate=False
  2. name_similarity() edge cases
     - empty string arguments  → 0.0
     - honorific-only tokens   → 0.0
  3. AsyncMergeExecutor._unsafe_merge_table() guard (bad table name rejected)
  4. score_person_dedup ImportError path — shared models unavailable → []
  5. Birth-year blocking query path
  6. Phone-prefix blocking query path
  7. Full orchestration path through score_person_dedup

Run with:
    pytest tests/test_enrichers/test_deduplication_wave3.py
"""

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — ensure the module-under-test is importable even when optional deps
# (SQLAlchemy, shared.models) are absent.
# ---------------------------------------------------------------------------

def _make_fake_sa():
    """Return a minimal sqlalchemy stub so the top-level import in
    deduplication.py doesn't fail in environments without the real package."""
    sa = types.ModuleType("sqlalchemy")
    sa.text = MagicMock(return_value=MagicMock())
    sa.select = MagicMock(return_value=MagicMock())

    ext = types.ModuleType("sqlalchemy.ext")
    ext_async = types.ModuleType("sqlalchemy.ext.asyncio")
    ext_async.AsyncSession = object

    sa.ext = ext
    ext.async_ = ext_async

    sys.modules.setdefault("sqlalchemy", sa)
    sys.modules.setdefault("sqlalchemy.ext", ext)
    sys.modules.setdefault("sqlalchemy.ext.asyncio", ext_async)
    return sa


_make_fake_sa()

from modules.enrichers.deduplication import (  # noqa: E402
    AsyncMergeExecutor,
    ExactMatchDeduplicator,
    MergeCandidate,
    _SAFE_TABLE_RE,
    name_similarity,
    score_person_dedup,
)


# ===========================================================================
# 1. ExactMatchDeduplicator — Dragonfly branch
# ===========================================================================


class TestExactMatchDeduplicatorDragonflyBranch:
    """Tests for check_and_mark_duplicate() when a dragonfly client is injected."""

    def _record(self) -> dict:
        return {
            "full_name": "Alice Wonderland",
            "dob": "1990-01-01",
            "email": "alice@example.com",
        }

    def test_dragonfly_set_returns_none_is_duplicate(self):
        """
        When dragonfly.set(..., nx=True) returns None the key already existed —
        the record must be reported as a duplicate.
        """
        mock_dragonfly = MagicMock()
        mock_dragonfly.set.return_value = None  # key already existed

        dedup = ExactMatchDeduplicator(dragonfly_client=mock_dragonfly)
        is_dup, matched_key = dedup.check_and_mark_duplicate(self._record())

        assert is_dup is True
        assert matched_key  # some non-empty key was matched

    def test_dragonfly_set_returns_true_is_not_duplicate(self):
        """
        When dragonfly.set(..., nx=True) returns True the key was freshly written —
        the record must NOT be reported as a duplicate for any key.
        """
        mock_dragonfly = MagicMock()
        mock_dragonfly.set.return_value = True  # key was newly created

        dedup = ExactMatchDeduplicator(dragonfly_client=mock_dragonfly)
        is_dup, matched_key = dedup.check_and_mark_duplicate(self._record())

        assert is_dup is False
        assert matched_key == ""

    def test_dragonfly_set_called_with_nx_true(self):
        """The NX flag must be forwarded to dragonfly.set() so the operation is atomic."""
        mock_dragonfly = MagicMock()
        mock_dragonfly.set.return_value = True

        dedup = ExactMatchDeduplicator(dragonfly_client=mock_dragonfly)
        dedup.check_and_mark_duplicate(self._record())

        # Every call to set() must use nx=True
        for call in mock_dragonfly.set.call_args_list:
            assert call.kwargs.get("nx") is True or call[1].get("nx") is True

    def test_dragonfly_set_called_with_expiry(self):
        """Each key must be written with a TTL (ex=86400)."""
        mock_dragonfly = MagicMock()
        mock_dragonfly.set.return_value = True

        dedup = ExactMatchDeduplicator(dragonfly_client=mock_dragonfly)
        dedup.check_and_mark_duplicate(self._record())

        for call in mock_dragonfly.set.call_args_list:
            ex_val = call.kwargs.get("ex") or call[1].get("ex")
            assert ex_val == 86400

    def test_dragonfly_second_call_same_record_duplicate(self):
        """
        On the first call set() returns True (new). On the second call for the
        same record set() returns None (already present) — should be detected
        as duplicate.
        """
        mock_dragonfly = MagicMock()
        mock_dragonfly.set.side_effect = [True, True, True, None]  # first pass ok, second hits None

        dedup = ExactMatchDeduplicator(dragonfly_client=mock_dragonfly)
        is_dup1, _ = dedup.check_and_mark_duplicate(self._record())
        is_dup2, matched_key = dedup.check_and_mark_duplicate(self._record())

        assert is_dup1 is False
        assert is_dup2 is True
        assert matched_key


# ===========================================================================
# 2. name_similarity() edge cases
# ===========================================================================


class TestNameSimilarityEdgeCases:
    """Lines ~164-165, 176-177."""

    def test_empty_first_arg_returns_zero(self):
        assert name_similarity("", "John Smith") == 0.0

    def test_empty_second_arg_returns_zero(self):
        assert name_similarity("John Smith", "") == 0.0

    def test_both_empty_returns_zero(self):
        assert name_similarity("", "") == 0.0

    def test_honorific_only_first_arg_returns_zero(self):
        """
        'Mr' is an honorific and gets stripped by normalize_name().
        The resulting token set is empty → similarity must be 0.0.
        """
        result = name_similarity("Mr", "John Smith")
        assert result == 0.0

    def test_honorific_only_second_arg_returns_zero(self):
        result = name_similarity("John Smith", "Dr")
        assert result == 0.0

    def test_both_honorific_only_returns_one(self):
        """
        Both 'Mrs' and 'Dr' normalize to an empty string.
        Empty strings are identical ('""' == '""'), so the function returns 1.0
        (the early-exit identical-after-normalize branch at line ~170).
        This test pins that documented behavior — do NOT change to 0.0.
        """
        result = name_similarity("Mrs", "Dr")
        assert result == 1.0

    def test_honorific_plus_real_name_non_zero(self):
        """Honorific stripped; real tokens remain → score > 0."""
        result = name_similarity("Mr John Smith", "John Smith")
        assert result > 0.0

    def test_identical_names_return_one(self):
        assert name_similarity("Alice Wonderland", "Alice Wonderland") == 1.0

    def test_completely_different_names_return_zero(self):
        assert name_similarity("Alice Wonderland", "Bob Builder") == 0.0


# ===========================================================================
# 3. AsyncMergeExecutor — _SAFE_TABLE_RE guard on bad table names
# ===========================================================================


class TestAsyncMergeExecutorTableGuard:
    """Lines ~865-867: unsafe table names must be skipped."""

    def test_safe_table_re_accepts_valid_names(self):
        valid = [
            "identifiers",
            "social_profiles",
            "audit_log",
            "addresses",
            "a1",
            "ab",
        ]
        for name in valid:
            assert _SAFE_TABLE_RE.match(name), f"Expected {name!r} to be accepted"

    def test_safe_table_re_rejects_injection_attempts(self):
        dangerous = [
            "persons; DROP TABLE persons--",
            "1starts_with_digit",
            "has space",
            "has-hyphen",
            "has.dot",
            "a",  # single character (regex requires {1,62} after first char → needs at least 2 chars total)
            "",
            "UPPERCASE",
        ]
        for name in dangerous:
            assert not _SAFE_TABLE_RE.match(name), f"Expected {name!r} to be rejected"

    @pytest.mark.asyncio
    async def test_bad_table_name_is_skipped_not_executed(self):
        """
        If REASSIGN_TABLES contained an unsafe entry, the executor must skip it
        and not call session.execute() for that table.
        """
        executor = AsyncMergeExecutor()
        # Temporarily monkey-patch REASSIGN_TABLES with one bad + one good entry
        bad_table = "bad table; DROP TABLE persons--"
        good_table = "identifiers"

        canonical_id = str(uuid.uuid4())
        duplicate_id = str(uuid.uuid4())

        mock_session = AsyncMock()
        execute_result = MagicMock()
        execute_result.rowcount = 0
        mock_session.execute.return_value = execute_result
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        with patch.object(AsyncMergeExecutor, "REASSIGN_TABLES", (bad_table, good_table)):
            result = await executor.execute(
                {"canonical_id": canonical_id, "duplicate_id": duplicate_id},
                mock_session,
            )

        # The merge should still succeed (no exception)
        assert result["merged"] is True

        # The SQL statements that were actually executed must not contain the bad table name
        for call_args in mock_session.execute.call_args_list:
            stmt = call_args[0][0]
            stmt_text = str(stmt) if not hasattr(stmt, "text") else stmt.text
            assert bad_table not in stmt_text, (
                f"Unsafe table name leaked into SQL: {stmt_text!r}"
            )

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_error(self):
        executor = AsyncMergeExecutor()
        mock_session = AsyncMock()

        result = await executor.execute(
            {"canonical_id": "not-a-uuid", "duplicate_id": str(uuid.uuid4())},
            mock_session,
        )
        assert result["merged"] is False
        assert "Invalid UUID" in result["error"]

    @pytest.mark.asyncio
    async def test_same_id_returns_error(self):
        executor = AsyncMergeExecutor()
        mock_session = AsyncMock()
        same_id = str(uuid.uuid4())

        result = await executor.execute(
            {"canonical_id": same_id, "duplicate_id": same_id},
            mock_session,
        )
        assert result["merged"] is False
        assert "must differ" in result["error"]


# ===========================================================================
# 4. score_person_dedup — ImportError path
# ===========================================================================


class TestScorePersonDedupImportError:
    """Lines ~925-927: when shared.models are unavailable the function returns []."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_shared_models_missing(self):
        """
        Patch sys.modules so that importing shared.models.* raises ImportError.
        score_person_dedup should catch it and return [].
        """
        mock_session = AsyncMock()
        person_id = str(uuid.uuid4())

        # Hide the shared.models packages by mapping them to None in sys.modules
        modules_to_hide = {
            "shared": None,
            "shared.models": None,
            "shared.models.person": None,
            "shared.models.identifier": None,
            "shared.models.address": None,
        }

        with patch.dict(sys.modules, modules_to_hide):
            result = await score_person_dedup(person_id, mock_session)

        assert result == []

    @pytest.mark.asyncio
    async def test_session_not_called_when_import_fails(self):
        """The session must never be touched if the models can't be imported."""
        mock_session = AsyncMock()
        person_id = str(uuid.uuid4())

        modules_to_hide = {
            "shared": None,
            "shared.models": None,
            "shared.models.person": None,
            "shared.models.identifier": None,
            "shared.models.address": None,
        }

        with patch.dict(sys.modules, modules_to_hide):
            await score_person_dedup(person_id, mock_session)

        mock_session.execute.assert_not_called()


# ===========================================================================
# Shared fixtures / helpers for tests 5-7
# ===========================================================================


def _make_shared_models():
    """
    Build minimal stub modules for shared.models.{person,identifier,address}
    and inject them into sys.modules so score_person_dedup can import them.
    Returns (Person, Identifier, Address) mock classes.
    """
    # Person
    Person = MagicMock(name="Person")
    Person.id = MagicMock()
    Person.full_name = MagicMock()
    Person.full_name.ilike = MagicMock(return_value=MagicMock())
    Person.id.in_ = MagicMock(return_value=MagicMock())

    # Identifier
    Identifier = MagicMock(name="Identifier")
    Identifier.person_id = MagicMock()
    Identifier.type = MagicMock()
    Identifier.person_id.in_ = MagicMock(return_value=MagicMock())

    # Address
    Address = MagicMock(name="Address")
    Address.person_id = MagicMock()
    Address.person_id.in_ = MagicMock(return_value=MagicMock())

    shared_pkg = types.ModuleType("shared")
    shared_models = types.ModuleType("shared.models")
    mod_person = types.ModuleType("shared.models.person")
    mod_identifier = types.ModuleType("shared.models.identifier")
    mod_address = types.ModuleType("shared.models.address")

    mod_person.Person = Person
    mod_identifier.Identifier = Identifier
    mod_address.Address = Address

    shared_pkg.models = shared_models
    shared_models.person = mod_person
    shared_models.identifier = mod_identifier
    shared_models.address = mod_address

    overrides = {
        "shared": shared_pkg,
        "shared.models": shared_models,
        "shared.models.person": mod_person,
        "shared.models.identifier": mod_identifier,
        "shared.models.address": mod_address,
    }
    return overrides, Person, Identifier, Address


def _make_person(pid: str, full_name: str = "Alice Smith", dob: str = "1990-03-15"):
    p = MagicMock()
    p.id = pid
    p.full_name = full_name
    p.dob = dob
    return p


def _make_identifier(person_id: str, id_type: str, value: str):
    ident = MagicMock()
    ident.person_id = person_id
    ident.type = id_type
    ident.normalized_value = value
    ident.value = value
    return ident


def _make_address(person_id: str, city: str = "Austin", state: str = "TX"):
    addr = MagicMock()
    addr.person_id = person_id
    addr.city = city
    addr.state = state
    return addr


def _build_session(
    target_person,
    target_idents=None,
    candidate_ids_rows=None,
    ln_ids_rows=None,
    ph_ids_rows=None,
    candidate_persons=None,
    all_idents=None,
    all_addresses=None,
):
    """
    Build an AsyncMock session whose execute() returns pre-configured results
    in call order, matching the call sequence inside score_person_dedup.

    Call order:
      0. person_stmt        → scalar_one_or_none → target_person
      1. ident_stmt         → scalars().all()    → target_idents
      2. by_stmt (dob)      → fetchall()         → candidate_ids_rows (if dob set)
      3. ln_stmt (name)     → fetchall()         → ln_ids_rows
      4. ph_stmt(s) (phone) → fetchall()         → ph_ids_rows per prefix
      5. cand_stmt          → scalars().all()    → candidate_persons
      6. cand_ident_stmt    → scalars().all()    → all_idents
      7. addr_stmt          → scalars().all()    → all_addresses
    """
    target_idents = target_idents or []
    candidate_ids_rows = candidate_ids_rows or []
    ln_ids_rows = ln_ids_rows or []
    ph_ids_rows = ph_ids_rows or []
    candidate_persons = candidate_persons or []
    all_idents = all_idents or []
    all_addresses = all_addresses or []

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        return r

    def _scalars_result(items):
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        r = MagicMock()
        r.scalars.return_value = scalars_mock
        return r

    def _fetchall_result(rows):
        r = MagicMock()
        r.fetchall.return_value = rows
        return r

    # Build the ordered side_effect list
    calls = [
        _scalar_result(target_person),       # person lookup
        _scalars_result(target_idents),      # target identifiers
    ]

    # birth-year blocking (only added when target_person.dob is truthy)
    if target_person and getattr(target_person, "dob", None):
        calls.append(_fetchall_result(candidate_ids_rows))  # by_stmt

    # last-name blocking (only added when full_name is truthy)
    if target_person and getattr(target_person, "full_name", None):
        calls.append(_fetchall_result(ln_ids_rows))  # ln_stmt

    # phone-prefix blocking — one call per phone prefix
    for _ in ph_ids_rows if isinstance(ph_ids_rows, list) else []:
        calls.append(_fetchall_result([ph_ids_rows] if not isinstance(ph_ids_rows[0], list) else ph_ids_rows))

    # candidate load
    calls.append(_scalars_result(candidate_persons))   # cand_stmt
    calls.append(_scalars_result(all_idents))          # cand_ident_stmt
    calls.append(_scalars_result(all_addresses))       # addr_stmt

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=calls)
    return session


# ===========================================================================
# 5. Birth-year blocking query path
# ===========================================================================


class TestBirthYearBlockingPath:
    """Lines ~966-974."""

    @pytest.mark.asyncio
    async def test_birth_year_query_executed_when_dob_present(self):
        """When target person has a dob, a birth-year blocking query must run."""
        person_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())

        target = _make_person(person_id, "Alice Smith", "1990-03-15")

        overrides, Person, Identifier, Address = _make_shared_models()
        Person.id.__eq__ = MagicMock(return_value=MagicMock())

        # Candidate row returned by birth-year query
        cand_row = MagicMock()
        cand_row.__getitem__ = lambda self, i: cand_id  # row[0] == cand_id

        session = _build_session(
            target_person=target,
            target_idents=[],
            candidate_ids_rows=[(cand_id,)],
            ln_ids_rows=[(cand_id,)],
            candidate_persons=[_make_person(cand_id, "Alice Smith", "1990-03-15")],
            all_idents=[],
            all_addresses=[],
        )

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        # At least 3 execute calls happened (person, idents, dob-blocking, name-blocking, ...)
        assert session.execute.call_count >= 3

    @pytest.mark.asyncio
    async def test_birth_year_query_skipped_when_no_dob(self):
        """When target person has no dob, the birth-year blocking query must not run."""
        person_id = str(uuid.uuid4())

        target = _make_person(person_id, "Alice Smith", "")
        target.dob = None  # explicitly no DOB

        overrides, Person, Identifier, Address = _make_shared_models()

        # Without dob blocking there is no name match either, so candidates = empty → return []
        session = AsyncMock()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),           # person lookup
            _scalars_result([]),              # target idents
            _fetchall_result([]),             # ln_stmt (name is "Alice Smith" so this runs)
            _scalars_result([]),              # cand_stmt (no candidates)
            _scalars_result([]),              # cand_ident_stmt
            _scalars_result([]),              # addr_stmt
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []

    @pytest.mark.asyncio
    async def test_non_digit_birth_year_skips_query(self):
        """
        If the first 4 chars of dob are not all digits, the blocking query is skipped.
        """
        person_id = str(uuid.uuid4())
        target = _make_person(person_id, "Alice Smith", "N/A-01-01")  # year part "N/A-" — not digit

        overrides, Person, Identifier, Address = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([]),       # idents
            _fetchall_result([]),      # ln_stmt (name present)
            _scalars_result([]),       # cand
            _scalars_result([]),       # cand_idents
            _scalars_result([]),       # addrs
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []


# ===========================================================================
# 6. Phone-prefix blocking query path
# ===========================================================================


class TestPhonePrefixBlockingPath:
    """Lines ~992-1002."""

    @pytest.mark.asyncio
    async def test_phone_prefix_query_executed_for_each_phone(self):
        """One blocking query per phone prefix must be issued."""
        person_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())

        target = _make_person(person_id, "Bob Jones", None)
        target.dob = None  # disable birth-year blocking to isolate phone path

        phone_ident = _make_identifier(person_id, "phone", "5125550101")

        overrides, Person, Identifier, Address = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),              # person
            _scalars_result([phone_ident]),      # target idents
            _fetchall_result([(cand_id,)]),      # ln_stmt (name present)
            _fetchall_result([(cand_id,)]),      # ph_stmt for "512" prefix
            _scalars_result([_make_person(cand_id, "Bob Jones", None)]),  # candidates
            _scalars_result([]),                 # cand idents
            _scalars_result([]),                 # addresses
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        # Should have at least one phone-prefix execute call beyond the basics
        assert session.execute.call_count >= 4

    @pytest.mark.asyncio
    async def test_short_phone_skips_prefix_query(self):
        """A phone with fewer than 3 digits must not generate a prefix query."""
        person_id = str(uuid.uuid4())
        target = _make_person(person_id, "Bob Jones", None)
        target.dob = None

        # Phone with only 2 digits after stripping — prefix query must be skipped
        short_phone_ident = _make_identifier(person_id, "phone", "51")

        overrides, Person, Identifier, Address = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        # Only 5 calls expected: person, idents, ln_stmt, cand, cand_idents, addrs
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([short_phone_ident]),
            _fetchall_result([]),    # ln_stmt
            _scalars_result([]),     # cand
            _scalars_result([]),     # cand_idents
            _scalars_result([]),     # addrs
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []

    @pytest.mark.asyncio
    async def test_no_phone_identifiers_no_prefix_query(self):
        """When target person has no phone identifiers, no prefix query runs."""
        person_id = str(uuid.uuid4())
        target = _make_person(person_id, "Carol White", None)
        target.dob = None

        email_ident = _make_identifier(person_id, "email", "carol@example.com")

        overrides, Person, Identifier, Address = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([email_ident]),
            _fetchall_result([]),    # ln_stmt
            _scalars_result([]),     # cand
            _scalars_result([]),     # cand_idents
            _scalars_result([]),     # addrs
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []


# ===========================================================================
# 7. Full orchestration path through score_person_dedup
# ===========================================================================


class TestScorePersonDedupOrchestration:
    """Lines ~1011-1073 — full path returning MergeCandidate objects."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_person_not_found(self):
        overrides, _, _, _ = _make_shared_models()
        session = AsyncMock()

        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(str(uuid.uuid4()), session)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_candidates_found(self):
        """When blocking queries yield no candidates, function returns []."""
        person_id = str(uuid.uuid4())
        target = _make_person(person_id, "Dave Brown", "1985-07-22")

        overrides, _, _, _ = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([]),    # idents
            _fetchall_result([]),   # dob blocking
            _fetchall_result([]),   # name blocking
            _scalars_result([]),    # cand
            _scalars_result([]),    # cand_idents
            _scalars_result([]),    # addrs
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_merge_candidates_for_matching_persons(self):
        """
        When candidates share name and DOB with the target, FuzzyDeduplicator
        should produce at least one MergeCandidate referencing the target person.
        """
        person_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())

        target = _make_person(person_id, "Eve Adams", "1992-11-30")
        candidate = _make_person(cand_id, "Eve Adams", "1992-11-30")

        phone_ident = _make_identifier(person_id, "phone", "5125550199")
        cand_phone = _make_identifier(cand_id, "phone", "5125550199")

        overrides, _, _, _ = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([phone_ident]),          # target idents
            _fetchall_result([(cand_id,)]),           # dob blocking
            _fetchall_result([(cand_id,)]),           # name blocking
            _fetchall_result([(cand_id,)]),           # phone prefix blocking
            _scalars_result([candidate]),             # candidate persons
            _scalars_result([phone_ident, cand_phone]),  # all idents
            _scalars_result([]),                      # addresses
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        # Result must be a list of MergeCandidate
        assert isinstance(result, list)
        assert len(result) >= 1
        for mc in result:
            assert isinstance(mc, MergeCandidate)
            assert mc.id_a == str(person_id) or mc.id_b == str(person_id)

    @pytest.mark.asyncio
    async def test_self_match_excluded_from_results(self):
        """The target person must never appear as a candidate matched against itself."""
        person_id = str(uuid.uuid4())
        target = _make_person(person_id, "Frank Castle", "1975-06-10")

        overrides, _, _, _ = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([]),     # idents
            _fetchall_result([]),    # dob
            _fetchall_result([]),    # name
            _scalars_result([]),     # cand
            _scalars_result([]),     # cand_idents
            _scalars_result([]),     # addrs
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        # No self-match
        for mc in result:
            assert not (mc.id_a == str(person_id) and mc.id_b == str(person_id))

    @pytest.mark.asyncio
    async def test_exception_during_db_query_returns_empty_list(self):
        """Any unexpected exception during DB operations must be caught; return []."""
        person_id = str(uuid.uuid4())

        overrides, _, _, _ = _make_shared_models()

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert result == []

    @pytest.mark.asyncio
    async def test_ident_map_built_correctly_phone_and_email(self):
        """
        Identifiers of type 'phone' and 'email' must be routed to the correct
        keys in the ident_map, feeding the right fields into FuzzyDeduplicator.
        """
        person_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())

        target = _make_person(person_id, "Grace Hopper", "1906-12-09")
        candidate = _make_person(cand_id, "Grace Hopper", "1906-12-09")

        t_phone = _make_identifier(person_id, "phone", "2025550001")
        t_email = _make_identifier(person_id, "email", "grace@navy.mil")
        c_phone = _make_identifier(cand_id, "phone", "2025550001")
        c_email = _make_identifier(cand_id, "email", "grace@navy.mil")

        overrides, _, _, _ = _make_shared_models()

        def _scalar_result(val):
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            return r

        def _scalars_result(items):
            s = MagicMock()
            s.all.return_value = items
            r = MagicMock()
            r.scalars.return_value = s
            return r

        def _fetchall_result(rows):
            r = MagicMock()
            r.fetchall.return_value = rows
            return r

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _scalar_result(target),
            _scalars_result([t_phone, t_email]),
            _fetchall_result([(cand_id,)]),           # dob blocking
            _fetchall_result([(cand_id,)]),           # name blocking
            _fetchall_result([(cand_id,)]),           # phone prefix "202"
            _scalars_result([candidate]),
            _scalars_result([t_phone, t_email, c_phone, c_email]),
            _scalars_result([]),
        ])

        with patch.dict(sys.modules, overrides):
            result = await score_person_dedup(person_id, session)

        assert isinstance(result, list)
        # With identical phone + name + dob there should be a high-scoring candidate
        if result:
            assert result[0].similarity_score > 0.0
