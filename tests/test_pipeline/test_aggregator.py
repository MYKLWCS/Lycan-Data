"""
Tests for modules/pipeline/aggregator.py

12 tests covering the main entry-point and every sub-handler.
All DB interaction is mocked — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.crawlers.core.result import CrawlerResult
from modules.pipeline.aggregator import (
    _get_or_create_person,
    _handle_behavioural,
    _handle_breach_data,
    _handle_court_records,
    _handle_darkweb,
    _handle_people_search,
    _handle_watchlist,
    _upsert_social_profile,
    aggregate_result,
)
from shared.models.address import Address
from shared.models.alert import Alert
from shared.models.behavioural import BehaviouralProfile
from shared.models.breach import BreachRecord
from shared.models.darkweb import DarkwebMention
from shared.models.person import Person
from shared.models.social_profile import SocialProfile
from shared.models.watchlist import WatchlistMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session() -> AsyncMock:
    """Return a mock AsyncSession with sensible defaults."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    scalar_result.scalar.return_value = None
    session.execute.return_value = scalar_result

    # session.get() returns None by default (no existing record)
    session.get = AsyncMock(return_value=None)
    return session


def _make_result(**kwargs) -> CrawlerResult:
    defaults = {
        "platform": "instagram",
        "identifier": "testuser",
        "found": True,
        "data": {"handle": "testuser", "bio": "Hello"},
        "source_reliability": 0.55,
    }
    defaults.update(kwargs)
    return CrawlerResult(**defaults)


# ---------------------------------------------------------------------------
# 1. aggregate_result returns early when result.found is False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aggregate_result_not_found_returns_early():
    session = _mock_session()
    result = _make_result(found=False, data={})
    out = await aggregate_result(session, result)
    assert out == {"written": False, "reason": "no data"}
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 2. aggregate_result returns early when result.data is empty
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aggregate_result_empty_data_returns_early():
    session = _mock_session()
    result = _make_result(found=True, data={})
    out = await aggregate_result(session, result)
    assert out == {"written": False, "reason": "no data"}


# ---------------------------------------------------------------------------
# 3. aggregate_result creates a Person and commits for a social platform
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aggregate_result_social_creates_person_and_commits():
    session = _mock_session()
    result = _make_result(platform="instagram", data={"handle": "alice"})

    out = await aggregate_result(session, result)

    assert "person_id" in out
    assert "social_profile" in out
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. aggregate_result passes person_id through when provided
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aggregate_result_uses_provided_person_id():
    person_id = uuid.uuid4()
    person = Person(id=person_id, full_name="Bob")

    session = _mock_session()
    session.get.return_value = person

    result = _make_result(platform="twitter", data={"handle": "bob"})
    out = await aggregate_result(session, result, person_id=str(person_id))

    assert out["person_id"] == str(person_id)


# ---------------------------------------------------------------------------
# 5. _get_or_create_person creates new Person when nothing found
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_or_create_person_creates_new():
    session = _mock_session()
    result = _make_result(data={"display_name": "NewPerson"})

    person = await _get_or_create_person(session, None, result)

    assert isinstance(person, Person)
    assert person.full_name == "NewPerson"
    session.add.assert_called_once_with(person)
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# 6. _upsert_social_profile inserts a new SocialProfile
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_social_profile_inserts_new():
    session = _mock_session()
    result = _make_result(
        platform="reddit",
        identifier="redditor",
        data={"handle": "redditor", "bio": "test bio", "follower_count": 100},
    )
    person_id = uuid.uuid4()

    profile = await _upsert_social_profile(session, result, person_id)

    assert isinstance(profile, SocialProfile)
    assert profile.handle == "redditor"
    assert profile.platform == "reddit"
    assert profile.person_id == person_id
    session.add.assert_called_once()


# ---------------------------------------------------------------------------
# 7. _upsert_social_profile updates existing SocialProfile
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_social_profile_updates_existing():
    existing = SocialProfile(
        id=uuid.uuid4(),
        platform="reddit",
        handle="redditor",
        follower_count=50,
    )
    session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = mock_result

    result = _make_result(
        platform="reddit",
        identifier="redditor",
        data={"handle": "redditor", "follower_count": 200},
    )

    profile = await _upsert_social_profile(session, result, uuid.uuid4())

    assert profile is existing
    assert profile.follower_count == 200
    # No new add() call — we updated in-place
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# 8. _handle_breach_data writes BreachRecord rows for HIBP-style breaches
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_breach_data_hibp_style():
    session = _mock_session()
    result = _make_result(
        platform="email_hibp",
        identifier="test@example.com",
        data={
            "breaches": [
                {"name": "Adobe", "date": "2013-10-04", "data_classes": ["email", "password"]},
                {"name": "LinkedIn", "date": "2012-05-05", "data_classes": ["email"]},
            ]
        },
    )

    count = await _handle_breach_data(session, result, uuid.uuid4())

    assert count == 2
    assert session.add.call_count == 2
    # Verify the objects added are BreachRecords
    for c in session.add.call_args_list:
        assert isinstance(c.args[0], BreachRecord)


# ---------------------------------------------------------------------------
# 9. _handle_breach_data handles Holehe-style found_on lists
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_breach_data_holehe_style():
    session = _mock_session()
    result = _make_result(
        platform="email_holehe",
        identifier="test@example.com",
        data={"found_on": ["spotify", "netflix", "github"]},
    )

    count = await _handle_breach_data(session, result, uuid.uuid4())

    assert count == 3
    records = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(r, BreachRecord) for r in records)
    names = [r.breach_name for r in records]
    assert "spotify" in names


# ---------------------------------------------------------------------------
# 10. _handle_watchlist writes WatchlistMatch and Alert for each match
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_watchlist_writes_match_and_alert():
    session = _mock_session()
    result = _make_result(
        platform="sanctions_ofac",
        identifier="John Doe",
        data={
            "matches": [
                {"name": "JOHN DOE", "score": 0.95},
            ]
        },
    )

    count = await _handle_watchlist(session, result, uuid.uuid4())

    assert count == 1
    added = [c.args[0] for c in session.add.call_args_list]
    types = {type(a).__name__ for a in added}
    assert "WatchlistMatch" in types
    assert "Alert" in types

    wm = next(a for a in added if isinstance(a, WatchlistMatch))
    assert wm.list_name == "OFAC"
    assert wm.match_score == 0.95


# ---------------------------------------------------------------------------
# 11. _handle_darkweb writes DarkwebMention and Alert (capped at 10)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_darkweb_caps_at_10_mentions():
    session = _mock_session()
    mentions = [{"url": f"http://onion{i}.onion", "title": f"Hit {i}"} for i in range(15)]
    result = _make_result(
        platform="darkweb_ahmia",
        identifier="target@example.com",
        data={"mentions": mentions},
    )

    await _handle_darkweb(session, result, uuid.uuid4())

    added = [c.args[0] for c in session.add.call_args_list]
    mention_objects = [a for a in added if isinstance(a, DarkwebMention)]
    alert_objects = [a for a in added if isinstance(a, Alert)]

    # Cap at 10
    assert len(mention_objects) == 10
    assert len(alert_objects) == 10


# ---------------------------------------------------------------------------
# 12. _handle_people_search writes Address rows (max 3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_people_search_writes_addresses():
    session = _mock_session()
    result = _make_result(
        platform="whitepages",
        identifier="John Smith",
        data={
            "results": [
                {"address": "123 Main St", "city": "Dallas", "state": "TX"},
                {"address": "456 Oak Ave", "city": "Houston", "state": "TX"},
                {"address": "789 Pine Rd", "city": "Austin", "state": "TX"},
                {
                    "address": "999 Extra Ln",
                    "city": "Waco",
                    "state": "TX",
                },  # 4th — should be skipped
            ]
        },
    )

    await _handle_people_search(session, result, uuid.uuid4())

    added = [c.args[0] for c in session.add.call_args_list]
    addresses = [a for a in added if isinstance(a, Address)]
    assert len(addresses) >= 3  # New handler processes up to 5 results
    cities = [a.city for a in addresses]
    assert "Dallas" in cities


# ---------------------------------------------------------------------------
# Bonus: _handle_court_records raises alert with correct type
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_court_records_raises_alert():
    session = _mock_session()
    result = _make_result(
        platform="court_courtlistener",
        identifier="Jane Doe",
        data={"cases": [{"case_id": "1"}, {"case_id": "2"}]},
    )

    await _handle_court_records(session, result, uuid.uuid4())

    added = [c.args[0] for c in session.add.call_args_list]
    assert len(added) == 3  # 2 CriminalRecords + 1 Alert
    alert = next(a for a in added if isinstance(a, Alert))
    assert isinstance(alert, Alert)
    assert alert.alert_type == "criminal_signal"


# ---------------------------------------------------------------------------
# Bonus: _handle_behavioural creates BehaviouralProfile with correct scores
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handle_behavioural_creates_profile():
    session = _mock_session()
    result = _make_result(
        platform="social_posts_analyzer",
        identifier="@someone",
        data={
            "gambling_language": True,
            "financial_stress_language": False,
            "substance_language": True,
            "aggression_language": False,
        },
    )

    await _handle_behavioural(session, result, uuid.uuid4())

    added = [c.args[0] for c in session.add.call_args_list]
    assert len(added) == 1
    bp = added[0]
    assert isinstance(bp, BehaviouralProfile)
    assert bp.gambling_score == 1.0
    assert bp.financial_distress_score == 0.0
    assert bp.drug_signal_score == 1.0
