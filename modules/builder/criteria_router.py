"""
Criteria Router — maps input criteria to appropriate discovery crawlers.

Given any combination of search parameters, determines which crawlers
can fulfil the discovery phase and what parameters to pass them.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CriteriaRouter:
    """Routes discovery criteria to appropriate crawler sources."""

    def route(self, criteria: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a list of source configs to execute for discovery.

        Each source config: {"name": str, "crawler": str, "params": dict}
        """
        sources: list[dict[str, Any]] = []

        location = criteria.get("location")
        state = criteria.get("state")
        country = criteria.get("country")
        employer = criteria.get("employer")
        platform = criteria.get("specific_platform")
        keywords = criteria.get("keywords")
        seed_list = criteria.get("seed_list", [])
        has_property = criteria.get("property_owner")
        property_range = criteria.get("property_value_range")
        has_vehicle = criteria.get("has_vehicle")

        # ── Seed list: search each seed through full pipeline ──────────
        if seed_list:
            for seed in seed_list[:500]:  # cap at 500 seeds
                seed_str = str(seed).strip()
                if not seed_str:
                    continue
                # Infer seed type
                if "@" in seed_str:
                    sources.append({"name": f"email:{seed_str}", "crawler": "email_holehe", "params": {"email": seed_str}})
                    sources.append({"name": f"hibp:{seed_str}", "crawler": "email_hibp", "params": {"email": seed_str}})
                elif seed_str.replace("+", "").replace("-", "").replace(" ", "").isdigit():
                    sources.append({"name": f"phone:{seed_str}", "crawler": "phone_phoneinfoga", "params": {"phone": seed_str}})
                    sources.append({"name": f"truecaller:{seed_str}", "crawler": "phone_truecaller", "params": {"phone": seed_str}})
                else:
                    # Assume name
                    sources.append({"name": f"fps:{seed_str}", "crawler": "fastpeoplesearch", "params": {"name": seed_str, "location": location or ""}})
                    sources.append({"name": f"tps:{seed_str}", "crawler": "truepeoplesearch", "params": {"name": seed_str}})
                    sources.append({"name": f"wp:{seed_str}", "crawler": "whitepages", "params": {"name": seed_str, "location": location or ""}})

        # ── Location-based discovery ───────────────────────────────────
        if location or state:
            loc_str = location or state or ""
            sources.extend([
                {"name": "voter_records", "crawler": "public_voter", "params": {"location": loc_str, "state": state}},
                {"name": "property_county", "crawler": "property_county", "params": {"location": loc_str}},
                {"name": "fps_location", "crawler": "fastpeoplesearch", "params": {"location": loc_str}},
                {"name": "tps_location", "crawler": "truepeoplesearch", "params": {"location": loc_str}},
            ])

        # ── Employer-based discovery ───────────────────────────────────
        if employer:
            sources.extend([
                {"name": f"linkedin:{employer}", "crawler": "linkedin", "params": {"company": employer}},
                {"name": f"sec:{employer}", "crawler": "company_sec", "params": {"company_name": employer}},
                {"name": f"opencorp:{employer}", "crawler": "company_opencorporates", "params": {"company_name": employer}},
            ])

        # ── Platform-specific discovery ────────────────────────────────
        if platform:
            platform_lower = platform.lower()
            if platform_lower in ("instagram", "twitter", "tiktok", "linkedin", "reddit", "github", "youtube"):
                sources.append({
                    "name": f"platform:{platform_lower}",
                    "crawler": platform_lower,
                    "params": {"search": keywords or location or "", "platform": platform_lower},
                })
            # Username enumeration for social platforms
            if keywords:
                sources.append({
                    "name": "sherlock_username",
                    "crawler": "username_sherlock",
                    "params": {"username": keywords},
                })

        # ── Property-based discovery ───────────────────────────────────
        if has_property or property_range:
            loc = location or state or ""
            sources.extend([
                {"name": "zillow", "crawler": "property_zillow", "params": {"location": loc}},
                {"name": "redfin", "crawler": "property_redfin", "params": {"location": loc}},
                {"name": "county_assessor", "crawler": "property_county", "params": {"location": loc}},
            ])

        # ── Vehicle-based discovery ────────────────────────────────────
        if has_vehicle:
            sources.append({"name": "vehicle_nhtsa", "crawler": "vehicle_nhtsa", "params": {"location": location or ""}})

        # ── Keywords / free-text discovery ─────────────────────────────
        if keywords and not seed_list:
            sources.extend([
                {"name": f"news:{keywords}", "crawler": "news_search", "params": {"query": keywords}},
                {"name": f"google_news:{keywords}", "crawler": "google_news_rss", "params": {"query": keywords}},
                {"name": f"sherlock:{keywords}", "crawler": "username_sherlock", "params": {"username": keywords}},
            ])

        # ── Fallback: if no specific criteria, use bulk sources ────────
        if not sources:
            loc = location or state or country or ""
            if loc:
                sources.extend([
                    {"name": "voter_bulk", "crawler": "public_voter", "params": {"location": loc}},
                    {"name": "fps_bulk", "crawler": "fastpeoplesearch", "params": {"location": loc}},
                ])
            else:
                # Pure bulk — use whatever has broad access
                sources.append({"name": "voter_national", "crawler": "public_voter", "params": {}})

        # Deduplicate sources by name
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for s in sources:
            if s["name"] not in seen:
                seen.add(s["name"])
                unique.append(s)

        logger.info("CriteriaRouter produced %d sources for criteria keys: %s",
                     len(unique), list(criteria.keys()))
        return unique
