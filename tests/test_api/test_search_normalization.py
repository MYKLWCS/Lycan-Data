from api.routes.search import SEED_PLATFORM_MAP, _auto_detect_type
from shared.constants import SeedType


def test_auto_detect_type_is_case_insensitive():
    assert _auto_detect_type("USER@EXAMPLE.COM") == SeedType.EMAIL
    assert _auto_detect_type("  USER@EXAMPLE.COM  ") == SeedType.EMAIL


def test_auto_detect_type_phone():
    assert _auto_detect_type("+1-800-555-1234") == SeedType.PHONE


def test_seed_platform_map_has_new_crawlers():
    required = {
        "username_maigret",
        "email_socialscan",
        "phone_phoneinfoga",
        "people_phonebook",
        "people_intelx",
        "email_dehashed",
    }
    all_values = {v for vals in SEED_PLATFORM_MAP.values() for v in vals}
    assert required.issubset(all_values)


def test_instagram_handle_seed_type_exists():
    assert hasattr(SeedType, "INSTAGRAM_HANDLE")
    assert hasattr(SeedType, "TWITTER_HANDLE")
    assert hasattr(SeedType, "LINKEDIN_URL")
