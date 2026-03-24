"""
Psychological profiling — derives OCEAN signals and emotional triggers
from scraped text. Pure analytics, no external API calls.

OCEAN = Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism
"""

from dataclasses import dataclass, field

# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class PsychologicalProfile:
    # OCEAN scores (0.0 = very low, 1.0 = very high, 0.5 = neutral/unknown)
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5

    # Emotional triggers (topics that generate strong response)
    emotional_triggers: list[str] = field(default_factory=list)

    # Dominant themes in their content
    dominant_themes: list[str] = field(default_factory=list)

    # Product/service predispositions (derived from OCEAN + themes)
    product_predispositions: list[str] = field(default_factory=list)

    # Risk signals
    financial_stress_language: bool = False
    gambling_language: bool = False
    substance_language: bool = False
    aggression_language: bool = False

    # Confidence in profile (0-1)
    confidence: float = 0.0


# ── OCEAN keyword signals ─────────────────────────────────────────────────────

OCEAN_SIGNALS: dict[str, dict[str, list[str]]] = {
    "openness": {
        "high": [
            "art",
            "music",
            "travel",
            "philosophy",
            "creative",
            "imagination",
            "poetry",
            "culture",
            "novel",
            "curious",
            "explore",
            "discovery",
            "innovation",
            "diversity",
            "ideas",
        ],
        "low": [
            "routine",
            "traditional",
            "conventional",
            "practical",
            "realistic",
            "conservative",
            "stable",
            "familiar",
            "habit",
            "rule",
        ],
    },
    "conscientiousness": {
        "high": [
            "organized",
            "plan",
            "schedule",
            "discipline",
            "goal",
            "achieve",
            "productive",
            "responsible",
            "deadline",
            "detail",
            "professional",
            "focused",
            "committed",
        ],
        "low": [
            "procrastinat",
            "lazy",
            "careless",
            "forgot",
            "mess",
            "disorganized",
            "impulsive",
            "late",
        ],
    },
    "extraversion": {
        "high": [
            "party",
            "social",
            "friends",
            "outgoing",
            "energy",
            "fun",
            "love meeting",
            "crowd",
            "networking",
            "loud",
            "adventure",
            "spontaneous",
            "love people",
        ],
        "low": [
            "introvert",
            "alone",
            "quiet",
            "home",
            "solitude",
            "private",
            "reserved",
            "shy",
            "prefer staying in",
        ],
    },
    "agreeableness": {
        "high": [
            "kind",
            "helpful",
            "empathy",
            "compassion",
            "volunteer",
            "caring",
            "supportive",
            "trust",
            "cooperat",
            "generous",
            "forgive",
            "patient",
        ],
        "low": [
            "compet",
            "argue",
            "disagree",
            "stubborn",
            "demand",
            "challenge",
            "fight",
            "confrontation",
        ],
    },
    "neuroticism": {
        "high": [
            "anxious",
            "worry",
            "stress",
            "nervous",
            "overwhelm",
            "panic",
            "depressed",
            "sad",
            "fear",
            "insecure",
            "emotional",
            "cry",
            "struggle",
            "can't cope",
            "breaking",
        ],
        "low": [
            "calm",
            "stable",
            "relax",
            "confident",
            "secure",
            "content",
            "at peace",
            "balanced",
        ],
    },
}

# ── Emotional trigger categories ──────────────────────────────────────────────

TRIGGER_CATEGORIES: dict[str, list[str]] = {
    "family": ["family", "children", "kids", "parents", "mother", "father", "sibling", "home"],
    "money": [
        "money",
        "financial",
        "debt",
        "loan",
        "bills",
        "afford",
        "broke",
        "rich",
        "wealth",
        "salary",
    ],
    "health": [
        "health",
        "sick",
        "hospital",
        "cancer",
        "doctor",
        "mental health",
        "anxiety",
        "pain",
    ],
    "career": ["job", "work", "career", "boss", "fired", "promoted", "business", "success"],
    "relationships": [
        "relationship",
        "love",
        "breakup",
        "divorce",
        "heartbreak",
        "lonely",
        "dating",
    ],
    "fairness": ["unfair", "justice", "rights", "discrimination", "cheated", "lied", "betrayed"],
    "status": ["respect", "recognition", "status", "achievement", "proud", "reputation"],
    "religion": ["god", "faith", "prayer", "church", "mosque", "temple", "spiritual", "blessed"],
    "politics": [
        "political",
        "government",
        "election",
        "vote",
        "democrat",
        "republican",
        "liberal",
    ],
    "sports": ["team", "football", "soccer", "basketball", "match", "game", "win", "lose"],
}


# ── Scoring functions ─────────────────────────────────────────────────────────


def analyze_ocean(texts: list[str]) -> dict[str, float]:
    """Score OCEAN dimensions from text keyword counts."""
    combined = " ".join(texts).lower()
    scores = {}

    for dimension, signals in OCEAN_SIGNALS.items():
        high_hits = sum(1 for kw in signals["high"] if kw in combined)
        low_hits = sum(1 for kw in signals["low"] if kw in combined)
        total = high_hits + low_hits

        if total == 0:
            scores[dimension] = 0.5  # neutral
        else:
            scores[dimension] = min(1.0, max(0.0, 0.5 + (high_hits - low_hits) * 0.08))

    return scores


def detect_emotional_triggers(texts: list[str]) -> list[str]:
    """Find which emotional trigger categories appear in text."""
    combined = " ".join(texts).lower()
    triggers = []
    for category, keywords in TRIGGER_CATEGORIES.items():
        if any(kw in combined for kw in keywords):
            triggers.append(category)
    return triggers


def detect_risk_language(texts: list[str]) -> dict[str, bool]:
    """Detect financial stress, gambling, substance, aggression language."""
    combined = " ".join(texts).lower()
    return {
        "financial_stress": any(
            kw in combined
            for kw in [
                "can't pay",
                "overdue",
                "evict",
                "repo",
                "foreclos",
                "bankrupt",
                "broke",
                "need money urgently",
                "desperate",
                "behind on",
                "debt collector",
            ]
        ),
        "gambling": any(
            kw in combined
            for kw in [
                "casino",
                "betting",
                "gambl",
                "slots",
                "poker",
                "roulette",
                "sports betting",
                "bet365",
                "bovada",
                "draftkings",
                "fanduel",
                "winning streak",
                "jackpot",
            ]
        ),
        "substance": any(
            kw in combined
            for kw in [
                "drunk",
                "high",
                "weed",
                "cocaine",
                "meth",
                "pills",
                "addiction",
                "rehab",
                "sober",
                "recovery",
                "aa meeting",
                "narcotics",
            ]
        ),
        "aggression": any(
            kw in combined
            for kw in [
                "going to hurt",
                "kill",
                "threaten",
                "fight",
                "attack",
                "revenge",
                "destroy you",
                "beat your ass",
                "gonna get you",
            ]
        ),
    }


def detect_dominant_themes(texts: list[str]) -> list[str]:
    """Return top themes by keyword frequency."""
    combined = " ".join(texts).lower()
    theme_scores: dict[str, int] = {}
    for theme, keywords in TRIGGER_CATEGORIES.items():
        theme_scores[theme] = sum(combined.count(kw) for kw in keywords)

    # Return themes with at least 2 hits, sorted by count
    active = [(t, s) for t, s in theme_scores.items() if s >= 2]
    active.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in active[:5]]  # top 5


# ── Predisposition derivation ─────────────────────────────────────────────────


def _derive_predispositions(profile: PsychologicalProfile, themes: list[str]) -> list[str]:
    predispositions: list[str] = []

    # High openness → experiences, travel, arts
    if profile.openness > 0.6:
        predispositions.extend(
            ["travel_insurance", "experience_products", "premium_subscriptions", "art_culture"]
        )

    # High conscientiousness → financial products, insurance
    if profile.conscientiousness > 0.6:
        predispositions.extend(
            ["financial_planning", "insurance", "health_products", "productivity_tools"]
        )

    # High extraversion → social products, events
    if profile.extraversion > 0.6:
        predispositions.extend(["social_events", "dining", "entertainment", "fashion"])

    # High neuroticism → insurance, mental health, security
    if profile.neuroticism > 0.6:
        predispositions.extend(
            ["health_insurance", "security_products", "mental_health_apps", "home_security"]
        )

    # Low conscientiousness + money theme → high-risk borrower signal
    if profile.conscientiousness < 0.4 and "money" in themes:
        predispositions.append("debt_consolidation")

    # High financial stress → short-term loans (payday risk)
    if profile.financial_stress_language:
        predispositions.extend(["payday_loans_risk", "debt_management"])

    # Gambling language → avoid lending / addiction flag
    if profile.gambling_language:
        predispositions.append("gambling_risk")

    # Family theme + not financially stressed = stable borrower signal
    if "family" in themes and not profile.financial_stress_language:
        predispositions.append("mortgage_receptive")

    # Career focused → premium products
    if "career" in themes and profile.conscientiousness > 0.5:
        predispositions.extend(["professional_services", "business_loans"])

    return list(dict.fromkeys(predispositions))  # deduplicate preserving order


# ── Top-level builder ─────────────────────────────────────────────────────────


def build_psychological_profile(
    texts: list[str],
    word_count_threshold: int = 20,
) -> PsychologicalProfile:
    """Build full psychological profile from text corpus."""
    profile = PsychologicalProfile()

    combined = " ".join(texts)
    word_count = len(combined.split())

    if word_count < word_count_threshold:
        # Not enough text to profile reliably
        profile.confidence = 0.0
        return profile

    ocean = analyze_ocean(texts)
    profile.openness = ocean["openness"]
    profile.conscientiousness = ocean["conscientiousness"]
    profile.extraversion = ocean["extraversion"]
    profile.agreeableness = ocean["agreeableness"]
    profile.neuroticism = ocean["neuroticism"]

    profile.emotional_triggers = detect_emotional_triggers(texts)
    profile.dominant_themes = detect_dominant_themes(texts)

    risk = detect_risk_language(texts)
    profile.financial_stress_language = risk["financial_stress"]
    profile.gambling_language = risk["gambling"]
    profile.substance_language = risk["substance"]
    profile.aggression_language = risk["aggression"]

    profile.product_predispositions = _derive_predispositions(profile, profile.dominant_themes)

    # Confidence grows with word count (more text = more reliable)
    profile.confidence = min(1.0, word_count / 500)

    return profile
