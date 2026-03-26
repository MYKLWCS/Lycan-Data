"""Tests for modules/graph/relationship_expansion.py — RelationshipExpansionEngine."""

from modules.graph.relationship_expansion import (
    DEFAULT_STRENGTH,
    RELATIONSHIP_COLORS,
    RELATIONSHIP_LABEL_MAP,
    SOURCE_CONFIDENCE,
    RelationshipExpansionEngine,
    _classify_relationship,
    _compute_composite,
)


def test_classify_spouse():
    detailed, broad = _classify_relationship("spouse")
    assert detailed == "spouse"
    assert broad == "family"


def test_classify_wife_maps_to_spouse():
    detailed, broad = _classify_relationship("wife")
    assert detailed == "spouse"
    assert broad == "family"


def test_classify_employer():
    detailed, broad = _classify_relationship("employer")
    assert detailed == "employer"
    assert broad == "employer"


def test_classify_unknown_defaults_to_associate():
    detailed, broad = _classify_relationship("xyzzy_unknown_type")
    assert detailed == "associate"
    assert broad == "associate"


def test_classify_case_insensitive():
    detailed, broad = _classify_relationship("SPOUSE")
    assert detailed == "spouse"
    assert broad == "family"


def test_classify_with_whitespace():
    detailed, broad = _classify_relationship("  Friend  ")
    assert detailed == "friend"
    assert broad == "associate"


def test_classify_business_partner():
    detailed, broad = _classify_relationship("business partner")
    assert detailed == "business_partner"
    assert broad == "business_partner"


def test_classify_co_defendant():
    detailed, broad = _classify_relationship("co-defendant")
    assert detailed == "co_defendant"
    assert broad == "associate"


def test_classify_power_of_attorney():
    detailed, broad = _classify_relationship("power of attorney")
    assert detailed == "power_of_attorney"
    assert broad == "associate"


def test_compute_composite():
    # 50 strength * 0.4 + 80 confidence * 0.4 + 100 freshness * 0.2
    # = 20 + 32 + 20 = 72
    result = _compute_composite(50, 0.8, 1.0)
    assert result == 72.0


def test_compute_composite_all_max():
    result = _compute_composite(100, 1.0, 1.0)
    assert result == 100.0


def test_compute_composite_all_zero():
    result = _compute_composite(0, 0.0, 0.0)
    assert result == 0.0


def test_default_strength_spouse_is_high():
    assert DEFAULT_STRENGTH["spouse"] >= 90


def test_default_strength_acquaintance_is_low():
    assert DEFAULT_STRENGTH["acquaintance"] <= 30


def test_source_confidence_court_records_high():
    assert SOURCE_CONFIDENCE["court_records"] >= 0.85


def test_source_confidence_social_media_moderate():
    assert SOURCE_CONFIDENCE["social_media"] < 0.70


def test_relationship_colors_all_types_have_colors():
    for label_map_value in RELATIONSHIP_LABEL_MAP.values():
        detailed_type = label_map_value[0]
        assert detailed_type in RELATIONSHIP_COLORS, f"Missing color for {detailed_type}"


def test_relationship_colors_match_spec():
    """Verify key colors match the spec."""
    assert RELATIONSHIP_COLORS["spouse"] == "#DC2626"
    assert RELATIONSHIP_COLORS["parent"] == "#2563EB"
    assert RELATIONSHIP_COLORS["sibling"] == "#60A5FA"
    assert RELATIONSHIP_COLORS["friend"] == "#4ADE80"
    assert RELATIONSHIP_COLORS["employer"] == "#C2410C"
    assert RELATIONSHIP_COLORS["co_signer"] == "#CA8A04"


def test_verification_level_progression():
    engine = RelationshipExpansionEngine()
    assert engine._verification_level(1) == "single_source"
    assert engine._verification_level(2) == "cross_referenced"
    assert engine._verification_level(3) == "cross_referenced"
    assert engine._verification_level(5) == "confirmed"


def test_risk_tier_calculation():
    assert RelationshipExpansionEngine._risk_tier(0.9) == "critical"
    assert RelationshipExpansionEngine._risk_tier(0.7) == "high"
    assert RelationshipExpansionEngine._risk_tier(0.5) == "medium"
    assert RelationshipExpansionEngine._risk_tier(0.2) == "low"
    assert RelationshipExpansionEngine._risk_tier(None) == "unknown"


def test_calc_age_none():
    assert RelationshipExpansionEngine._calc_age(None) is None


def test_calc_age_valid():
    from datetime import date
    # Roughly 36 years old (born 1990)
    age = RelationshipExpansionEngine._calc_age(date(1990, 1, 1))
    assert age >= 36


def test_all_label_map_entries_have_strength():
    """Every detailed_type in the label map should have a default strength."""
    for label, (detailed, _broad) in RELATIONSHIP_LABEL_MAP.items():
        assert detailed in DEFAULT_STRENGTH, f"Missing default strength for {detailed} (from label '{label}')"
