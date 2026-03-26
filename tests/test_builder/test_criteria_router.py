"""Tests for modules/builder/criteria_router.py — CriteriaRouter."""

from modules.builder.criteria_router import CriteriaRouter


def test_location_routes_to_voter_and_people_search():
    router = CriteriaRouter()
    sources = router.route({"location": "Miami, FL"})
    names = [s["name"] for s in sources]
    assert "voter_records" in names
    assert "fps_location" in names
    assert "tps_location" in names


def test_employer_routes_to_linkedin_and_sec():
    router = CriteriaRouter()
    sources = router.route({"employer": "Acme Corp"})
    names = [s["name"] for s in sources]
    assert "linkedin:Acme Corp" in names
    assert "sec:Acme Corp" in names
    assert "opencorp:Acme Corp" in names


def test_seed_list_email_routes_to_email_crawlers():
    router = CriteriaRouter()
    sources = router.route({"seed_list": ["john@example.com"]})
    names = [s["name"] for s in sources]
    assert any("email" in n for n in names)
    assert any("hibp" in n for n in names)


def test_seed_list_phone_routes_to_phone_crawlers():
    router = CriteriaRouter()
    sources = router.route({"seed_list": ["+15551234567"]})
    names = [s["name"] for s in sources]
    assert any("phone" in n for n in names)


def test_seed_list_name_routes_to_people_search():
    router = CriteriaRouter()
    sources = router.route({"seed_list": ["John Smith"]})
    names = [s["name"] for s in sources]
    assert any("fps" in n for n in names)
    assert any("tps" in n for n in names)
    assert any("wp" in n for n in names)


def test_platform_specific_discovery():
    router = CriteriaRouter()
    sources = router.route({"specific_platform": "instagram", "keywords": "miami_lifestyle"})
    names = [s["name"] for s in sources]
    assert "platform:instagram" in names


def test_property_routes():
    router = CriteriaRouter()
    sources = router.route({"property_owner": True, "location": "Dallas, TX"})
    names = [s["name"] for s in sources]
    assert any("zillow" in n or "redfin" in n or "county" in n for n in names)


def test_keywords_routes_to_news_and_sherlock():
    router = CriteriaRouter()
    sources = router.route({"keywords": "CEO startup fintech"})
    names = [s["name"] for s in sources]
    assert any("news" in n or "google_news" in n for n in names)
    assert any("sherlock" in n for n in names)


def test_empty_criteria_fallback():
    router = CriteriaRouter()
    sources = router.route({})
    # Should have at least one fallback source
    assert len(sources) >= 1


def test_combined_criteria():
    router = CriteriaRouter()
    sources = router.route({
        "location": "Austin, TX",
        "employer": "Tesla",
        "has_vehicle": True,
        "age_range": {"min": 25, "max": 45},
    })
    names = [s["name"] for s in sources]
    # Should have sources for both location and employer
    assert any("voter" in n or "fps" in n for n in names)
    assert any("tesla" in n.lower() for n in names)


def test_no_duplicate_sources():
    router = CriteriaRouter()
    sources = router.route({
        "location": "Miami",
        "property_owner": True,
    })
    names = [s["name"] for s in sources]
    assert len(names) == len(set(names)), "Duplicate source names found"
