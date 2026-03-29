"""
test_linkedin_coverage.py — Targeted coverage for linkedin.py lines 101-110, 130-136, 145.

Lines targeted:
- 101-110: endorsement count aggregation loop inside _extract()
- 130-136: education items loop — querying school/degree/field/dates sub-elements
- 145:     data["education"] = education_items  (only set when list is non-empty)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.linkedin import LinkedInCrawler
from modules.crawlers.core.result import CrawlerResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crawler() -> LinkedInCrawler:
    return LinkedInCrawler()


def _make_page(
    *,
    url: str = "https://www.linkedin.com/in/testuser/",
    title: str = "Test User | LinkedIn",
    content: str = "<html></html>",
    headline_text: str | None = None,
    location_text: str | None = None,
    connections_text: str | None = None,
    skill_texts: list[str] | None = None,
    endorsement_texts: list[str] | None = None,
    post_count_text: str | None = None,
    edu_items: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Playwright page with configurable return values."""
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.content = AsyncMock(return_value=content)

    async def _qs(selector):
        mapping = {
            ".top-card-layout__headline": _text_el(headline_text),
            ".top-card__subline-item": _text_el(location_text),
            ".top-card__connections-count": _text_el(connections_text),
            ".pv-recent-activity-section__headline-text": None,
            "[data-test-id='post-count']": _text_el(post_count_text) if post_count_text else None,
        }
        return mapping.get(selector)

    async def _qsa(selector):
        # Check most-specific first — endorsement selector also contains "skill"
        if "endorsement" in selector:
            return [_text_el(t) for t in (endorsement_texts or [])]
        if "skill" in selector:
            return [_text_el(t) for t in (skill_texts or [])]
        if "education" in selector or "edu" in selector.lower():
            return _build_edu_els(edu_items or [])
        return []

    page.query_selector = AsyncMock(side_effect=_qs)
    page.query_selector_all = AsyncMock(side_effect=_qsa)
    return page


def _text_el(text: str | None) -> MagicMock | None:
    if text is None:
        return None
    el = MagicMock()
    el.inner_text = AsyncMock(return_value=text)
    return el


def _build_edu_els(edu_items: list[dict]) -> list[MagicMock]:
    """Build mock education entity elements with nested sub-element queries."""
    els = []
    for item in edu_items:
        edu_el = MagicMock()

        async def _sub_qs(selector, _item=item):
            key_map = {
                ".pv-entity__school-name": "school",
                "h3.pv-entity__school-name": "school",
                ".pv-entity__degree-name span:nth-child(2)": "degree",
                ".pv-entity__fos span:nth-child(2)": "field",
                ".pv-entity__dates span:nth-child(2)": "dates",
            }
            for sel_fragment, data_key in key_map.items():
                if sel_fragment in selector:
                    val = _item.get(data_key)
                    return _text_el(val) if val is not None else None
            return None

        edu_el.query_selector = AsyncMock(side_effect=_sub_qs)
        els.append(edu_el)
    return els


# ---------------------------------------------------------------------------
# Lines 101-110: endorsement count aggregation
# ---------------------------------------------------------------------------


async def test_extract_endorsement_count_sums_correctly():
    """Lines 101-110: endorsement elements are parsed and summed into endorsement_count."""
    crawler = _crawler()
    page = _make_page(
        title="Wolf Developer | LinkedIn",
        endorsement_texts=["42", "18", "5"],
    )
    data = await crawler._extract(page, "wolf-dev")
    assert data.get("endorsement_count") == 65


async def test_extract_endorsement_count_ignores_invalid_text():
    """Lines 108-109: ValueError on int() is caught and that element contributes 0."""
    crawler = _crawler()
    page = _make_page(
        title="Edge Case | LinkedIn",
        endorsement_texts=["10", "not-a-number", "7"],
    )
    data = await crawler._extract(page, "edgecase")
    # "10" + 0 (skipped) + "7" = 17
    assert data.get("endorsement_count") == 17


async def test_extract_endorsement_count_with_plus_suffix():
    """Lines 105: '+' suffix stripped before int() conversion."""
    crawler = _crawler()
    page = _make_page(
        title="Plus User | LinkedIn",
        endorsement_texts=["99+", "50+"],
    )
    data = await crawler._extract(page, "plususer")
    assert data.get("endorsement_count") == 149


async def test_extract_endorsement_count_with_comma_thousands():
    """Lines 105: commas stripped, e.g. '1,234' → 1234."""
    crawler = _crawler()
    page = _make_page(
        title="Big Endorser | LinkedIn",
        endorsement_texts=["1,234"],
    )
    data = await crawler._extract(page, "bigendorser")
    assert data.get("endorsement_count") == 1234


async def test_extract_no_endorsement_elements_skips_key():
    """Lines 100-110: when endorsement_els is empty, endorsement_count is not set."""
    crawler = _crawler()
    page = _make_page(
        title="No Endorsements | LinkedIn",
        endorsement_texts=[],
    )
    data = await crawler._extract(page, "noemp")
    assert "endorsement_count" not in data


async def test_extract_endorsement_zero_total():
    """All elements have non-numeric text → total stays 0, key still set."""
    crawler = _crawler()
    page = _make_page(
        title="Zero User | LinkedIn",
        endorsement_texts=["abc", "xyz"],
    )
    data = await crawler._extract(page, "zero")
    assert data.get("endorsement_count") == 0


# ---------------------------------------------------------------------------
# Lines 130-136: education sub-element queries inside the edu loop
# ---------------------------------------------------------------------------


async def test_extract_education_all_fields_present():
    """Lines 129-143: each education entity has all four sub-elements populated."""
    crawler = _crawler()
    edu = [
        {
            "school": "MIT",
            "degree": "Bachelor of Science",
            "field": "Computer Science",
            "dates": "2010 – 2014",
        }
    ]
    page = _make_page(
        title="Grad | LinkedIn",
        edu_items=edu,
    )
    data = await crawler._extract(page, "grad")
    assert "education" in data
    assert len(data["education"]) == 1
    entry = data["education"][0]
    assert entry["school"] == "MIT"
    assert entry["degree"] == "Bachelor of Science"
    assert entry["field"] == "Computer Science"
    assert entry["dates"] == "2010 – 2014"


async def test_extract_education_partial_fields():
    """Lines 130-135: sub-elements that return None produce empty strings."""
    crawler = _crawler()
    edu = [{"school": "Harvard", "degree": None, "field": None, "dates": None}]
    page = _make_page(
        title="Partial Edu | LinkedIn",
        edu_items=edu,
    )
    data = await crawler._extract(page, "partial-edu")
    assert "education" in data
    entry = data["education"][0]
    assert entry["school"] == "Harvard"
    assert entry["degree"] == ""
    assert entry["field"] == ""
    assert entry["dates"] == ""


async def test_extract_education_multiple_entries_limited_to_five():
    """Lines 129: slice [:5] caps the edu loop at five items."""
    crawler = _crawler()
    edu = [
        {"school": f"School {i}", "degree": "BA", "field": "Arts", "dates": ""} for i in range(8)
    ]
    page = _make_page(
        title="Many Schools | LinkedIn",
        edu_items=edu,
    )
    data = await crawler._extract(page, "manyschools")
    # _extract loops over edu_els[:5]
    assert len(data.get("education", [])) == 5


# ---------------------------------------------------------------------------
# Line 145: data["education"] only set when education_items is non-empty
# ---------------------------------------------------------------------------


async def test_extract_education_key_set_when_items_found():
    """Line 145: education key is written to data dict when list is non-empty."""
    crawler = _crawler()
    edu = [{"school": "Oxford", "degree": "DPhil", "field": "Physics", "dates": "2015 – 2018"}]
    page = _make_page(
        title="Oxford Grad | LinkedIn",
        edu_items=edu,
    )
    data = await crawler._extract(page, "oxford-grad")
    assert "education" in data


async def test_extract_education_key_absent_when_no_items():
    """Line 145 guard: when edu_els is empty, education is never added to data."""
    crawler = _crawler()
    page = _make_page(
        title="No Edu | LinkedIn",
        edu_items=[],
    )
    data = await crawler._extract(page, "no-edu")
    assert "education" not in data
