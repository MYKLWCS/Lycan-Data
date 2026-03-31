from datetime import UTC, datetime, timedelta, timezone

import pytest

from shared.freshness import compute_freshness, get_half_life, hours_until_stale, is_stale


def test_freshness_just_scraped():
    """Freshly scraped data should be near 1.0."""
    now = datetime.now(UTC)
    score = compute_freshness(now, "social_media_profile")
    assert score >= 0.99


def test_freshness_none_returns_zero():
    assert compute_freshness(None) == 0.0


def test_freshness_decays_over_time():
    """After one half-life, freshness should be ~0.5."""
    half_life = get_half_life("social_media_profile")  # 168 hours
    scraped = datetime.now(UTC) - timedelta(hours=half_life)
    score = compute_freshness(scraped, "social_media_profile")
    assert 0.48 <= score <= 0.52  # allow small floating point variance


def test_freshness_sanctions_decays_fast():
    """Sanctions have a 6-hour half-life — stale quickly."""
    scraped = datetime.now(UTC) - timedelta(hours=12)
    score = compute_freshness(scraped, "sanctions")
    assert score < 0.30  # two half-lives = 0.25


def test_is_stale_true():
    scraped = datetime.now(UTC) - timedelta(days=30)
    assert is_stale(scraped, "social_media_profile") is True


def test_is_stale_false():
    scraped = datetime.now(UTC) - timedelta(hours=1)
    assert is_stale(scraped, "social_media_profile") is False


def test_hours_until_stale_positive():
    scraped = datetime.now(UTC) - timedelta(hours=1)
    remaining = hours_until_stale(scraped, "social_media_profile")
    assert remaining > 0


def test_hours_until_stale_zero_when_already_stale():
    scraped = datetime.now(UTC) - timedelta(days=30)
    remaining = hours_until_stale(scraped, "social_media_profile")
    assert remaining == 0.0
