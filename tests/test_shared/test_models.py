import pytest
from sqlalchemy import text
from shared.models import Person, Identifier, Relationship, SocialProfile, Web


def test_person_model_has_risk_fields():
    p = Person(full_name="Test User")
    assert p.default_risk_score == 0.0
    assert p.darkweb_exposure == 0.0
    assert p.relationship_score == 0.0


def test_identifier_model_instantiates():
    i = Identifier(type="email", value="test@example.com")
    assert i.value == "test@example.com"
    assert i.confidence == 1.0


def test_social_profile_defaults():
    sp = SocialProfile(platform="instagram", handle="testuser")
    assert sp.is_verified is False
    assert sp.is_private is False
    assert sp.is_active is True


def test_web_model_defaults():
    w = Web(name="Test Web", seed_type="phone", seed_value="+1234567890")
    assert w.status == "pending"
    assert w.max_depth == 3
    assert w.depth == 0
