#!/usr/bin/env python
"""
Lycan CLI — OSINT search runner.

Usage:
    python lycan.py --name "John Smith"
    python lycan.py --username "jsmith99"
    python lycan.py --phone "+12025551234"
    python lycan.py --email "john@example.com"
    python lycan.py --vin "1HGBH41JXMN109186"
    python lycan.py --domain "example.com"
    python lycan.py --name "John Smith" --no-tor  (skip Tor-required scrapers)
    python lycan.py --name "John Smith" --only github,reddit,news_search
"""

import argparse
import asyncio
import importlib
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))
logger = logging.getLogger("lycan.cli")


# ── Colour helpers ────────────────────────────────────────────────────────────
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def GREEN(t):
    return _c("92", t)


def YELLOW(t):
    return _c("93", t)


def CYAN(t):
    return _c("96", t)


def RED(t):
    return _c("91", t)


def BOLD(t):
    return _c("1", t)


def DIM(t):
    return _c("2", t)


def BLUE(t):
    return _c("94", t)


# ── Auto-import all crawler modules so they self-register ─────────────────────
def _import_all_crawlers() -> list[str]:
    import os

    import modules.crawlers as pkg

    loaded = []
    base_path = pkg.__path__[0]
    for root, dirs, files in os.walk(base_path):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "core")]
        for fname in files:
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            rel = os.path.relpath(os.path.join(root, fname), base_path)
            module_name = f"modules.crawlers.{rel.replace(os.sep, '.').removesuffix('.py')}"
            try:
                importlib.import_module(module_name)
                loaded.append(module_name.split(".")[-1])
            except Exception:
                logger.exception("Crawler import failed: %s", module_name)
    return loaded


# ── Decide which crawlers to run for a given identifier type ──────────────────
PLATFORM_MAP = {
    "username": [
        "instagram",
        "twitter",
        "reddit",
        "github",
        "youtube",
        "tiktok",
        "linkedin",
        "facebook",
        "snapchat",
        "pinterest",
        "discord",
        "telegram",
        "whatsapp",
        "username_sherlock",
    ],
    "phone": [
        "phone_carrier",
        "phone_fonefinder",
        "phone_truecaller",
        "whatsapp",
        "telegram",
    ],
    "email": [
        "email_hibp",
        "email_holehe",
    ],
    "name": [
        "whitepages",
        "fastpeoplesearch",
        "truepeoplesearch",
        "people_thatsthem",
        "people_zabasearch",
        "idcrawl",
        "freepeoplesearch",
        "google_people_search",
        "sanctions_ofac",
        "sanctions_un",
        "sanctions_fbi",
        "court_courtlistener",
        "company_opencorporates",
        "company_sec",
        "public_npi",
        "public_faa",
        "public_nsopw",
        "vehicle_ownership",
        "news_search",
        "obituary_search",
    ],
    "vin": ["vehicle_nhtsa"],
    "domain": ["domain_whois", "domain_harvester"],
    "crypto": ["crypto_bitcoin", "crypto_ethereum", "crypto_blockchair"],
}

# Scrapers that require Tor (skip when --no-tor)
REQUIRES_TOR = {
    "instagram",
    "facebook",
    "tiktok",
    "linkedin",
    "snapchat",
    "pinterest",
    "discord",
    "whatsapp",
    "phone_carrier",
    "phone_fonefinder",
    "phone_truecaller",
    "email_holehe",
    "darkweb_ahmia",
    "darkweb_torch",
    "paste_pastebin",
    "paste_ghostbin",
    "paste_psbdmp",
    "telegram_dark",
    "property_zillow",
    "property_county",
    "vehicle_plate",
    "vehicle_ownership",
    "mortgage_deed",
    "domain_whois",
    "obituary_search",
    "news_search",
    "google_maps",
    "court_state",
}

# Scrapers that call subprocesses (skip if tool not installed)
SUBPROCESS_SCRAPERS = {
    "username_sherlock": "sherlock",
    "email_holehe": "holehe",
    "domain_harvester": "theHarvester",
}


def _check_tool(tool: str) -> bool:
    import shutil

    return shutil.which(tool) is not None


# ── Result formatter ──────────────────────────────────────────────────────────
def _print_result(platform: str, result, elapsed: float) -> None:
    status = GREEN("FOUND") if result.found else DIM("not found")
    print(f"  {BOLD(platform):<30} {status}  {DIM(f'{elapsed:.1f}s')}")

    if not result.found:
        if result.error:
            print(f"    {DIM('→')} {DIM(result.error[:120])}")
        return

    data = result.data or {}
    # Print the most interesting fields
    interesting = [
        "name",
        "display_name",
        "full_name",
        "username",
        "handle",
        "follower_count",
        "following_count",
        "bio",
        "carrier_name",
        "line_type",
        "is_burner",
        "balance_btc",
        "balance_eth",
        "breach_count",
        "breaches",
        "found_on",
        "site_count",
        "cases",
        "case_count",
        "matches",
        "match_count",
        "result_count",
        "results",
        "make",
        "model",
        "year",
        "vin",
        "total_loans",
        "median_loan_amount",
        "articles",
        "article_count",
        "locations",
        "providers",
        "pilots",
        "offenders",
    ]
    shown = 0
    for key in interesting:
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            if not val:
                continue
            # Show first 2 items
            preview = json.dumps(val[:2], default=str)
            if len(val) > 2:
                preview = preview[:-1] + f", ... +{len(val) - 2} more]"
            print(f"    {CYAN(key)}: {preview}")
        elif isinstance(val, (dict,)):
            print(f"    {CYAN(key)}: {json.dumps(val, default=str)[:120]}")
        else:
            print(f"    {CYAN(key)}: {val}")
        shown += 1
        if shown >= 6:
            remaining = len([k for k in data if k not in interesting[: interesting.index(key) + 1]])
            if remaining:
                print(f"    {DIM(f'... +{len(data) - shown} more fields')}")
            break


# ── Main runner ───────────────────────────────────────────────────────────────
async def run_search(
    identifier: str,
    id_type: str,
    no_tor: bool = False,
    only: list[str] | None = None,
    concurrency: int = 8,
) -> None:
    from modules.crawlers.registry import get_crawler

    platforms = only or PLATFORM_MAP.get(id_type, [])

    # Filter
    to_run = []
    skipped = []
    for p in platforms:
        if no_tor and p in REQUIRES_TOR:
            skipped.append((p, "requires Tor"))
            continue
        tool = SUBPROCESS_SCRAPERS.get(p)
        if tool and not _check_tool(tool):
            skipped.append((p, f"{tool} not installed"))
            continue
        crawler_cls = get_crawler(p)
        if not crawler_cls:
            skipped.append((p, "not registered"))
            continue
        to_run.append(p)

    print()
    print(BOLD(f"  Lycan OSINT — {id_type.upper()}: {CYAN(identifier)}"))
    print(
        f"  {DIM(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}  "
        f"Running {GREEN(str(len(to_run)))} scrapers"
        + (f"  {DIM(f'({len(skipped)} skipped)')}" if skipped else "")
    )
    print()

    # Run in batches for concurrency limit
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(platform: str):
        async with sem:
            crawler_cls = get_crawler(platform)
            crawler = crawler_cls()
            t0 = time.monotonic()
            try:
                result = await crawler.run(identifier)
            except Exception as exc:
                from modules.crawlers.core.result import CrawlerResult

                result = CrawlerResult(
                    platform=platform,
                    identifier=identifier,
                    found=False,
                    error=str(exc),
                )
            elapsed = time.monotonic() - t0
            return platform, result, elapsed

    tasks = [asyncio.create_task(_run_one(p)) for p in to_run]

    found_count = 0
    for coro in asyncio.as_completed(tasks):
        platform, result, elapsed = await coro
        _print_result(platform, result, elapsed)
        if result.found and result.data:
            found_count += 1

    print()
    print(
        f"  {BOLD('Summary:')} {GREEN(str(found_count))} sources returned data "
        f"out of {len(to_run)} scrapers run."
    )

    if skipped:
        print(f"\n  {BOLD('Skipped:')}")
        for name, reason in skipped:
            print(f"    {DIM(name):<30} {DIM(reason)}")

    # ── Psychological profile if posts/bio text collected ──────────────────
    # Collect any bio/description text from results for analysis
    texts = []
    for task in tasks:
        try:
            _, res, _ = task.result()
            bio = (res.data or {}).get("bio") or (res.data or {}).get("description", "")
            if bio:
                texts.append(str(bio))
        except Exception:
            pass

    if texts and sum(len(t.split()) for t in texts) >= 20:
        print()
        print(BOLD("  Psychological Profile (from scraped bio/post text):"))
        from modules.enrichers.biographical import build_biographical_profile
        from modules.enrichers.psychological import build_psychological_profile

        psych = build_psychological_profile(texts)
        bio_profile = build_biographical_profile(texts)

        if psych.confidence > 0:
            ocean = {
                "O": psych.openness,
                "C": psych.conscientiousness,
                "E": psych.extraversion,
                "A": psych.agreeableness,
                "N": psych.neuroticism,
            }
            ocean_str = "  ".join(f"{k}={CYAN(f'{v:.2f}')}" for k, v in ocean.items())
            print(f"    OCEAN: {ocean_str}  {DIM(f'(confidence {psych.confidence:.0%})')}")

            if psych.emotional_triggers:
                print(f"    Triggers: {YELLOW(', '.join(psych.emotional_triggers))}")
            if psych.dominant_themes:
                print(f"    Themes:   {', '.join(psych.dominant_themes)}")
            if psych.product_predispositions:
                print(f"    Products: {BLUE(', '.join(psych.product_predispositions[:5]))}")
            flags = []
            if psych.financial_stress_language:
                flags.append(RED("financial-stress"))
            if psych.gambling_language:
                flags.append(RED("gambling"))
            if psych.substance_language:
                flags.append(RED("substance"))
            if flags:
                print(f"    Risk:     {', '.join(flags)}")

        if bio_profile.dob:
            print(
                f"    DOB:      {CYAN(str(bio_profile.dob))} {DIM(f'(conf {bio_profile.dob_confidence:.0%})')}"
            )
        if bio_profile.marital_status:
            print(f"    Marital:  {bio_profile.marital_status}")

    print()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Lycan OSINT — recursive people intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", metavar="NAME", help='Full name, e.g. "John Smith"')
    group.add_argument("--username", metavar="USER", help="Username across platforms")
    group.add_argument("--phone", metavar="PHONE", help="Phone number (E.164 or plain)")
    group.add_argument("--email", metavar="EMAIL", help="Email address")
    group.add_argument("--vin", metavar="VIN", help="Vehicle VIN (17 chars)")
    group.add_argument("--domain", metavar="DOMAIN", help="Domain name")
    group.add_argument("--crypto", metavar="ADDR", help="Crypto wallet (btc:addr or eth:addr)")

    parser.add_argument("--no-tor", action="store_true", help="Skip scrapers that require Tor")
    parser.add_argument(
        "--only", metavar="SCRAPERS", help="Comma-separated scraper list, e.g. github,reddit"
    )
    parser.add_argument("--jobs", type=int, default=8, help="Concurrent scrapers (default 8)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead")

    args = parser.parse_args()

    # Determine identifier type and value
    if args.name:
        id_type, identifier = "name", args.name
    elif args.username:
        id_type, identifier = "username", args.username
    elif args.phone:
        id_type, identifier = "phone", args.phone
    elif args.email:
        id_type, identifier = "email", args.email
    elif args.vin:
        id_type, identifier = "vin", args.vin.upper()
    elif args.domain:
        id_type, identifier = "domain", args.domain
    else:
        id_type, identifier = "crypto", args.crypto

    # Auto-import all crawlers
    _import_all_crawlers()

    only = [s.strip() for s in args.only.split(",")] if args.only else None

    asyncio.run(
        run_search(
            identifier=identifier,
            id_type=id_type,
            no_tor=args.no_tor,
            only=only,
            concurrency=args.jobs,
        )
    )


if __name__ == "__main__":
    main()
