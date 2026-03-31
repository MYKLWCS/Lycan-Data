"""
Biographical enrichment — extracts DOB, family structure, and life events
from heterogeneous text sources (social bios, people-search results, obituaries).
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# DOB extraction patterns
DOB_PATTERNS = [
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
    r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})\b",
    r"\bborn\s+(on\s+)?([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b",
    r"\bDOB:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b",
    r"\bage\s+(\d{2})\b",  # "age 34" → approximate DOB
    r"\b(\d{4})-(\d{2})-(\d{2})\b",  # ISO date
]

MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


@dataclass
class BiographicalProfile:
    dob: date | None = None
    dob_confidence: float = 0.0
    dob_sources: list[str] = field(default_factory=list)
    age_estimated: int | None = None

    # Family
    marital_status: str | None = None  # "married", "single", "divorced", "widowed"
    children_count: int | None = None
    parent_father_name: str | None = None
    parent_mother_name: str | None = None
    parent_father_deceased: bool | None = None
    parent_mother_deceased: bool | None = None
    siblings: list[str] = field(default_factory=list)
    spouse_name: str | None = None

    # Life events (list of {event, date, detail})
    life_events: list[dict] = field(default_factory=list)


def extract_dob(
    texts: list[str], sources: list[str] | None = None
) -> tuple[date | None, float, list[str]]:
    """
    Extract DOB from multiple text sources. Returns (dob, confidence, matched_sources).
    Higher confidence if multiple sources agree.
    """
    candidates: list[tuple[date, str]] = []

    for i, text in enumerate(texts):
        source = (sources or [])[i] if sources and i < len(sources) else f"source_{i}"
        dob = _extract_single_dob(text)
        if dob:
            candidates.append((dob, source))

    if not candidates:
        return None, 0.0, []

    # Find the most common date
    date_counts = Counter(d for d, _ in candidates)
    best_date, count = date_counts.most_common(1)[0]
    matched_sources = [s for d, s in candidates if d == best_date]

    # Confidence: 0.4 per unique source, capped at 1.0
    confidence = min(1.0, count * 0.40)

    return best_date, confidence, matched_sources


def _extract_single_dob(text: str) -> date | None:
    """Try each pattern, return first valid date found."""
    text_lower = text.lower()

    # ISO date
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        dob = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dob:
            return dob

    # "Month DD, YYYY"
    m = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+(\d{1,2}),?\s+(\d{4})\b",
        text_lower,
    )
    if m:
        dob = _safe_date(int(m.group(3)), MONTH_MAP[m.group(1)], int(m.group(2)))
        if dob:
            return dob

    # MM/DD/YYYY or MM-DD-YYYY
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", text)
    if m:
        dob = _safe_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if dob:
            return dob

    # "DOB: MM/DD/YY"
    m = re.search(r"dob:?\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})\b", text_lower)
    if m:
        year = int(m.group(3))
        year = year + 1900 if year > 30 else year + 2000
        dob = _safe_date(year, int(m.group(1)), int(m.group(2)))
        if dob:
            return dob

    return None


def extract_marital_status(texts: list[str]) -> str | None:
    """Detect marital status from text."""
    married_kw = [
        "married",
        "wife",
        "husband",
        "spouse",
        "wed",
        "wedding",
        "anniversary",
        "mrs.",
        "mr. & mrs.",
    ]
    divorced_kw = ["divorced", "divorce", "ex-wife", "ex-husband", "separated"]
    widowed_kw = [
        "widowed",
        "widow",
        "widower",
        "late wife",
        "late husband",
        "passed away",
        "in memory of my",
    ]

    combined = " ".join(texts).lower()

    if any(kw in combined for kw in widowed_kw):
        return "widowed"
    if any(kw in combined for kw in divorced_kw):
        return "divorced"
    if any(kw in combined for kw in married_kw):
        return "married"
    return None


def extract_children(texts: list[str]) -> int | None:
    """Estimate number of children from text references."""
    combined = " ".join(texts).lower()

    # "father/mother of 3", "3 kids", "3 children"
    m = re.search(r"\b(\d)\s+(?:kids?|children|sons?|daughters?)\b", combined)
    if m:
        return int(m.group(1))

    # Count possessive child references "my son John, my daughter Mary"
    son_count = len(re.findall(r"\bmy son\b", combined))
    daughter_count = len(re.findall(r"\bmy daughter\b", combined))
    if son_count + daughter_count > 0:
        return son_count + daughter_count

    if any(
        kw in combined for kw in ["my kids", "my children", "being a parent", "mom of", "dad of"]
    ):
        return -1  # unknown count but has children

    return None


def extract_parent_status(texts: list[str]) -> dict[str, Any]:
    """Detect if parents are mentioned as deceased."""
    combined = " ".join(texts).lower()

    result: dict[str, Any] = {
        "father_deceased": None,
        "mother_deceased": None,
        "father_name": None,
        "mother_name": None,
    }

    # Deceased signals
    deceased_kw = [
        "passed away",
        "rest in peace",
        "rip",
        "in loving memory",
        "gone too soon",
        "we lost",
        "miss you every day",
        "until we meet again",
        "heaven",
        "watching over",
    ]

    father_kw = ["dad", "father", "papa", "pop"]
    mother_kw = ["mom", "mother", "mama", "mum"]

    has_deceased_signal = any(kw in combined for kw in deceased_kw)

    if has_deceased_signal:
        # Check proximity to father/mother keywords
        for kw in father_kw:
            pattern = rf"({'|'.join(deceased_kw)})[^.]*{kw}|{kw}[^.]*({'|'.join(deceased_kw)})"
            if re.search(pattern, combined):
                result["father_deceased"] = True
                break

        for kw in mother_kw:
            pattern = rf"({'|'.join(deceased_kw)})[^.]*{kw}|{kw}[^.]*({'|'.join(deceased_kw)})"
            if re.search(pattern, combined):
                result["mother_deceased"] = True
                break

    return result


def build_biographical_profile(
    texts: list[str],
    sources: list[str] | None = None,
    people_search_data: dict | None = None,
) -> BiographicalProfile:
    """Aggregate all biographical signals into a profile."""
    profile = BiographicalProfile()

    profile.dob, profile.dob_confidence, profile.dob_sources = extract_dob(texts, sources)
    profile.marital_status = extract_marital_status(texts)
    children = extract_children(texts)
    if children is not None:
        profile.children_count = None if children == -1 else children

    parent_status = extract_parent_status(texts)
    profile.parent_father_deceased = parent_status["father_deceased"]
    profile.parent_mother_deceased = parent_status["mother_deceased"]

    # From people search structured data
    if people_search_data:
        relatives = people_search_data.get("relatives", [])
        # Heuristic: older relatives with matching last name = parents
        profile.siblings = [r for r in relatives if isinstance(r, str)]

    return profile
