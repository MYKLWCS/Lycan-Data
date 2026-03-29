"""
Freshness scoring — computes how fresh (recent) a scraped data point is.

Each source type has a half-life (in hours). Freshness decays from 1.0
toward 0.0 as time passes since last scrape. The decay is exponential:

    freshness(t) = 0.5 ^ (t / half_life)

where t is hours elapsed since last_scraped_at.
"""

import math
from datetime import timezone, datetime

from shared.constants import FRESHNESS_HALF_LIFE


def compute_freshness(last_scraped_at: datetime | None, source_type: str = "default") -> float:
    """
    Compute freshness score for a data point.

    Args:
        last_scraped_at: When the data was last scraped. None returns 0.0.
        source_type: Key into FRESHNESS_HALF_LIFE (e.g. 'social_media_post').

    Returns:
        float in [0.0, 1.0]. 1.0 = just scraped, 0.0 = never scraped.
    """
    if last_scraped_at is None:
        return 0.0

    half_life_hours = FRESHNESS_HALF_LIFE.get(source_type, FRESHNESS_HALF_LIFE["default"])
    now = datetime.now(timezone.utc)

    # Ensure last_scraped_at is timezone-aware
    if last_scraped_at.tzinfo is None:
        last_scraped_at = last_scraped_at.replace(tzinfo=timezone.utc)

    elapsed_hours = (now - last_scraped_at).total_seconds() / 3600.0
    elapsed_hours = max(0.0, elapsed_hours)

    freshness = math.pow(0.5, elapsed_hours / half_life_hours)
    return round(min(1.0, max(0.0, freshness)), 4)


def is_stale(
    last_scraped_at: datetime | None, source_type: str = "default", threshold: float = 0.40
) -> bool:
    """Return True if freshness is below threshold."""
    return compute_freshness(last_scraped_at, source_type) < threshold


def hours_until_stale(
    last_scraped_at: datetime | None, source_type: str = "default", threshold: float = 0.40
) -> float:
    """
    How many hours from now until freshness drops below threshold.
    Returns 0.0 if already stale.
    """
    if last_scraped_at is None:
        return 0.0

    half_life_hours = FRESHNESS_HALF_LIFE.get(source_type, FRESHNESS_HALF_LIFE["default"])
    now = datetime.now(timezone.utc)
    if last_scraped_at.tzinfo is None:
        last_scraped_at = last_scraped_at.replace(tzinfo=timezone.utc)

    elapsed_hours = (now - last_scraped_at).total_seconds() / 3600.0
    # Solve: 0.5^(t/half_life) = threshold => t = half_life * log2(1/threshold)
    stale_at_hours = half_life_hours * math.log2(1.0 / threshold)
    remaining = stale_at_hours - elapsed_hours
    return max(0.0, round(remaining, 2))


def get_half_life(source_type: str) -> float:
    """Return half-life in hours for a source type."""
    return FRESHNESS_HALF_LIFE.get(source_type, FRESHNESS_HALF_LIFE["default"])
