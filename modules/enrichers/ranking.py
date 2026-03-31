"""
Result Ranking & Sorting Engine.

Scores and sorts any list of result dicts by a composite of:
  - composite_quality (freshness × reliability × corroboration)
  - risk_relevance (how risk-relevant the result is for the query context)
  - source_authority (government > social > dark web)
  - recency (how recently scraped)

Every algorithm is auditable: scores are returned alongside results.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

AUTHORITY_WEIGHTS: dict[str, float] = {
    "government_registry": 1.00,
    "court_record": 0.95,
    "financial_record": 0.90,
    "company_registry": 0.85,
    "property_registry": 0.85,
    "npi": 0.90,
    "faa": 0.90,
    "nsopw": 0.90,
    "ofac": 0.95,
    "un_sanctions": 0.95,
    "fbi": 0.90,
    "linkedin": 0.75,
    "truecaller": 0.70,
    "whitepages": 0.65,
    "facebook": 0.60,
    "instagram": 0.55,
    "twitter": 0.55,
    "tiktok": 0.50,
    "telegram": 0.50,
    "paste_site": 0.35,
    "dark_forum": 0.30,
    "dark_paste": 0.25,
    "unknown": 0.20,
}

RISK_KEYWORDS: frozenset[str] = frozenset(
    [
        "fraud",
        "scam",
        "criminal",
        "arrest",
        "conviction",
        "warrant",
        "sanction",
        "watchlist",
        "ofac",
        "interpol",
        "drug",
        "trafficking",
        "money laundering",
        "burner",
        "dark web",
        "breach",
        "leaked",
        "sex offender",
        "bankrupt",
        "default",
        "foreclosure",
        "repossess",
    ]
)


@dataclass
class RankedResult:
    data: dict[str, Any]
    rank_score: float
    score_breakdown: dict[str, float]
    source: str = "unknown"


def rank_results(
    results: list[dict[str, Any]],
    context: str = "general",  # "risk", "wealth", "identity", "general"
    weights: dict[str, float] | None = None,
) -> list[RankedResult]:
    """
    Rank a list of result dicts by composite score.

    Args:
        results: List of result dicts. Each may have:
            - composite_quality (float 0-1)
            - source_reliability (float 0-1)
            - source_type (str)
            - scraped_at (datetime or ISO string)
            - platform (str)
            - Any data fields (text searched for risk keywords)
        context: Ranking context changes weight distribution
        weights: Override default weights

    Returns:
        List of RankedResult sorted by rank_score descending.
    """
    default_weights = _context_weights(context)
    w = {**default_weights, **(weights or {})}

    ranked = []
    for item in results:
        score, breakdown = _score_result(item, w)
        source = item.get("platform") or item.get("source_type") or "unknown"
        ranked.append(
            RankedResult(data=item, rank_score=score, score_breakdown=breakdown, source=source)
        )

    ranked.sort(key=lambda r: r.rank_score, reverse=True)
    return ranked


def _context_weights(context: str) -> dict[str, float]:
    """Return weight distribution for each scoring context."""
    if context == "risk":
        return {"quality": 0.25, "authority": 0.30, "risk_relevance": 0.30, "recency": 0.15}
    elif context == "wealth":
        return {"quality": 0.35, "authority": 0.35, "risk_relevance": 0.10, "recency": 0.20}
    elif context == "identity":
        return {"quality": 0.40, "authority": 0.30, "risk_relevance": 0.10, "recency": 0.20}
    else:  # general
        return {"quality": 0.35, "authority": 0.25, "risk_relevance": 0.20, "recency": 0.20}


def _score_result(
    item: dict[str, Any], weights: dict[str, float]
) -> tuple[float, dict[str, float]]:
    """Compute composite rank score for a single result dict."""
    quality = float(item.get("composite_quality", item.get("source_reliability", 0.5)))

    source_type = item.get("source_type") or item.get("platform") or "unknown"
    authority = AUTHORITY_WEIGHTS.get(source_type.lower(), 0.20)

    risk_relevance = _compute_risk_relevance(item)

    recency = _compute_recency(item)

    breakdown = {
        "quality": quality,
        "authority": authority,
        "risk_relevance": risk_relevance,
        "recency": recency,
    }

    score = (
        weights.get("quality", 0.35) * quality
        + weights.get("authority", 0.25) * authority
        + weights.get("risk_relevance", 0.20) * risk_relevance
        + weights.get("recency", 0.20) * recency
    )

    return min(1.0, score), breakdown


def _compute_risk_relevance(item: dict[str, Any]) -> float:
    """Count risk keyword hits across all string values in item."""
    text = " ".join(str(v).lower() for v in item.values() if isinstance(v, (str, list)))
    hits = sum(1 for kw in RISK_KEYWORDS if kw in text)
    return min(1.0, hits * 0.15)


def _compute_recency(item: dict[str, Any]) -> float:
    """Score recency: 1.0 = scraped now, decays over 30 days."""
    scraped_at = item.get("scraped_at") or item.get("last_scraped_at")
    if scraped_at is None:
        return 0.5
    if isinstance(scraped_at, str):
        try:
            scraped_at = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.5
    if scraped_at.tzinfo is None:
        scraped_at = scraped_at.replace(tzinfo=UTC)

    age_days = (datetime.now(UTC) - scraped_at).total_seconds() / 86400
    return max(0.0, 1.0 - age_days / 30)


def sort_by_risk(results: list[dict]) -> list[RankedResult]:
    """Convenience: rank for risk assessment context."""
    return rank_results(results, context="risk")


def sort_by_wealth(results: list[dict]) -> list[RankedResult]:
    """Convenience: rank for wealth assessment context."""
    return rank_results(results, context="wealth")


def sort_by_freshness(results: list[dict]) -> list[RankedResult]:
    """Convenience: rank purely by recency."""
    return rank_results(
        results,
        context="general",
        weights={"quality": 0.10, "authority": 0.10, "risk_relevance": 0.10, "recency": 0.70},
    )
