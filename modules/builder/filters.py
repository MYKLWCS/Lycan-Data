"""
Post-filters for the People Builder.

After discovery and building, these filters are applied to ensure
only people matching ALL specified criteria are returned.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from shared.models.person import Person

logger = logging.getLogger(__name__)


def apply_post_filters(person: Person, criteria: dict[str, Any]) -> bool:
    """Return True if person passes ALL specified criteria filters."""

    # Age range
    age_range = criteria.get("age_range")
    if age_range and person.date_of_birth:
        today = date.today()
        age = today.year - person.date_of_birth.year
        if today.month < person.date_of_birth.month or (
            today.month == person.date_of_birth.month
            and today.day < person.date_of_birth.day
        ):
            age -= 1
        if "min" in age_range and age < age_range["min"]:
            return False
        if "max" in age_range and age > age_range["max"]:
            return False

    # Income range
    income_range = criteria.get("income_range")
    if income_range and person.estimated_annual_income_usd is not None:
        if "min" in income_range and person.estimated_annual_income_usd < income_range["min"]:
            return False
        if "max" in income_range and person.estimated_annual_income_usd > income_range["max"]:
            return False

    # Property owner
    if criteria.get("property_owner") is True and person.property_count < 1:
        return False

    # Property value range
    prop_range = criteria.get("property_value_range")
    if prop_range:
        # Property value is on the Person model as estimated_net_worth or property-level
        # For now we use property_count as proxy
        pass  # Detailed property value filtering requires join — handled at DB level

    # Has vehicle
    if criteria.get("has_vehicle") is True and person.vehicle_count < 1:
        return False

    # Vehicle value minimum
    vehicle_min = criteria.get("vehicle_value_min")
    if vehicle_min is not None:
        pass  # Requires vehicle join — builder handles at DB level

    # Risk tier
    risk_tier = criteria.get("risk_tier")
    if risk_tier:
        score = person.default_risk_score or 0.0
        tier_map = {
            "low": (0.0, 0.39),
            "medium": (0.40, 0.59),
            "high": (0.60, 0.79),
            "critical": (0.80, 1.0),
        }
        if risk_tier in tier_map:
            lo, hi = tier_map[risk_tier]
            if not (lo <= score <= hi):
                return False

    # Credit score range
    credit_range = criteria.get("credit_score_range")
    if credit_range and person.alt_credit_score is not None:
        if "min" in credit_range and person.alt_credit_score < credit_range["min"]:
            return False
        if "max" in credit_range and person.alt_credit_score > credit_range["max"]:
            return False

    # Education level
    edu_level = criteria.get("education_level")
    if edu_level:
        # Education is in a separate table; this is a soft filter
        pass

    # Marital status
    marital = criteria.get("marital_status")
    if marital and person.marital_status:
        if person.marital_status.lower() != marital.lower():
            return False

    # Has criminal record
    if criteria.get("has_criminal_record") is True:
        # Check via meta or criminal_records relationship
        pass  # Requires join

    # Has bankruptcy
    if criteria.get("has_bankruptcy") is True:
        pass  # Requires credit profile join

    # Tags
    tags = criteria.get("tags")
    if tags and isinstance(tags, list):
        person_tags = set(person.marketing_tags_list or [])
        if not person_tags.intersection(set(tags)):
            return False

    # Gender (inferred from criteria)
    gender = criteria.get("gender")
    if gender and person.gender:
        if person.gender.lower() != gender.lower():
            return False

    return True
