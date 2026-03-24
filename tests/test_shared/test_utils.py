import uuid

import pytest

from shared.constants import LineType, SeedType
from shared.schemas import PersonSummary, SeedInput, WebConfig
from shared.utils.email import extract_domain, is_disposable_domain, is_valid_email, normalize_email
from shared.utils.phone import get_country_code, get_line_type, is_valid_phone, normalize_phone
from shared.utils.scoring import clamp, log_scale, tier_from_score, weighted_sum
from shared.utils.social import build_profile_url, extract_handle_from_url, normalize_handle


# --- Phone ---
def test_normalize_phone_valid():
    assert normalize_phone("+1 (415) 555-2671") == "+14155552671"


def test_normalize_phone_invalid():
    assert normalize_phone("not-a-phone") is None


def test_get_line_type_unknown_returns_enum():
    lt = get_line_type("not-a-phone")
    assert lt == LineType.UNKNOWN


def test_is_valid_phone_true():
    assert is_valid_phone("+14155552671") is True


def test_is_valid_phone_false():
    assert is_valid_phone("abc") is False


# --- Email ---
def test_normalize_email_valid():
    assert normalize_email("  TEST@Example.COM  ") == "test@example.com"


def test_normalize_email_invalid():
    assert normalize_email("notanemail") is None


def test_extract_domain():
    assert extract_domain("user@gmail.com") == "gmail.com"


def test_is_disposable_domain_true():
    assert is_disposable_domain("mailinator.com") is True


def test_is_disposable_domain_false():
    assert is_disposable_domain("gmail.com") is False


# --- Social ---
def test_normalize_handle_strips_at():
    assert normalize_handle("@elonmusk") == "elonmusk"


def test_normalize_handle_lowercases():
    assert normalize_handle("TESTUSER") == "testuser"


def test_extract_handle_from_instagram_url():
    result = extract_handle_from_url("https://www.instagram.com/natgeo/")
    assert result == "natgeo"


def test_build_profile_url_instagram():
    url = build_profile_url("instagram", "testuser")
    assert url == "https://www.instagram.com/testuser/"


# --- Scoring ---
def test_clamp():
    assert clamp(1.5) == 1.0
    assert clamp(-0.1) == 0.0
    assert clamp(0.5) == 0.5


def test_log_scale_zero():
    assert log_scale(0) == 0.0


def test_log_scale_increases():
    scores = [log_scale(i) for i in range(1, 6)]
    assert scores == sorted(scores)


def test_tier_from_score():
    tiers = [(0.8, "critical"), (0.5, "high"), (0.2, "medium"), (0.0, "low")]
    assert tier_from_score(0.9, tiers) == "critical"
    assert tier_from_score(0.6, tiers) == "high"
    assert tier_from_score(0.1, tiers) == "low"


# --- Schemas ---
def test_seed_input_strips_value():
    s = SeedInput(seed_type=SeedType.PHONE, seed_value="  +1234567890  ")
    assert s.seed_value == "+1234567890"


def test_seed_input_clamps_depth():
    s = SeedInput(seed_type=SeedType.EMAIL, seed_value="a@b.com", max_depth=99)
    assert s.max_depth == 10


def test_person_summary_from_attributes():
    import uuid

    ps = PersonSummary(
        id=uuid.uuid4(),
        full_name="Test",
        relationship_score=0.5,
        default_risk_score=0.2,
        darkweb_exposure=0.0,
        composite_quality=0.7,
    )
    assert ps.full_name == "Test"
