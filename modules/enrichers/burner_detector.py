"""
Burner Detector — Task 13
=========================
Pure scoring engine that evaluates a phone number across 9 signals and
produces a BurnerScore (0.0-1.0) + BurnerConfidence classification.

Also provides `persist_burner_assessment` for upsert into the DB.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.constants import BURNER_CARRIERS, BurnerConfidence, LineType
from shared.models.burner import BurnerAssessment

# ---------------------------------------------------------------------------
# Area codes that are strongly associated with toll-free / VoIP blocks
# ---------------------------------------------------------------------------
BURNER_AREA_CODES: frozenset[str] = frozenset(
    [
        "800",
        "888",
        "877",
        "866",
        "855",
        "844",
        "833",  # toll-free
        "900",  # 900 numbers
        "521",
        "522",
        "523",
        "524",  # some VoIP blocks
    ]
)


# ---------------------------------------------------------------------------
# BurnerScore dataclass
# ---------------------------------------------------------------------------
@dataclass
class BurnerScore:
    phone: str
    score: float  # 0.0 – 1.0
    confidence: BurnerConfidence  # derived from score at construction time
    signals: dict[str, float] = field(default_factory=dict)  # signal_name → weight that fired
    carrier_name: str | None = None
    line_type: LineType | None = None
    whatsapp_registered: bool | None = None
    telegram_registered: bool | None = None

    @property
    def confidence_label(self) -> BurnerConfidence:
        """Derive BurnerConfidence from the score field (useful for re-evaluation)."""
        if self.score >= 0.70:
            return BurnerConfidence.CONFIRMED
        if self.score >= 0.40:
            return BurnerConfidence.LIKELY
        if self.score >= 0.20:
            return BurnerConfidence.POSSIBLE
        return BurnerConfidence.CLEAN


def _confidence_from_score(score: float) -> BurnerConfidence:
    """Map a numeric score to a BurnerConfidence enum value."""
    if score >= 0.70:
        return BurnerConfidence.CONFIRMED
    if score >= 0.40:
        return BurnerConfidence.LIKELY
    if score >= 0.20:
        return BurnerConfidence.POSSIBLE
    return BurnerConfidence.CLEAN


# ---------------------------------------------------------------------------
# Core scoring function — pure, no IO, no async
# ---------------------------------------------------------------------------
def compute_burner_score(
    phone: str,
    carrier_name: str | None = None,
    line_type: LineType | None = None,
    whatsapp_registered: bool | None = None,
    telegram_registered: bool | None = None,
    fonefinder_city: str | None = None,
    truecaller_name: str | None = None,
    secondary_carrier: str | None = None,  # carrier name from a secondary source (e.g. fonefinder)
    area_code: str | None = None,
) -> BurnerScore:
    """
    Pure function — no DB, no async. Evaluates 9 signals and returns a BurnerScore.

    Signal weights:
        carrier_is_burner          0.35
        line_type_voip             0.20
        line_type_prepaid          0.10
        no_whatsapp_registration   0.10
        no_telegram_registration   0.10
        multiple_carrier_hits      0.05
        no_truecaller_name         0.05
        high_risk_area_code        0.03
        no_fonefinder_location     0.02
    """
    signals: dict[str, float] = {}

    # Signal 1 — carrier is a known burner/VoIP provider
    if carrier_name:
        carrier_lower = carrier_name.lower()
        if any(b in carrier_lower for b in BURNER_CARRIERS):
            signals["carrier_is_burner"] = 0.35

    # Signal 2 — VoIP line type
    if line_type == LineType.VOIP:
        signals["line_type_voip"] = 0.20

    # Signal 3 — prepaid line type
    if line_type == LineType.PREPAID:
        signals["line_type_prepaid"] = 0.10

    # Signal 4 — not registered on WhatsApp (only fires when explicitly False)
    if whatsapp_registered is False:
        signals["no_whatsapp_registration"] = 0.10

    # Signal 5 — not registered on Telegram (only fires when explicitly False)
    if telegram_registered is False:
        signals["no_telegram_registration"] = 0.10

    # Signal 6 — carrier name differs between two lookup sources
    if carrier_name and secondary_carrier:
        if carrier_name.lower() != secondary_carrier.lower():
            signals["multiple_carrier_hits"] = 0.05

    # Signal 7 — no name found in Truecaller (burner numbers rarely have a name)
    if truecaller_name is None:
        signals["no_truecaller_name"] = 0.05

    # Signal 8 — area code is in the high-risk set
    if area_code and area_code in BURNER_AREA_CODES:
        signals["high_risk_area_code"] = 0.03

    # Signal 9 — fonefinder returned no city/state (unlocatable number)
    if fonefinder_city is None:
        signals["no_fonefinder_location"] = 0.02

    score = min(1.0, sum(signals.values()))
    confidence = _confidence_from_score(score)

    return BurnerScore(
        phone=phone,
        score=score,
        confidence=confidence,
        signals=signals,
        carrier_name=carrier_name,
        line_type=line_type,
        whatsapp_registered=whatsapp_registered,
        telegram_registered=telegram_registered,
    )


# ---------------------------------------------------------------------------
# DB persistence — upsert BurnerAssessment
# ---------------------------------------------------------------------------
async def persist_burner_assessment(
    session: AsyncSession,
    identifier_id: uuid.UUID,
    score: BurnerScore,
) -> BurnerAssessment:
    """
    Upsert a BurnerAssessment for the given identifier_id.

    If a record already exists for this identifier it is updated in-place;
    otherwise a new record is created and added to the session.
    """
    result = await session.execute(
        select(BurnerAssessment).where(BurnerAssessment.identifier_id == identifier_id)
    )
    assessment: BurnerAssessment | None = result.scalar_one_or_none()

    # Resolve line_type to its string value for storage
    line_type_value: str | None = score.line_type.value if score.line_type is not None else None

    if assessment is None:
        assessment = BurnerAssessment(
            identifier_id=identifier_id,
            burner_score=score.score,
            confidence=score.confidence.value,
            line_type=line_type_value,
            carrier_name=score.carrier_name,
            whatsapp_registered=score.whatsapp_registered,
            telegram_registered=score.telegram_registered,
            signals=score.signals,
        )
        session.add(assessment)
    else:
        assessment.burner_score = score.score
        assessment.confidence = score.confidence.value
        assessment.line_type = line_type_value
        assessment.carrier_name = score.carrier_name
        assessment.whatsapp_registered = score.whatsapp_registered
        assessment.telegram_registered = score.telegram_registered
        assessment.signals = score.signals

    return assessment
