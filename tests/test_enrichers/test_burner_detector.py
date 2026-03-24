"""
Tests for the burner detector scoring engine.
Task 13 — 15 tests covering all 9 signals + persistence.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.burner_detector import (
    BURNER_AREA_CODES,
    BurnerScore,
    compute_burner_score,
    persist_burner_assessment,
)
from shared.constants import BurnerConfidence, LineType


# ---------------------------------------------------------------------------
# 1. VoIP burner carrier → CONFIRMED (score >= 0.70)
# ---------------------------------------------------------------------------
def test_voip_burner_carrier_confirmed():
    """carrier_is_burner (0.35) + line_type_voip (0.20) + no_truecaller_name (0.05)
    + no_fonefinder_location (0.02) = 0.62 minimum; add no_whatsapp + no_telegram for 0.82."""
    score = compute_burner_score(
        phone="+15550000001",
        carrier_name="TextNow Wireless",
        line_type=LineType.VOIP,
        whatsapp_registered=False,
        telegram_registered=False,
        fonefinder_city=None,
        truecaller_name=None,
    )
    assert score.score >= 0.70
    assert score.confidence == BurnerConfidence.CONFIRMED


# ---------------------------------------------------------------------------
# 2. Prepaid + no WhatsApp + no Telegram → LIKELY (0.40-0.69)
# ---------------------------------------------------------------------------
def test_prepaid_no_messaging_likely():
    """prepaid (0.10) + no_whatsapp (0.10) + no_telegram (0.10)
    + no_truecaller (0.05) + no_fonefinder (0.02) = 0.37, still POSSIBLE.
    Add a real carrier so carrier_is_burner doesn't fire; but we need 0.40+.
    Use no_truecaller + no_fonefinder to push over the edge."""
    score = compute_burner_score(
        phone="+15550000002",
        carrier_name="AT&T",
        line_type=LineType.PREPAID,
        whatsapp_registered=False,
        telegram_registered=False,
        fonefinder_city=None,
        truecaller_name=None,
        secondary_carrier="Verizon",  # carrier mismatch +0.05
    )
    # 0.10 + 0.10 + 0.10 + 0.05 + 0.05 + 0.02 = 0.42
    assert 0.40 <= score.score < 0.70
    assert score.confidence == BurnerConfidence.LIKELY


# ---------------------------------------------------------------------------
# 3. Real carrier, all signals clean → CLEAN (score < 0.20)
# ---------------------------------------------------------------------------
def test_real_carrier_all_clean():
    score = compute_burner_score(
        phone="+14155550001",
        carrier_name="AT&T Mobility",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="San Francisco",
        truecaller_name="John Smith",
        secondary_carrier=None,
        area_code="415",
    )
    assert score.score < 0.20
    assert score.confidence == BurnerConfidence.CLEAN


# ---------------------------------------------------------------------------
# 4. Carrier mismatch + no truecaller name → adds to score
# ---------------------------------------------------------------------------
def test_carrier_mismatch_and_no_truecaller_adds_score():
    score_without = compute_burner_score(
        phone="+15550000003",
        carrier_name="Verizon",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="Dallas",
        truecaller_name="Jane Doe",
        secondary_carrier=None,
    )
    score_with = compute_burner_score(
        phone="+15550000003",
        carrier_name="Verizon",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="Dallas",
        truecaller_name=None,  # +0.05
        secondary_carrier="T-Mobile",  # +0.05
    )
    assert score_with.score == score_without.score + 0.10
    assert "multiple_carrier_hits" in score_with.signals
    assert "no_truecaller_name" in score_with.signals


# ---------------------------------------------------------------------------
# 5. Burner area code (800) fires signal
# ---------------------------------------------------------------------------
def test_burner_area_code_fires():
    score = compute_burner_score(
        phone="+18005550001",
        carrier_name="AT&T",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="Unknown",
        truecaller_name="Support Line",
        area_code="800",
    )
    assert "high_risk_area_code" in score.signals
    assert score.signals["high_risk_area_code"] == 0.03


# ---------------------------------------------------------------------------
# 6. No fonefinder location fires signal
# ---------------------------------------------------------------------------
def test_no_fonefinder_location_fires():
    score = compute_burner_score(
        phone="+15550000004",
        carrier_name="T-Mobile",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city=None,
        truecaller_name="Bob",
    )
    assert "no_fonefinder_location" in score.signals
    assert score.signals["no_fonefinder_location"] == 0.02


# ---------------------------------------------------------------------------
# 7. Score capped at 1.0 even if all signals fire
# ---------------------------------------------------------------------------
def test_score_capped_at_one():
    score = compute_burner_score(
        phone="+18005550002",
        carrier_name="TextNow",
        line_type=LineType.VOIP,
        whatsapp_registered=False,
        telegram_registered=False,
        fonefinder_city=None,
        truecaller_name=None,
        secondary_carrier="Hushed",
        area_code="800",
    )
    # All 9 signals: 0.35+0.20+0.10+0.10+0.05+0.05+0.03+0.02 = 0.90 (no prepaid since voip set)
    # With prepaid it would exceed 1.0 but we use VOIP; total = 0.90
    assert score.score <= 1.0
    # Force over 1.0 by summing manually — confirm cap
    total_weights = sum(score.signals.values())
    assert score.score == min(1.0, total_weights)


# ---------------------------------------------------------------------------
# 8. BurnerScore.confidence_label correct for each tier
# ---------------------------------------------------------------------------
def test_confidence_label_tiers():
    def make_score(raw: float) -> BurnerScore:
        return BurnerScore(
            phone="+15550000000",
            score=raw,
            confidence=BurnerConfidence.CLEAN,  # placeholder — use property
            signals={},
        )

    assert make_score(0.70).confidence_label == BurnerConfidence.CONFIRMED
    assert make_score(0.85).confidence_label == BurnerConfidence.CONFIRMED
    assert make_score(1.00).confidence_label == BurnerConfidence.CONFIRMED
    assert make_score(0.40).confidence_label == BurnerConfidence.LIKELY
    assert make_score(0.69).confidence_label == BurnerConfidence.LIKELY
    assert make_score(0.20).confidence_label == BurnerConfidence.POSSIBLE
    assert make_score(0.39).confidence_label == BurnerConfidence.POSSIBLE
    assert make_score(0.19).confidence_label == BurnerConfidence.CLEAN
    assert make_score(0.00).confidence_label == BurnerConfidence.CLEAN


# ---------------------------------------------------------------------------
# 9. signals dict contains only fired signals (not all 9)
# ---------------------------------------------------------------------------
def test_signals_dict_only_fired():
    score = compute_burner_score(
        phone="+14155550002",
        carrier_name="AT&T Mobility",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="New York",
        truecaller_name="Alice",
        area_code="212",
    )
    # No signals should fire for a clean number
    assert score.signals == {}

    score2 = compute_burner_score(
        phone="+18005550003",
        carrier_name="Twilio",
        line_type=LineType.VOIP,
        whatsapp_registered=True,
        telegram_registered=True,
        fonefinder_city="Chicago",
        truecaller_name="Support",
        area_code="800",
    )
    # Only carrier_is_burner, line_type_voip, high_risk_area_code fire
    assert set(score2.signals.keys()) == {
        "carrier_is_burner",
        "line_type_voip",
        "high_risk_area_code",
    }


# ---------------------------------------------------------------------------
# 10. carrier_is_burner: "textnow" fires, "AT&T" doesn't
# ---------------------------------------------------------------------------
def test_carrier_is_burner_textnow_vs_att():
    burner = compute_burner_score(
        phone="+15550000005",
        carrier_name="textnow",
        line_type=LineType.MOBILE,
    )
    clean = compute_burner_score(
        phone="+15550000006",
        carrier_name="AT&T",
        line_type=LineType.MOBILE,
    )
    assert "carrier_is_burner" in burner.signals
    assert burner.signals["carrier_is_burner"] == 0.35
    assert "carrier_is_burner" not in clean.signals


# ---------------------------------------------------------------------------
# 11. carrier_is_burner: "twilio" substring match fires
# ---------------------------------------------------------------------------
def test_carrier_is_burner_twilio_substring():
    score = compute_burner_score(
        phone="+15550000007",
        carrier_name="Twilio Inc. Voice Services",
        line_type=LineType.VOIP,
    )
    assert "carrier_is_burner" in score.signals
    assert score.signals["carrier_is_burner"] == 0.35


# ---------------------------------------------------------------------------
# 12. whatsapp_registered=None → signal NOT fired
# ---------------------------------------------------------------------------
def test_whatsapp_none_no_signal():
    score = compute_burner_score(
        phone="+15550000008",
        carrier_name="T-Mobile",
        line_type=LineType.MOBILE,
        whatsapp_registered=None,
    )
    assert "no_whatsapp_registration" not in score.signals


# ---------------------------------------------------------------------------
# 13. whatsapp_registered=True → signal NOT fired
# ---------------------------------------------------------------------------
def test_whatsapp_true_no_signal():
    score = compute_burner_score(
        phone="+15550000009",
        carrier_name="T-Mobile",
        line_type=LineType.MOBILE,
        whatsapp_registered=True,
    )
    assert "no_whatsapp_registration" not in score.signals


# ---------------------------------------------------------------------------
# 14. whatsapp_registered=False → signal fires
# ---------------------------------------------------------------------------
def test_whatsapp_false_signal_fires():
    score = compute_burner_score(
        phone="+15550000010",
        carrier_name="T-Mobile",
        line_type=LineType.MOBILE,
        whatsapp_registered=False,
    )
    assert "no_whatsapp_registration" in score.signals
    assert score.signals["no_whatsapp_registration"] == 0.10


# ---------------------------------------------------------------------------
# 15. persist_burner_assessment: mock session, verify correct fields set
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_persist_burner_assessment_sets_fields():
    from shared.models.burner import BurnerAssessment

    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # add() is synchronous in SQLAlchemy

    # Make execute().scalar_one_or_none() return None (no existing record)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    identifier_id = uuid.uuid4()
    score = compute_burner_score(
        phone="+15550000011",
        carrier_name="TextNow",
        line_type=LineType.VOIP,
        whatsapp_registered=False,
        telegram_registered=False,
        fonefinder_city=None,
        truecaller_name=None,
    )

    assessment = await persist_burner_assessment(
        session=mock_session,
        identifier_id=identifier_id,
        score=score,
    )

    assert isinstance(assessment, BurnerAssessment)
    assert assessment.identifier_id == identifier_id
    assert assessment.burner_score == score.score
    assert assessment.confidence == score.confidence.value
    assert assessment.signals == score.signals
    assert assessment.carrier_name == score.carrier_name
    assert assessment.line_type == score.line_type.value if score.line_type else None
    assert assessment.whatsapp_registered == score.whatsapp_registered
    assert assessment.telegram_registered == score.telegram_registered
    mock_session.add.assert_called_once()
