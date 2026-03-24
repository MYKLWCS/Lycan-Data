"""
Tests for modules/enrichers/psychological.py — 15 tests covering OCEAN scoring,
emotional triggers, risk language, dominant themes, and product predispositions.
"""
from __future__ import annotations

import pytest

from modules.enrichers.psychological import (
    PsychologicalProfile,
    analyze_ocean,
    build_psychological_profile,
    detect_dominant_themes,
    detect_emotional_triggers,
    detect_risk_language,
)


# ── analyze_ocean ─────────────────────────────────────────────────────────────

class TestAnalyzeOcean:
    def test_high_openness_keywords(self):
        texts = ["I love art, music, travel, philosophy and exploring creative ideas"]
        scores = analyze_ocean(texts)
        assert scores["openness"] > 0.5

    def test_low_openness_keywords(self):
        texts = ["I prefer routine, conventional, practical, familiar and traditional approaches"]
        scores = analyze_ocean(texts)
        assert scores["openness"] < 0.5

    def test_no_keywords_neutral(self):
        texts = ["the quick brown fox jumped over the lazy dog"]
        scores = analyze_ocean(texts)
        # 'lazy' can hit conscientiousness-low; openness and others should stay neutral
        assert scores["openness"] == 0.5

    def test_high_conscientiousness(self):
        texts = ["I am very organized, goal-oriented, disciplined and professional at meeting deadlines"]
        scores = analyze_ocean(texts)
        assert scores["conscientiousness"] > 0.5

    def test_high_neuroticism(self):
        texts = ["I feel so anxious and stressed, worry constantly and often feel overwhelmed and depressed"]
        scores = analyze_ocean(texts)
        assert scores["neuroticism"] > 0.5


# ── detect_emotional_triggers ─────────────────────────────────────────────────

class TestDetectEmotionalTriggers:
    def test_family_keywords(self):
        triggers = detect_emotional_triggers(["I love my family and children at home"])
        assert "family" in triggers

    def test_money_keywords(self):
        triggers = detect_emotional_triggers(["worried about money and debt and bills"])
        assert "money" in triggers

    def test_no_keywords_empty_list(self):
        triggers = detect_emotional_triggers(["the sky is blue today"])
        assert triggers == []

    def test_multiple_triggers_detected(self):
        triggers = detect_emotional_triggers([
            "My family is important. I worry about money and my career job work."
        ])
        assert "family" in triggers
        assert "money" in triggers
        assert "career" in triggers


# ── detect_risk_language ──────────────────────────────────────────────────────

class TestDetectRiskLanguage:
    def test_financial_stress_detected(self):
        risk = detect_risk_language(["I can't pay my bills and debt collector keeps calling"])
        assert risk["financial_stress"] is True

    def test_gambling_detected(self):
        risk = detect_risk_language(["I love going to the casino and betting on poker"])
        assert risk["gambling"] is True

    def test_clean_text_all_false(self):
        risk = detect_risk_language(["Had a great day at the park with friends"])
        assert risk["financial_stress"] is False
        assert risk["gambling"] is False
        assert risk["substance"] is False
        assert risk["aggression"] is False

    def test_substance_detected(self):
        risk = detect_risk_language(["he is in rehab dealing with addiction and recovery"])
        assert risk["substance"] is True


# ── detect_dominant_themes ────────────────────────────────────────────────────

class TestDetectDominantThemes:
    def test_money_theme_with_repeated_keywords(self):
        texts = ["money money financial debt loan debt bills afford"]
        themes = detect_dominant_themes(texts)
        assert "money" in themes

    def test_no_themes_when_insufficient_hits(self):
        themes = detect_dominant_themes(["one money mention here"])
        # Only 1 hit — below the threshold of 2 — so money should not appear
        assert "money" not in themes


# ── build_psychological_profile ───────────────────────────────────────────────

class TestBuildPsychologicalProfile:
    def test_short_text_confidence_zero(self):
        """Less than 20 words → confidence = 0.0."""
        profile = build_psychological_profile(["too short"])
        assert profile.confidence == 0.0

    def test_long_text_confidence_full(self):
        """500+ words → confidence = 1.0."""
        # Generate a 500-word text rich in neutral filler
        word = "the"
        texts = [(" ".join([word] * 510))]
        profile = build_psychological_profile(texts)
        assert profile.confidence == 1.0

    def test_returns_psychological_profile_instance(self):
        texts = [" ".join(["word"] * 30)]
        profile = build_psychological_profile(texts)
        assert isinstance(profile, PsychologicalProfile)

    def test_high_openness_predisposition(self):
        """High openness signals should include travel_insurance in predispositions."""
        texts = [
            "I love art music travel philosophy creative imagination poetry culture "
            "novel curious explore discovery innovation diversity ideas. " * 3
        ]
        profile = build_psychological_profile(texts)
        assert profile.openness > 0.6
        assert "travel_insurance" in profile.product_predispositions

    def test_financial_stress_predisposition(self):
        """Financial stress language adds payday_loans_risk to predispositions."""
        texts = [
            "I can't pay my rent and the debt collector keeps calling. "
            "I'm desperate and behind on all my payments every single month. " * 5
        ]
        profile = build_psychological_profile(texts)
        assert profile.financial_stress_language is True
        assert "payday_loans_risk" in profile.product_predispositions

    def test_gambling_predisposition(self):
        """Gambling language adds gambling_risk to predispositions."""
        texts = [
            "I go to the casino every weekend for poker and betting on roulette. "
            "I love sports betting and winning big jackpots at the slots. " * 4
        ]
        profile = build_psychological_profile(texts)
        assert profile.gambling_language is True
        assert "gambling_risk" in profile.product_predispositions
