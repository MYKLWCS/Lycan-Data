"""Shared utility functions for crawler modules.

Consolidates common helpers that were previously duplicated across
multiple crawler files. No external dependencies required.
"""

import os
import time


def cache_valid(path: str, max_age_hours: float = 24.0) -> bool:
    """Check whether a file cache is still fresh.

    Args:
        path: Filesystem path to the cached file.
        max_age_hours: Maximum age in hours before the cache is stale.

    Returns:
        True if the file exists and is younger than *max_age_hours*.
    """
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < max_age_hours


def word_overlap(query: str, candidate: str) -> float:
    """Return the fraction of query words found in candidate.

    Both strings are lowercased and split on whitespace before comparison.

    Args:
        query: The reference string whose words we want to match.
        candidate: The string to search within.

    Returns:
        A float between 0.0 and 1.0 representing overlap ratio.
    """
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & c_words) / len(q_words)


def split_name(identifier: str) -> tuple[str, str]:
    """Split a full name into (first, last) components.

    For two or more words, returns the first word and the last word.
    For a single word, returns (name, "").

    Args:
        identifier: A name string such as "John Doe" or "Jane".

    Returns:
        A tuple of (first_name, last_name).
    """
    parts = identifier.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return identifier.strip(), ""
