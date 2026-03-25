import importlib

import pytest

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.flaresolverr_base import FlareSolverrCrawler

# Crawlers migrated to FlareSolverrCrawler (HttpxCrawler-based Cloudflare targets)
FLARESOLVERR_CRAWLERS = [
    "modules.crawlers.people_thatsthem",
    "modules.crawlers.people_zabasearch",
    "modules.crawlers.paste_pastebin",
    "modules.crawlers.paste_ghostbin",
    "modules.crawlers.paste_psbdmp",
]

# Crawlers migrated to CurlCrawler (HttpxCrawler-based TLS fingerprinting targets)
CURL_CRAWLERS = [
    "modules.crawlers.email_hibp",
    "modules.crawlers.email_emailrep",
    "modules.crawlers.email_breach",
    "modules.crawlers.cyber_shodan",
    "modules.crawlers.cyber_virustotal",
    "modules.crawlers.cyber_greynoise",
    "modules.crawlers.cyber_abuseipdb",
    "modules.crawlers.cyber_urlscan",
    "modules.crawlers.cyber_crt",
    "modules.crawlers.crypto_bitcoin",
    "modules.crawlers.crypto_ethereum",
    "modules.crawlers.crypto_blockchair",
    "modules.crawlers.financial_crunchbase",
    "modules.crawlers.news_search",
    "modules.crawlers.news_wikipedia",
    "modules.crawlers.domain_whois",
    # Social platforms using HTTP requests (CurlCrawler vs CamoufoxCrawler — no get() on Camoufox)
    "modules.crawlers.twitter",
    "modules.crawlers.tiktok",
    "modules.crawlers.snapchat",
    "modules.crawlers.discord",
    "modules.crawlers.pinterest",
]


@pytest.mark.parametrize("mod_path", FLARESOLVERR_CRAWLERS)
def test_flaresolverr_tier(mod_path):
    mod = importlib.import_module(mod_path)
    crawler_cls = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, FlareSolverrCrawler) and v is not FlareSolverrCrawler
    ]
    assert crawler_cls, f"{mod_path} has no FlareSolverrCrawler subclass"


@pytest.mark.parametrize("mod_path", CURL_CRAWLERS)
def test_curl_tier(mod_path):
    mod = importlib.import_module(mod_path)
    crawler_cls = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, CurlCrawler) and v is not CurlCrawler
        and not issubclass(v, FlareSolverrCrawler)
    ]
    assert crawler_cls, f"{mod_path} has no CurlCrawler subclass"
