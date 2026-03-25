#!/usr/bin/env python3
"""
Bulk-add CrawlerCategory and RateLimit to all registered scrapers.

Reads each scraper file, finds the class body, and inserts:
  category = CrawlerCategory.X
  rate_limit = RateLimit(...)

Also adds the import for CrawlerCategory and RateLimit if missing.
"""

import os
import re
import sys

# Category mapping: scraper filename → CrawlerCategory enum member
CATEGORY_MAP = {
    # PEOPLE
    "people_thatsthem.py": "PEOPLE",
    "people_intelx.py": "PEOPLE",
    "people_familysearch.py": "PEOPLE",
    "people_fbi_wanted.py": "PEOPLE",
    "people_findagrave.py": "PEOPLE",
    "people_immigration.py": "PEOPLE",
    "people_interpol.py": "PEOPLE",
    "people_namus.py": "PEOPLE",
    "people_phonebook.py": "PEOPLE",
    "people_usmarshals.py": "PEOPLE",
    "people_zabasearch.py": "PEOPLE",
    "fastpeoplesearch.py": "PEOPLE",
    "truepeoplesearch.py": "PEOPLE",
    "whitepages.py": "PEOPLE",
    "spokeo.py": "PEOPLE",
    "radaris.py": "PEOPLE",
    "familytreenow.py": "PEOPLE",
    "obituary_search.py": "PEOPLE",
    "interests_extractor.py": "PEOPLE",
    "username_maigret.py": "PEOPLE",
    "username_sherlock.py": "PEOPLE",
    "clustrmaps.py": "PEOPLE",
    # SOCIAL_MEDIA
    "twitter.py": "SOCIAL_MEDIA",
    "facebook.py": "SOCIAL_MEDIA",
    "instagram.py": "SOCIAL_MEDIA",
    "linkedin.py": "SOCIAL_MEDIA",
    "reddit.py": "SOCIAL_MEDIA",
    "youtube.py": "SOCIAL_MEDIA",
    "tiktok.py": "SOCIAL_MEDIA",
    "snapchat.py": "SOCIAL_MEDIA",
    "pinterest.py": "SOCIAL_MEDIA",
    "discord.py": "SOCIAL_MEDIA",
    "whatsapp.py": "SOCIAL_MEDIA",
    "telegram.py": "SOCIAL_MEDIA",
    "bluesky_profile.py": "SOCIAL_MEDIA",
    "threads_profile.py": "SOCIAL_MEDIA",
    "social_mastodon.py": "SOCIAL_MEDIA",
    "social_spotify.py": "SOCIAL_MEDIA",
    "social_steam.py": "SOCIAL_MEDIA",
    "social_twitch.py": "SOCIAL_MEDIA",
    "social_graph.py": "SOCIAL_MEDIA",
    "social_posts_analyzer.py": "SOCIAL_MEDIA",
    "truth_social_profile.py": "SOCIAL_MEDIA",
    "vk_profile.py": "SOCIAL_MEDIA",
    "github.py": "SOCIAL_MEDIA",
    "github_profile.py": "SOCIAL_MEDIA",
    "spotify_public.py": "SOCIAL_MEDIA",
    "stackoverflow_profile.py": "SOCIAL_MEDIA",
    # PUBLIC_RECORDS
    "txcourts.py": "PUBLIC_RECORDS",
    "fl_courts.py": "PUBLIC_RECORDS",
    "ca_courts.py": "PUBLIC_RECORDS",
    "court_courtlistener.py": "PUBLIC_RECORDS",
    "court_state.py": "PUBLIC_RECORDS",
    "bankruptcy_pacer.py": "PUBLIC_RECORDS",
    "public_faa.py": "PUBLIC_RECORDS",
    "public_npi.py": "PUBLIC_RECORDS",
    "public_nsopw.py": "PUBLIC_RECORDS",
    "public_voter.py": "PUBLIC_RECORDS",
    "gov_bop.py": "PUBLIC_RECORDS",
    "gov_epa.py": "PUBLIC_RECORDS",
    "gov_fda.py": "PUBLIC_RECORDS",
    "gov_fdic.py": "PUBLIC_RECORDS",
    "gov_fec.py": "PUBLIC_RECORDS",
    "gov_finra.py": "PUBLIC_RECORDS",
    "gov_fred.py": "PUBLIC_RECORDS",
    "gov_gleif.py": "PUBLIC_RECORDS",
    "gov_grants.py": "PUBLIC_RECORDS",
    "gov_nmls.py": "PUBLIC_RECORDS",
    "gov_osha.py": "PUBLIC_RECORDS",
    "gov_propublica.py": "PUBLIC_RECORDS",
    "gov_sam.py": "PUBLIC_RECORDS",
    "gov_usaspending.py": "PUBLIC_RECORDS",
    "gov_uspto_patents.py": "PUBLIC_RECORDS",
    "gov_uspto_trademarks.py": "PUBLIC_RECORDS",
    "gov_worldbank.py": "PUBLIC_RECORDS",
    "bis_entity_list.py": "PUBLIC_RECORDS",
    "fara_scraper.py": "PUBLIC_RECORDS",
    "icij_offshoreleaks.py": "PUBLIC_RECORDS",
    "us_corporate_registry.py": "PUBLIC_RECORDS",
    "ancestry_hints.py": "PUBLIC_RECORDS",
    "census_records.py": "PUBLIC_RECORDS",
    "geni_public.py": "PUBLIC_RECORDS",
    "newspapers_archive.py": "PUBLIC_RECORDS",
    "vitals_records.py": "PUBLIC_RECORDS",
    # FINANCIAL
    "financial_crunchbase.py": "FINANCIAL",
    "financial_finra.py": "FINANCIAL",
    "financial_worldbank.py": "FINANCIAL",
    "sec_insider.py": "FINANCIAL",
    "crypto_bitcoin.py": "FINANCIAL",
    "crypto_blockchair.py": "FINANCIAL",
    "crypto_bscscan.py": "FINANCIAL",
    "crypto_ethereum.py": "FINANCIAL",
    "crypto_polygonscan.py": "FINANCIAL",
    "mortgage_deed.py": "FINANCIAL",
    "mortgage_hmda.py": "FINANCIAL",
    # BUSINESS
    "company_companies_house.py": "BUSINESS",
    "company_opencorporates.py": "BUSINESS",
    "company_sec.py": "BUSINESS",
    "google_maps.py": "BUSINESS",
    # DARK_WEB
    "darkweb_ahmia.py": "DARK_WEB",
    "darkweb_torch.py": "DARK_WEB",
    "telegram_dark.py": "DARK_WEB",
    "paste_ghostbin.py": "DARK_WEB",
    "paste_pastebin.py": "DARK_WEB",
    "paste_psbdmp.py": "DARK_WEB",
    # PHONE_EMAIL
    "phone_carrier.py": "PHONE_EMAIL",
    "phone_fonefinder.py": "PHONE_EMAIL",
    "phone_numlookup.py": "PHONE_EMAIL",
    "phone_phoneinfoga.py": "PHONE_EMAIL",
    "phone_truecaller.py": "PHONE_EMAIL",
    "email_breach.py": "PHONE_EMAIL",
    "email_dehashed.py": "PHONE_EMAIL",
    "email_emailrep.py": "PHONE_EMAIL",
    "email_hibp.py": "PHONE_EMAIL",
    "email_holehe.py": "PHONE_EMAIL",
    "email_mx_validator.py": "PHONE_EMAIL",
    "email_socialscan.py": "PHONE_EMAIL",
    "domain_theharvester.py": "PHONE_EMAIL",
    "domain_whois.py": "PHONE_EMAIL",
    # PROPERTY
    "property_county.py": "PROPERTY",
    "property_redfin.py": "PROPERTY",
    "property_zillow.py": "PROPERTY",
    "redfin_property.py": "PROPERTY",
    "redfin_deep.py": "PROPERTY",
    "zillow_deep.py": "PROPERTY",
    "county_assessor_fl.py": "PROPERTY",
    "county_assessor_tx.py": "PROPERTY",
    "county_assessor_multi.py": "PROPERTY",
    "attom_gateway.py": "PROPERTY",
    "deed_recorder.py": "PROPERTY",
    "netronline_public.py": "PROPERTY",
    "propertyradar_scraper.py": "PROPERTY",
    "property_tax_nationwide.py": "PROPERTY",
    # VEHICLE
    "vehicle_nhtsa.py": "VEHICLE",
    "vehicle_nicb.py": "VEHICLE",
    "vehicle_ownership.py": "VEHICLE",
    "vehicle_plate.py": "VEHICLE",
    "vin_decode_enhanced.py": "VEHICLE",
    "faa_aircraft_registry.py": "VEHICLE",
    "marine_vessel.py": "VEHICLE",
    # SANCTIONS_AML
    "sanctions_australia.py": "SANCTIONS_AML",
    "sanctions_canada.py": "SANCTIONS_AML",
    "sanctions_eu.py": "SANCTIONS_AML",
    "sanctions_fatf.py": "SANCTIONS_AML",
    "sanctions_fbi.py": "SANCTIONS_AML",
    "sanctions_ofac.py": "SANCTIONS_AML",
    "sanctions_opensanctions.py": "SANCTIONS_AML",
    "sanctions_uk.py": "SANCTIONS_AML",
    "sanctions_un.py": "SANCTIONS_AML",
    "sanctions_worldbank_debarment.py": "SANCTIONS_AML",
    "open_pep_search.py": "SANCTIONS_AML",
    "world_check_mirror.py": "SANCTIONS_AML",
    # NEWS_MEDIA
    "news_search.py": "NEWS_MEDIA",
    "news_archive.py": "NEWS_MEDIA",
    "news_wikipedia.py": "NEWS_MEDIA",
    "google_news_rss.py": "NEWS_MEDIA",
    "bing_news.py": "NEWS_MEDIA",
    "gdelt_mentions.py": "NEWS_MEDIA",
    "adverse_media_search.py": "NEWS_MEDIA",
    # CYBER
    "cyber_abuseipdb.py": "CYBER",
    "cyber_alienvault.py": "CYBER",
    "cyber_crt.py": "CYBER",
    "cyber_dns.py": "CYBER",
    "cyber_greynoise.py": "CYBER",
    "cyber_shodan.py": "CYBER",
    "cyber_urlscan.py": "CYBER",
    "cyber_virustotal.py": "CYBER",
    "cyber_wayback.py": "CYBER",
    # GEOSPATIAL
    "geo_adsbexchange.py": "GEOSPATIAL",
    "geo_ip.py": "GEOSPATIAL",
    "geo_openstreetmap.py": "GEOSPATIAL",
}

# Rate limit overrides for categories (rps, burst, cooldown)
RATE_LIMITS = {
    "PEOPLE": (0.5, 3, 2.0),
    "SOCIAL_MEDIA": (0.5, 3, 1.0),
    "PUBLIC_RECORDS": (1.0, 5, 0.0),
    "FINANCIAL": (1.0, 5, 0.0),
    "BUSINESS": (1.0, 5, 0.0),
    "DARK_WEB": (0.3, 2, 5.0),
    "PHONE_EMAIL": (0.5, 3, 1.0),
    "PROPERTY": (0.5, 3, 2.0),
    "VEHICLE": (1.0, 5, 0.0),
    "SANCTIONS_AML": (2.0, 10, 0.0),
    "NEWS_MEDIA": (1.0, 5, 0.0),
    "CYBER": (1.0, 5, 0.0),
    "GEOSPATIAL": (1.0, 5, 0.0),
}

IMPORT_LINE = "from modules.crawlers.core.models import CrawlerCategory, RateLimit"


def process_file(filepath: str, category: str) -> bool:
    """Add category and rate_limit to a scraper file. Returns True if modified."""
    with open(filepath) as f:
        content = f.read()

    # Skip if already has CrawlerCategory
    if "CrawlerCategory" in content:
        return False

    lines = content.split("\n")
    new_lines = []
    import_added = False
    category_added = False

    for i, line in enumerate(lines):
        new_lines.append(line)

        # Add import after the last existing import from modules.crawlers.*
        if not import_added and line.strip().startswith(("from modules.crawlers.", "from shared.")):
            # Check if next non-empty line is NOT an import
            next_real = ""
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip():
                    next_real = lines[j].strip()
                    break
            if next_real and not next_real.startswith(("from ", "import ")):
                new_lines.append(IMPORT_LINE)
                import_added = True

        # Add category after source_reliability or platform line
        if not category_added and re.match(
            r"^\s+(source_reliability|platform)\s*=", line
        ):
            indent = re.match(r"^(\s+)", line).group(1)
            rps, burst, cooldown = RATE_LIMITS.get(category, (1.0, 5, 0.0))
            new_lines.append(
                f"{indent}category = CrawlerCategory.{category}"
            )
            new_lines.append(
                f"{indent}rate_limit = RateLimit(requests_per_second={rps}, burst_size={burst}, cooldown_seconds={cooldown})"
            )
            category_added = True

    if not import_added:
        # Insert import after the last import block
        insert_idx = 0
        for i, line in enumerate(new_lines):
            if line.strip().startswith(("from ", "import ")) and not line.strip().startswith("#"):
                insert_idx = i + 1
        new_lines.insert(insert_idx, IMPORT_LINE)

    if not category_added:
        # Fallback: find class body and insert after first class attribute
        for i, line in enumerate(new_lines):
            if re.match(r'^class \w+\(', line):
                # Find the first attribute after class definition
                for j in range(i + 1, min(i + 30, len(new_lines))):
                    if re.match(r'^\s+(platform|source_reliability|requires_tor)\s*=', new_lines[j]):
                        indent = re.match(r'^(\s+)', new_lines[j]).group(1)
                        rps, burst, cooldown = RATE_LIMITS.get(category, (1.0, 5, 0.0))
                        new_lines.insert(j + 1, f"{indent}category = CrawlerCategory.{category}")
                        new_lines.insert(j + 2, f"{indent}rate_limit = RateLimit(requests_per_second={rps}, burst_size={burst}, cooldown_seconds={cooldown})")
                        category_added = True
                        break
                break

    if not category_added:
        print(f"  WARNING: Could not add category to {filepath}")
        return False

    with open(filepath, "w") as f:
        f.write("\n".join(new_lines))

    return True


def find_scraper_files(base_dir: str):
    """Walk the crawlers directory and yield (filepath, filename) pairs."""
    for root, dirs, files in os.walk(base_dir):
        # Skip __pycache__ and core/
        dirs[:] = [d for d in dirs if d != "__pycache__" and d != "core"]
        for f in files:
            if f.endswith(".py") and not f.startswith("__"):
                yield os.path.join(root, f), f


def main():
    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "modules", "crawlers")

    modified = 0
    skipped = 0
    warnings = 0

    for filepath, filename in find_scraper_files(base_dir):
        # Skip base/infra files
        if filename in (
            "base.py", "httpx_base.py", "curl_base.py",
            "flaresolverr_base.py", "playwright_base.py", "camoufox_base.py",
            "db_writer.py", "registry.py", "result.py",
        ):
            continue

        category = CATEGORY_MAP.get(filename)
        if not category:
            # Check if it has @register
            with open(filepath) as f:
                if "@register(" not in f.read():
                    continue
            print(f"  UNMAPPED: {filepath}")
            warnings += 1
            continue

        if process_file(filepath, category):
            modified += 1
            print(f"  OK: {filepath} -> {category}")
        else:
            skipped += 1

    print(f"\nDone: {modified} modified, {skipped} already done, {warnings} warnings")


if __name__ == "__main__":
    main()
