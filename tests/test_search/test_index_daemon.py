"""Tests for modules/search/index_daemon.py — mocking event_bus, DB, and meili."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.search.index_daemon import IndexDaemon

# ─── Lifecycle ────────────────────────────────────────────────────────────────


def test_index_daemon_init():
    d = IndexDaemon(worker_id="test-indexer")
    assert d.worker_id == "test-indexer"
    assert d._running is False


@pytest.mark.asyncio
async def test_index_daemon_stop():
    d = IndexDaemon()
    d._running = True
    await d.stop()
    assert d._running is False


# ─── _process_one — dequeue returns None ─────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_dequeue_none_returns_early():
    d = IndexDaemon()
    with patch("modules.search.index_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value=None)
        await d._process_one()
    mock_bus.dequeue.assert_called_once_with(priority="index", timeout=5)


# ─── _process_one — invalid JSON payload ─────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_invalid_json_logs_warning():
    d = IndexDaemon()
    with patch("modules.search.index_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value=b"not-valid-json{{{")
        with patch("modules.search.index_daemon.logger") as mock_log:
            await d._process_one()
    mock_log.warning.assert_called_once()


# ─── _process_one — missing person_id ────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_missing_person_id_returns_early():
    d = IndexDaemon()
    with patch("modules.search.index_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value={"no_person_id": True})
        with patch.object(d, "_index_person") as mock_index:
            await d._process_one()
    mock_index.assert_not_called()


# ─── _process_one — invalid UUID ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_invalid_uuid_logs_warning():
    d = IndexDaemon()
    with patch("modules.search.index_daemon.event_bus") as mock_bus:
        mock_bus.dequeue = AsyncMock(return_value={"person_id": "not-a-uuid"})
        with patch("modules.search.index_daemon.logger") as mock_log:
            await d._process_one()
    mock_log.warning.assert_called_once()


# ─── _process_one — dict payload dispatches to _index_person ─────────────────


@pytest.mark.asyncio
async def test_process_one_valid_dict_payload():
    d = IndexDaemon()
    pid = str(uuid.uuid4())

    with (
        patch("modules.search.index_daemon.event_bus") as mock_bus,
        patch("modules.search.index_daemon.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_bus.dequeue = AsyncMock(return_value={"person_id": pid})

        # Set up async context manager
        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(d, "_index_person", new_callable=AsyncMock) as mock_index:
            await d._process_one()

    mock_index.assert_called_once()
    assert mock_index.call_args.args[1] == uuid.UUID(pid)


# ─── _process_one — JSON string payload ──────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_json_string_payload():
    import json

    d = IndexDaemon()
    pid = str(uuid.uuid4())
    payload_str = json.dumps({"person_id": pid})

    with (
        patch("modules.search.index_daemon.event_bus") as mock_bus,
        patch("modules.search.index_daemon.AsyncSessionLocal") as mock_session_cls,
    ):
        mock_bus.dequeue = AsyncMock(return_value=payload_str)

        mock_session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch.object(d, "_index_person", new_callable=AsyncMock) as mock_index:
            await d._process_one()

    mock_index.assert_called_once()


# ─── _index_person — person not found ────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_person_not_found_logs_warning():
    d = IndexDaemon()
    uid = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    with patch("modules.search.index_daemon.logger") as mock_log:
        await d._index_person(mock_session, uid)

    mock_log.warning.assert_called_once()
    assert str(uid) in mock_log.warning.call_args.args[0]


# ─── _index_person — successful indexing ─────────────────────────────────────


@pytest.mark.asyncio
async def test_index_person_successful():
    d = IndexDaemon()
    uid = uuid.uuid4()

    # Build a minimal Person mock
    person = MagicMock()
    person.id = uid
    person.full_name = "Alice Smith"
    person.date_of_birth = None
    person.nationality = "US"
    person.default_risk_score = 0.1
    person.darkweb_exposure = 0.0
    person.verification_status = "verified"
    person.composite_quality = 0.9
    person.corroboration_count = 5
    person.created_at = None

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=person)

    # execute() returns scalars().all()
    def _make_scalars(rows):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
        return result

    mock_session.execute = AsyncMock(
        side_effect=[
            _make_scalars([]),  # identifiers
            _make_scalars([]),  # addresses
            _make_scalars([]),  # social profiles
        ]
    )

    with patch(
        "modules.search.typesense_indexer.meili_indexer.index_person",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_meili:
        await d._index_person(mock_session, uid)

    mock_meili.assert_called_once()


@pytest.mark.asyncio
async def test_index_person_meili_failure_logs_error():
    d = IndexDaemon()
    uid = uuid.uuid4()

    person = MagicMock()
    person.id = uid
    person.full_name = "Bob Jones"
    person.date_of_birth = None
    person.nationality = None
    person.default_risk_score = 0.85
    person.darkweb_exposure = 0.5
    person.verification_status = "pending"
    person.composite_quality = 0.5
    person.corroboration_count = 1
    person.created_at = None

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=person)

    def _make_scalars(rows):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = rows
        result.scalars.return_value = scalars
        return result

    mock_session.execute = AsyncMock(
        side_effect=[
            _make_scalars([]),
            _make_scalars([]),
            _make_scalars([]),
        ]
    )

    with (
        patch(
            "modules.search.typesense_indexer.meili_indexer.index_person",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("modules.search.index_daemon.logger") as mock_log,
    ):
        await d._index_person(mock_session, uid)

    mock_log.error.assert_called_once()


# ─── Risk tier mapping ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_person_risk_tiers():
    """Verify that various risk scores map to the correct risk_tier labels."""
    from modules.search.typesense_indexer import build_person_doc

    risk_cases = [
        (0.85, "do_not_lend"),
        (0.65, "high_risk"),
        (0.45, "medium_risk"),
        (0.25, "low_risk"),
        (0.05, "preferred"),
    ]

    for score_val, expected_tier in risk_cases:
        d = IndexDaemon()
        uid = uuid.uuid4()

        person = MagicMock()
        person.id = uid
        person.full_name = "Test User"
        person.date_of_birth = None
        person.nationality = None
        person.default_risk_score = score_val
        person.darkweb_exposure = 0.0
        person.verification_status = "verified"
        person.composite_quality = 0.5
        person.corroboration_count = 1
        person.created_at = None

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=person)

        def _make_scalars(rows):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = rows
            result.scalars.return_value = scalars
            return result

        mock_session.execute = AsyncMock(
            side_effect=[
                _make_scalars([]),
                _make_scalars([]),
                _make_scalars([]),
            ]
        )

        captured_doc = {}

        async def capture_doc(doc):
            captured_doc.update(doc)
            return True

        with patch(
            "modules.search.typesense_indexer.meili_indexer.index_person", side_effect=capture_doc
        ):
            await d._index_person(mock_session, uid)

        assert captured_doc.get("risk_tier") == expected_tier, (
            f"score {score_val} → expected {expected_tier}, got {captured_doc.get('risk_tier')}"
        )
