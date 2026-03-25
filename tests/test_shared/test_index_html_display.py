"""Tests confirming all score displays in static/index.html use 0-100 integers."""

import pathlib
import re

INDEX_HTML = pathlib.Path("static/index.html").read_text()


def test_risk_dial_renders_integer():
    """drawRiskDial renders Math.round(pct*100) — already done, must stay."""
    assert "Math.round(pct*100)" in INDEX_HTML, "drawRiskDial should output Math.round(pct*100)"


def test_no_raw_score_toFixed():
    """No raw .toFixed() calls directly on 0-1 score variable names."""
    # Timing values (duration_ms.toFixed(1)+'ms') are fine — only score variables matter.
    score_vars = re.compile(
        r"(?:risk_score|match_score|confidence|quality|reliability|corroboration)"
        r"[^;]*\.toFixed\(\d\)"
    )
    assert not score_vars.search(INDEX_HTML), (
        "Found .toFixed() on a score variable — must use Math.round(*100)"
    )


def test_identifier_confidence_displayed_as_integer():
    """Identifier confidence shown as Math.round((i.confidence||0)*100)+'%'."""
    assert "Math.round((i.confidence||0)*100)+'%'" in INDEX_HTML, (
        "Identifier confidence must render as integer percent"
    )


def test_composite_quality_displayed_as_integer():
    """composite_quality badge uses relBadge which internally rounds to integer."""
    # relBadge function: const pct = Math.round((score || 0) * 100);
    assert "Math.round((score || 0) * 100)" in INDEX_HTML, (
        "relBadge should render score as integer percent"
    )


def test_similarity_score_displayed_as_integer():
    """Dedup similarity scores shown as Math.round(...*100)."""
    assert (
        "Math.round(c.similarity_score * 100)" in INDEX_HTML
        or "Math.round((c.similarity_score||0)*100)" in INDEX_HTML
    ), "Similarity score must render as integer percent"


def test_financial_aml_score_displayed_as_integer():
    """AML match score displayed as Math.round((w.match_score||0)*100)+'%'."""
    # The watchlist alert section already uses Math.round((w.match_score||0)*100)
    # in the alert display. Both variations are acceptable.
    assert (
        "Math.round((w.match_score||0)*100)" in INDEX_HTML
        or "Math.round((m.match_score||0)*100)" in INDEX_HTML
    ), "AML match score must render as integer percent"
