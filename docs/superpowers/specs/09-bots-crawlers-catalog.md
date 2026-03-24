# OSINT/Data Broker Platform — Bots, Crawlers & Scrapers Catalog

## Context
This platform serves as a government-grade OSINT (Open Source Intelligence) and data brokerage system. OSINT collection from publicly available sources is a foundational practice in national security, law enforcement, financial compliance, and corporate intelligence. Companies like Palantir ($2.7B revenue), Babel Street, Recorded Future (acquired by Mastercard for $2.65B), and LexisNexis Risk Solutions all operate in this space legally and at massive scale. Every tool listed here is free and open-source. Our goal is to exceed Palantir capabilities using only free tools — no paid APIs, no third-party SaaS dependencies.

---

## Part 1: Core Crawler Framework

### Folder Structure
```
/crawlers
├── /core                      # Base classes and interfaces
│   ├── base_crawler.py        # Abstract base — ALL crawlers extend this
│   ├── browser_crawler.py     # Playwright-based for JS-rendered sites
│   ├── api_crawler.py         # REST/GraphQL API consumers
│   ├── tor_crawler.py         # Tor-routed crawler for .onion + anonymity
│   ├── stealth_crawler.py     # Anti-detection hardened crawler
│   ├── bulk_crawler.py        # High-throughput batch crawler
│   └── streaming_crawler.py   # Real-time feed/websocket consumer
├── /anti_detection            # Evasion and stealth modules
│   ├── fingerprint_manager.py # Browser fingerprint randomization
│   ├── captcha_solver.py      # Free CAPTCHA solving (Tesseract + Whisper)
│   ├── cloudflare_bypass.py   # CF/anti-bot challenge solvers
│   ├── rate_limiter.py        # Adaptive per-domain rate limiting
│   ├── proxy_rotator.py       # Free proxy pool management
│   ├── tor_manager.py         # Tor circuit rotation
│   ├── tls_fingerprint.py     # TLS/JA3 fingerprint mimicry
│   └── session_manager.py     # Cookie/session persistence & rotation
├── /people                    # People search & identity scrapers
├── /social_media              # Social platform scrapers (ALL platforms)
├── /public_records            # Government, court, regulatory records
├── /financial                 # Financial & corporate intelligence + scoring
├── /business                  # Business intelligence & commercial data
├── /dark_web                  # .onion, I2P, deep web crawlers
├── /phone_email               # Phone/email lookup & validation
├── /property                  # Property, real estate, land records
├── /vehicle                   # Vehicle, DMV, VIN records
├── /identity                  # Identity verification & cross-reference
├── /sanctions_aml             # Sanctions, PEP, watchlists
├── /news_media                # News, media, adverse media monitoring
├── /geospatial                # Geolocation, satellite, mapping
├── /cyber                     # Cyber intelligence, breach data, IOCs
├── /monitoring                # Continuous monitoring bots
└── /data_ingestion            # Bulk import, file parsing, data feeds
```

### Base Crawler Interface

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime
from enum import Enum
import asyncio
import hashlib
import logging

class CrawlerCategory(str, Enum):
    PEOPLE = "people"
    SOCIAL_MEDIA = "social_media"
    PUBLIC_RECORDS = "public_records"
    FINANCIAL = "financial"
    BUSINESS = "business"
    DARK_WEB = "dark_web"
    PHONE_EMAIL = "phone_email"
    PROPERTY = "property"
    VEHICLE = "vehicle"
    IDENTITY = "identity"
    SANCTIONS_AML = "sanctions_aml"
    NEWS_MEDIA = "news_media"
    GEOSPATIAL = "geospatial"
    CYBER = "cyber"

class CrawlerResult(BaseModel):
    """Standard output schema for ALL crawlers."""
    source_name: str
    source_url: str
    source_reliability: float = Field(ge=0.0, le=1.0)
    category: CrawlerCategory
    entity_type: str  # person, business, property, vehicle, etc.
    raw_data: Dict[str, Any]
    normalized_data: Dict[str, Any]
    confidence_score: float = Field(ge=0.0, le=1.0)
    data_hash: str  # SHA-256 of normalized_data for dedup
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = {}

class RateLimit(BaseModel):
    requests_per_second: float
    burst_size: int
    cooldown_seconds: float = 0

class CrawlerHealth(BaseModel):
    healthy: bool
    last_check: datetime
    avg_latency_ms: float
    success_rate: float
    last_error: Optional[str] = None

class BaseCrawler(ABC):
    """Abstract base class that ALL crawlers must implement."""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._circuit_open = False
        self._consecutive_failures = 0
        self._max_failures = 5
        self._circuit_reset_time = 60

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def category(self) -> CrawlerCategory:
        ...

    @property
    @abstractmethod
    def rate_limit(self) -> RateLimit:
        ...

    @property
    @abstractmethod
    def source_reliability(self) -> float:
        ...

    @abstractmethod
    async def crawl(self, query: str, params: Dict[str, Any] = None) -> List[CrawlerResult]:
        ...

    @abstractmethod
    async def health_check(self) -> CrawlerHealth:
        ...

    async def crawl_streaming(self, query: str, params: Dict[str, Any] = None) -> AsyncGenerator[CrawlerResult, None]:
        results = await self.crawl(query, params)
        for r in results:
            yield r

    async def safe_crawl(self, query: str, params: Dict[str, Any] = None) -> List[CrawlerResult]:
        """Crawl with circuit breaker, retry, and error handling."""
        if self._circuit_open:
            self.logger.warning(f"Circuit OPEN for {self.name}, skipping")
            return []
        try:
            results = await asyncio.wait_for(
                self._retry_crawl(query, params), timeout=120.0
            )
            self._consecutive_failures = 0
            return results
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                self._circuit_open = True
                asyncio.get_event_loop().call_later(
                    self._circuit_reset_time, self._half_open_circuit
                )
            return []

    async def _retry_crawl(self, query, params, max_retries=3):
        import random
        for attempt in range(max_retries):
            try:
                return await self.crawl(query, params)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                delay = min(60, (2 ** attempt) + random.uniform(0, 1))
                await asyncio.sleep(delay)

    def _half_open_circuit(self):
        self._circuit_open = False
        self._consecutive_failures = 0

    @staticmethod
    def hash_data(data: Dict) -> str:
        import json
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## Part 2: Anti-Detection & Evasion Stack (All Free)

### Browser Stealth (Playwright)

```python
from playwright.async_api import async_playwright
import random

class BrowserCrawler(BaseCrawler):
    """Base for sites requiring JavaScript rendering."""

    async def _get_browser_context(self):
        p = await async_playwright().start()
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled',
                  '--disable-dev-shm-usage', '--no-sandbox']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=self._random_ua(),
            locale='en-US', timezone_id='America/New_York',
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
        """)
        return browser, context

    def _random_ua(self):
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        ])
```

### CAPTCHA Solving (Free — Tesseract + Whisper)

```python
import pytesseract
from PIL import Image
import whisper
import io

class FreeCaptchaSolver:
    def __init__(self):
        self.whisper_model = whisper.load_model("base")  # Runs locally, free

    async def solve_image(self, image_bytes: bytes) -> str:
        image = Image.open(io.BytesIO(image_bytes)).convert('L')
        image = image.point(lambda x: 0 if x < 128 else 255)
        return pytesseract.image_to_string(image, config='--psm 7 --oem 3').strip()

    async def solve_audio(self, audio_bytes: bytes) -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(audio_bytes)
            result = self.whisper_model.transcribe(f.name)
            return result['text'].strip()

    async def solve_recaptcha_v2(self, page) -> bool:
        """Switch to audio challenge, transcribe with Whisper."""
        try:
            frame = page.frame_locator('iframe[title="reCAPTCHA"]')
            await frame.locator('.recaptcha-checkbox-border').click()
            await asyncio.sleep(2)
            challenge = page.frame_locator('iframe[title*="recaptcha challenge"]')
            await challenge.locator('#recaptcha-audio-button').click()
            await asyncio.sleep(2)
            audio_src = await challenge.locator('.rc-audiochallenge-tdownload-link').get_attribute('href')
            async with aiohttp.ClientSession() as session:
                async with session.get(audio_src) as resp:
                    audio = await resp.read()
            answer = await self.solve_audio(audio)
            await challenge.locator('#audio-response').fill(answer)
            await challenge.locator('#recaptcha-verify-button').click()
            return True
        except Exception:
            return False
```

### Cloudflare & Anti-Bot Bypass (All Free)

```python
class CloudflareBypass:
    """5 free methods, tried in order of speed."""

    async def method_curl_cffi(self, url):
        from curl_cffi import requests
        return requests.get(url, impersonate="chrome").text

    async def method_cloudscraper(self, url):
        import cloudscraper
        return cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        ).get(url).text

    async def method_flaresolverr(self, url):
        # Self-hosted: docker run -p 8191:8191 ghcr.io/flaresolverr/flaresolverr
        async with aiohttp.ClientSession() as session:
            async with session.post("http://localhost:8191/v1",
                json={"cmd": "request.get", "url": url, "maxTimeout": 60000}
            ) as resp:
                return (await resp.json())["solution"]["response"]

    async def method_playwright_stealth(self, url):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='networkidle')
            content = await page.content()
            await browser.close()
            return content

    async def method_undetected_chrome(self, url):
        import undetected_chromedriver as uc
        driver = uc.Chrome(headless=True)
        driver.get(url)
        html = driver.page_source
        driver.quit()
        return html

    async def adaptive_bypass(self, url):
        """Try all methods, fastest first, fallback on failure."""
        for name, method in [
            ("curl_cffi", self.method_curl_cffi),
            ("cloudscraper", self.method_cloudscraper),
            ("flaresolverr", self.method_flaresolverr),
            ("playwright", self.method_playwright_stealth),
            ("undetected", self.method_undetected_chrome),
        ]:
            try:
                result = await asyncio.wait_for(method(url), timeout=30)
                if result and len(result) > 500:
                    return result
            except Exception:
                continue
        raise Exception(f"All bypass methods failed for {url}")
```

### Free Proxy Rotation

```python
class FreeProxyManager:
    SOURCES = [
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]
    SOCKS_SOURCES = [
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    ]

    def __init__(self):
        self.pool = []
        self.blacklist = set()

    async def refresh(self):
        proxies = []
        async with aiohttp.ClientSession() as session:
            for url in self.SOURCES:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        for line in (await resp.text()).strip().split('\n'):
                            p = line.strip()
                            if p and ':' in p and p not in self.blacklist:
                                proxies.append(p)
                except Exception:
                    continue
        tested = await asyncio.gather(*[self._test(p) for p in proxies[:200]])
        self.pool = [p for p in tested if p]

    async def _test(self, proxy):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get('http://httpbin.org/ip', proxy=f'http://{proxy}',
                    timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        return proxy
        except Exception:
            return None

    def get(self):
        return f'http://{random.choice(self.pool)}' if self.pool else None
```

### Tor Routing

```python
class TorCrawler(BaseCrawler):
    """Route through Tor for .onion access and IP anonymity."""

    async def _fetch_via_tor(self, url, socks_port=9050):
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(f'socks5://127.0.0.1:{socks_port}')
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return await resp.text()

    async def _new_circuit(self, control_port=9051):
        from stem import Signal
        from stem.control import Controller
        with Controller.from_port(port=control_port) as c:
            c.authenticate()
            c.signal(Signal.NEWNYM)
            await asyncio.sleep(5)
```

---

## Part 3: Complete Scraper Catalog — 145+ Free Scrapers

### Category A: People Search & Identity (20 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 1 | TruePeopleSearch | truepeoplesearch.com | Name, address, phone, email, relatives, associates | Browser | 0.85 |
| 2 | FastPeopleSearch | fastpeoplesearch.com | Name, address, phone, age, relatives | Browser | 0.80 |
| 3 | ThatsThem | thatsthem.com | Name, address, phone, email, IP | Browser | 0.75 |
| 4 | WhitePages Public | whitepages.com | Name, address, phone, age | Browser+CF | 0.85 |
| 5 | Zabasearch | zabasearch.com | Name, address, phone | HTTP | 0.70 |
| 6 | PeekYou | peekyou.com | Social profiles, web presence, age | Browser | 0.70 |
| 7 | Webmii | webmii.com | Web visibility score, social profiles | HTTP | 0.65 |
| 8 | Voter Records | 50 state sites | Name, address, DOB, party, voter history | HTTP/Browser | 0.95 |
| 9 | Obituary Search | legacy.com, tributes.com | Death records, family, locations | HTTP | 0.90 |
| 10 | FamilySearch | familysearch.org | Birth, death, marriage, family trees | API (free) | 0.90 |
| 11 | FindAGrave | findagrave.com | Death records, burial, family connections | HTTP | 0.90 |
| 12 | SSA Death Master | NTIS/SSA | SSN, name, DOB, death date, residence | Bulk file | 0.99 |
| 13 | NSOPW (Sex Offenders) | nsopw.gov | Name, photo, address, offenses | API (free) | 0.99 |
| 14 | BOP Inmate Locator | bop.gov | Federal inmates: name, facility, release | HTTP | 0.99 |
| 15 | State Prison Locators | 50 state DOC sites | State inmates: name, charges, release | Browser | 0.95 |
| 16 | FBI Most Wanted | fbi.gov | Wanted persons, suspects, missing persons | API (free) | 0.99 |
| 17 | Interpol Red Notices | interpol.int | International wanted persons | API (free) | 0.99 |
| 18 | US Marshals Fugitives | usmarshals.gov | Wanted fugitives, rewards, last location | HTTP | 0.99 |
| 19 | NamUs Missing Persons | namus.nij.ojp.gov | Missing and unidentified persons | HTTP | 0.99 |
| 20 | Immigration Court | justice.gov | Immigration case status | HTTP | 0.90 |

### Category B: Social Media Intelligence — ALL Platforms (20 Scrapers)

| # | Scraper | Source | Data Returned | Tool/Library | Reliability |
|---|---------|--------|---------------|-------------|-------------|
| 21 | Sherlock | 400+ sites | Username existence across platforms | sherlock-project | 0.90 |
| 22 | Maigret | 2500+ sites | Username + profile data across platforms | maigret | 0.92 |
| 23 | Instaloader | Instagram | Profile, posts, followers, stories, highlights, IGTV, tagged, comments, likes | instaloader | 0.85 |
| 24 | snscrape/Twint | Twitter/X | Tweets, followers, following, likes, profile, media, replies, quote tweets | snscrape | 0.75 |
| 25 | Reddit PRAW | Reddit | Post history, comment history, karma, subreddits, awards, saved, gilded | PRAW API | 0.95 |
| 26 | TikTok Scraper | TikTok | Profile, videos, likes, followers, following, sounds, hashtags, comments | TikTok-Api | 0.70 |
| 27 | YouTube Data | YouTube | Channel stats, videos, comments, playlists, subscribers, about, community posts | YT Data API | 0.95 |
| 28 | GitHub OSINT | GitHub | Profile, repos, commits, email from commits, stars, followers, orgs, gists | GitHub API | 0.95 |
| 29 | LinkedIn Public | LinkedIn | Profile, job history, education, skills, certifications, recommendations | Browser scrape | 0.65 |
| 30 | Telegram OSINT | Telegram | Public channels, messages, group membership, forwarded message sources | Telethon | 0.80 |
| 31 | Discord OSINT | Discord | Server membership, messages, roles, connections, linked accounts | discord.py | 0.70 |
| 32 | Pinterest | Pinterest | Boards, pins, interests, followers, following | Browser | 0.65 |
| 33 | Mastodon/Fediverse | Mastodon | Posts, followers, instance data, profile | Mastodon API | 0.85 |
| 34 | Snapchat Public | Snapchat | Public stories, Snap Map, display name | Browser | 0.50 |
| 35 | GHunt | Google | Google account info, Maps reviews, Photos, Calendar, YouTube, Gmail indicators | GHunt | 0.80 |
| 36 | Facebook Public | Facebook | Public posts, groups, events, friends list (if public), about, photos | Browser | 0.60 |
| 37 | WhatsApp OSINT | WhatsApp | Profile photo, about text, online status, group membership indicators | Browser | 0.50 |
| 38 | Twitch | Twitch | Stream history, VODs, clips, followers, subscriptions, chat activity | Twitch API | 0.85 |
| 39 | Steam OSINT | Steam | Game library, playtime, friends, groups, profile | Steam API | 0.80 |
| 40 | Spotify Public | Spotify | Public playlists, following, listening activity | Spotify API | 0.70 |

### Category C: Public Records & Government (25 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 41 | SEC EDGAR | sec.gov | 10-K, 10-Q, 8-K, proxy, insider trades (Form 4), ownership (13D/G) | API (free) | 0.99 |
| 42 | FEC Campaign Finance | fec.gov | Contributions, PAC data, expenditures, committee data | API (free) | 0.99 |
| 43 | PACER Courts | pacer.gov | Federal court filings, cases, dockets, judgments | HTTP | 0.95 |
| 44 | State Courts (50) | 50 state sites | State case records, filings, judgments, sentences | Browser | 0.90 |
| 45 | USPTO Patents | patft.uspto.gov | Patent filings, grants, assignments, inventors, claims | API (free) | 0.99 |
| 46 | USPTO Trademarks | tsdr.uspto.gov | Trademark registrations, applications, owners, opposition | API (free) | 0.99 |
| 47 | Sec of State (All 50) | state SoS sites | Business registrations, officers, agents, filings, status | Browser | 0.95 |
| 48 | UCC Filings | state UCC sites | Secured transaction filings, debtors, creditors | Browser | 0.90 |
| 49 | County Recorder (3000+) | county sites | Deeds, mortgages, liens, releases, transfers, easements | Browser | 0.90 |
| 50 | County Assessor (3000+) | county sites | Property values, tax assessments, owner, legal description | Browser | 0.90 |
| 51 | Federal Register | federalregister.gov | Regulations, rules, notices, executive orders | API (free) | 0.99 |
| 52 | USASpending | usaspending.gov | Government contracts, grants, loans, spending by agency | API (free) | 0.99 |
| 53 | Grants.gov | grants.gov | Federal grant opportunities and awards | API (free) | 0.99 |
| 54 | FDA Databases | fda.gov | Drug approvals, recalls, inspections, warning letters, adverse events | API (free) | 0.99 |
| 55 | OSHA Inspections | osha.gov | Workplace inspections, violations, penalties, fatalities | API (free) | 0.99 |
| 56 | EPA Enforcement | echo.epa.gov | Environmental violations, inspections, penalties, permits | API (free) | 0.99 |
| 57 | SAM.gov | sam.gov | Government contractors, excluded parties, entity registrations | API (free) | 0.99 |
| 58 | Congressional Records | congress.gov | Bills, votes, member info, committees, hearings | API (free) | 0.99 |
| 59 | Senate Financial Disc. | efdsearch.senate.gov | Senator/candidate financial disclosures, assets, transactions | Browser | 0.95 |
| 60 | House Financial Disc. | disclosures.house.gov | House member financial disclosures | Browser | 0.95 |
| 61 | IRS 990 (Nonprofits) | ProPublica API | Nonprofit financials, compensation, grants, missions | API (free) | 0.95 |
| 62 | Professional Licenses | 50 state boards | Doctors, lawyers, contractors, nurses, CPAs, real estate agents | Browser | 0.90 |
| 63 | DEA Registrations | deadiversion.usdoj.gov | DEA registrant lookup — controlled substance handlers | HTTP | 0.95 |
| 64 | NPI Registry | nppes.cms.hhs.gov | Healthcare provider NPI lookup, specialties, addresses | API (free) | 0.99 |
| 65 | FOIA Libraries | agency FOIA sites | FOIA-released documents, correspondence, investigations | HTTP | 0.95 |

### Category D: Financial & Corporate Intelligence (20 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 66 | OpenCorporates | opencorporates.com | Global company data (200M+ companies, officers, filings) | API (free tier) | 0.85 |
| 67 | FRED (Federal Reserve) | fred.stlouisfed.org | Economic indicators, interest rates, GDP, CPI, unemployment | API (free) | 0.99 |
| 68 | World Bank Open Data | data.worldbank.org | Country economic data, development indicators | API (free) | 0.99 |
| 69 | GLEIF (Legal Entity ID) | gleif.org | LEI data, entity relationships, ownership chains, hierarchy | API (free) | 0.95 |
| 70 | Blockchain (BTC) | blockchain.com API | Bitcoin transactions, wallet balances, address clustering | API (free) | 0.95 |
| 71 | Etherscan | etherscan.io | Ethereum transactions, token balances, contract interactions | API (free) | 0.95 |
| 72 | Polygonscan | polygonscan.com | Polygon chain transactions and balances | API (free) | 0.90 |
| 73 | BSCScan | bscscan.com | Binance Smart Chain transactions | API (free) | 0.90 |
| 74 | OpenSanctions | opensanctions.org | Sanctions, PEPs, wanted persons (40+ lists unified) | API/Bulk (free) | 0.90 |
| 75 | Google Maps/Places | maps.google.com | Business info, reviews, hours, contact, photos, rating | Browser | 0.85 |
| 76 | Yelp | yelp.com | Business reviews, ratings, categories, hours | Browser | 0.80 |
| 77 | BBB | bbb.org | Accreditation, complaints, ratings, alerts | Browser | 0.85 |
| 78 | Glassdoor | glassdoor.com | Company reviews, salaries, interview data, CEO rating | Browser+CF | 0.70 |
| 79 | Indeed Jobs | indeed.com | Job postings (implies company health/growth/hiring) | Browser | 0.75 |
| 80 | Crunchbase Public | crunchbase.com | Startup funding, founders, investors, acquisitions | Browser | 0.75 |
| 81 | ProPublica Nonprofit | projects.propublica.org | IRS 990 data, nonprofit financials, officers, grants | API (free) | 0.95 |
| 82 | FDIC BankFind | fdic.gov | Bank data, branches, financial statements, enforcement | API (free) | 0.99 |
| 83 | NMLS Consumer Access | nmlsconsumeraccess.org | Mortgage lender/broker license, enforcement actions | HTTP | 0.95 |
| 84 | FINRA BrokerCheck | brokercheck.finra.org | Broker/advisor records, complaints, disciplinary history | HTTP | 0.95 |
| 85 | FinCEN BSA Filings | fincen.gov | Beneficial ownership data (Corporate Transparency Act) | API (when live) | 0.99 |

### Category E: Sanctions, AML & Watchlists (12 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 86 | OFAC SDN List | ofac.treasury.gov | US sanctions — names, aliases, addresses, IDs, vessels | API/Bulk (free) | 0.99 |
| 87 | OFAC Consolidated | ofac.treasury.gov | All OFAC programs consolidated | Bulk XML (free) | 0.99 |
| 88 | EU Sanctions | data.europa.eu | EU restrictive measures — persons and entities | API (free) | 0.99 |
| 89 | UN Sanctions | un.org | UN Security Council consolidated list | XML (free) | 0.99 |
| 90 | UK HMT Sanctions | gov.uk/hmt | UK financial sanctions targets | CSV/XML (free) | 0.99 |
| 91 | Australia DFAT | dfat.gov.au | Australian sanctions list | CSV (free) | 0.99 |
| 92 | Canada OSFI | osfi-bsif.gc.ca | Canadian sanctions and terrorist lists | CSV (free) | 0.99 |
| 93 | OpenSanctions Unified | opensanctions.org | 40+ global lists: sanctions, PEPs, crime, wanted | API/Bulk (free) | 0.95 |
| 94 | FATF Lists | fatf-gafi.org | Grey/black list high-risk jurisdictions | HTTP scrape | 0.99 |
| 95 | CIA World Factbook | cia.gov | Country intel — leadership, economy, military, threats | HTTP (free) | 0.99 |
| 96 | Transparency Intl | transparency.org | Corruption Perception Index by country | HTTP (free) | 0.95 |
| 97 | World Bank Debarment | worldbank.org | Debarred firms and individuals | HTTP (free) | 0.99 |

### Category F: Dark Web & Deep Web Intelligence (10 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 98 | Ahmia Search | ahmia.fi | Tor hidden service search engine | Tor HTTP | 0.70 |
| 99 | OnionScan | github onionscan | .onion analysis — security leaks, identity exposure | Tor + analysis | 0.75 |
| 100 | HIBP (Have I Been Pwned) | haveibeenpwned.com | Email/password breach data, breach timelines | API (free) | 0.95 |
| 101 | Dehashed (free tier) | dehashed.com | Breach data search, credentials, hashes | API (free tier) | 0.80 |
| 102 | Paste Site Monitor | pastebin + alternatives | Leaked data, credentials, PII | HTTP polling | 0.70 |
| 103 | IntelX (free tier) | intelx.io | Dark web, paste, leak data, phonebooks | API (free tier) | 0.75 |
| 104 | Tor Directory Scanner | custom | Discover new .onion services | Tor crawler | 0.60 |
| 105 | I2P Crawler | i2p network | I2P eepsite content | I2P router | 0.50 |
| 106 | Dark Web Forum Monitor | .onion forums | Threat intel, credential sales, fraud | Tor Browser | 0.65 |
| 107 | Ransomware Leak Monitor | .onion | Victim data, leaked corporate docs | Tor Browser | 0.70 |

### Category G: Geospatial & Physical Intelligence (10 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 108 | OpenStreetMap | overpass-api.de | Building footprints, POIs, roads, boundaries | API (free) | 0.90 |
| 109 | Google Earth/Maps | google.com/maps | Satellite imagery, street view, location data | Browser | 0.90 |
| 110 | Wigle.net | wigle.net | WiFi network mapping, SSID geolocation | API (free) | 0.75 |
| 111 | ADS-B Exchange | adsbexchange.com | Aircraft tracking, flight history, registration | API (free) | 0.90 |
| 112 | MarineTraffic | marinetraffic.com | Vessel AIS data, port calls, ownership, routes | HTTP | 0.80 |
| 113 | EXIF Extractor | local (exiftool) | GPS, camera model, timestamps, software from photos | Local tool | 0.95 |
| 114 | OpenCellID | opencellid.org | Cell tower locations for geolocation | API (free) | 0.80 |
| 115 | IP Geolocation | ip-api.com | IP → city/country, ISP, organization, ASN | API (free) | 0.85 |
| 116 | Sentinel Hub | sentinel-hub.com | Satellite imagery (Copernicus, Sentinel) | API (free tier) | 0.85 |
| 117 | NASA EOSDIS | earthdata.nasa.gov | Earth observation data, weather, terrain | API (free) | 0.90 |

### Category H: Cyber Intelligence (12 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 118 | Shodan (free tier) | shodan.io | Internet devices, open ports, vulns, banners | API (free) | 0.90 |
| 119 | Censys (free tier) | censys.io | TLS certs, hosts, services, cloud assets | API (free) | 0.90 |
| 120 | WHOIS Lookup | whois databases | Domain registrant, creation/expiry, nameservers | whois protocol | 0.90 |
| 121 | DNS Enumeration | custom | Subdomains, A/AAAA/MX/TXT/NS records, zone transfers | dnspython | 0.85 |
| 122 | Certificate Transparency | crt.sh | SSL certificates, subdomains, issuers, timeline | API (free) | 0.95 |
| 123 | SecurityTrails (free) | securitytrails.com | Historical DNS, WHOIS, subdomains, associated domains | API (free) | 0.85 |
| 124 | VirusTotal (free) | virustotal.com | Malware analysis, URL scanning, IP/domain reputation | API (free) | 0.90 |
| 125 | AbuseIPDB | abuseipdb.com | IP reputation, abuse reports, categories | API (free) | 0.85 |
| 126 | URLScan | urlscan.io | Website analysis, screenshots, DOM, linked resources | API (free) | 0.85 |
| 127 | Wayback Machine | web.archive.org | Historical website snapshots, changes over time | API (free) | 0.85 |
| 128 | GreyNoise | greynoise.io | Internet scanner/attacker IP intelligence | API (free) | 0.85 |
| 129 | AlienVault OTX | otx.alienvault.com | Threat indicators (IOCs), pulses, reputation | API (free) | 0.85 |

### Category I: Phone & Email Intelligence (10 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 130 | PhoneInfoga | github phoneinfoga | Carrier, location, social accounts from phone | Free tool | 0.80 |
| 131 | Truecaller Public | truecaller.com | Caller ID, spam detection, name lookup | Browser | 0.75 |
| 132 | EmailRep | emailrep.io | Reputation score, breach presence, deliverability, age | API (free) | 0.85 |
| 133 | Holehe | github holehe | Email → which sites have accounts registered | Free tool | 0.85 |
| 134 | MX/SMTP Validator | custom | MX records, SMTP handshake, catch-all detection | DNS/SMTP | 0.90 |
| 135 | Disposable Email DB | github lists | Detect throwaway/temporary email domains | Free list | 0.95 |
| 136 | CallerID Databases | various | Reverse phone, carrier, line type, name | HTTP/Browser | 0.70 |
| 137 | NumLookup | numlookup.com | Free reverse phone lookup, carrier data | HTTP | 0.75 |
| 138 | Epieos | epieos.com | Email → Google account info, registered services | HTTP | 0.80 |
| 139 | Eye of God alternative | custom | Aggregated phone/email intelligence | Multi-source | 0.75 |

### Category J: Property & Vehicle (10 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 140 | Zillow Public | zillow.com | Property values, Zestimate, history, tax, photos | Browser | 0.80 |
| 141 | Redfin Public | redfin.com | Listings, sold data, market trends, history | Browser | 0.80 |
| 142 | Realtor.com | realtor.com | Listings, property details, neighborhood data | Browser | 0.80 |
| 143 | County Assessor (3000+) | county sites | Tax assessments, legal description, owner, improvements | Browser | 0.90 |
| 144 | County Recorder (3000+) | county sites | Deeds, mortgages, liens, releases, UCC | Browser | 0.90 |
| 145 | NHTSA VIN Decoder | nhtsa.gov | Vehicle specs, recalls, complaints, crash data | API (free) | 0.99 |
| 146 | NICB VINCheck | nicb.org | Theft, salvage, total loss from VIN | HTTP (free) | 0.90 |
| 147 | State DMV Public | state DMV sites | Vehicle registration (where public) | Browser | 0.85 |
| 148 | FMCSA/DOT | safer.fmcsa.dot.gov | Commercial vehicle/carrier data, safety records | HTTP | 0.95 |
| 149 | FAA Registry | faa.gov | Aircraft registration, owner, airworthiness | HTTP (free) | 0.99 |

### Category K: News & Media Intelligence (8 Scrapers)

| # | Scraper | Source | Data Returned | Method | Reliability |
|---|---------|--------|---------------|--------|-------------|
| 150 | GDELT Project | gdeltproject.org | Global news events, tone, themes, locations, actors | API/BigQuery | 0.90 |
| 151 | Google News | news.google.com | News articles, headlines, trending | Browser | 0.80 |
| 152 | NewsAPI (free tier) | newsapi.org | News from 80,000+ sources | API (free) | 0.85 |
| 153 | MediaCloud | mediacloud.org | Media ecosystem analysis, story tracking, influence | API (free) | 0.80 |
| 154 | RSS Aggregator | various RSS | Real-time news monitoring from RSS feeds | HTTP | 0.85 |
| 155 | Common Crawl | commoncrawl.org | Petabytes of web crawl data (entire web archive) | S3 (free) | 0.80 |
| 156 | Wikipedia/Wikidata | wikidata.org | Structured entity data, biographical info, relationships | API (free) | 0.90 |
| 157 | Archive.org | archive.org | Historical web pages, books, media, government docs | API (free) | 0.85 |

### Category L: Continuous Monitoring Bots (12 Bots)

| # | Bot | Function | Frequency |
|---|-----|----------|-----------|
| 158 | Court Filing Monitor | New case filings for person/entity | Every 6 hours |
| 159 | Property Transfer Monitor | New deeds, liens, transfers | Daily |
| 160 | SEC Filing Monitor | New corporate filings | Real-time RSS |
| 161 | Sanctions List Monitor | Additions/removals to sanctions | Every 4 hours |
| 162 | Adverse Media Monitor | Negative news mentions | Every 2 hours |
| 163 | Social Media Monitor | New posts, profile changes | Every hour |
| 164 | Domain/WHOIS Monitor | Domain ownership/expiry changes | Daily |
| 165 | Breach Notification Bot | New data breaches | Every hour |
| 166 | Corporate Filing Monitor | Business filings, officer changes | Daily |
| 167 | Death Record Monitor | SSA Death Master File updates | Weekly |
| 168 | Price/Value Monitor | Property value and financial changes | Weekly |
| 169 | Change Detection Bot | Any web page content changes | Configurable (changedetection.io) |

---

## Part 4: OSINT Frameworks (All-in-One Free Tools)

### 1. SpiderFoot (free, open-source) — RECOMMENDED
- 200+ modules for automated OSINT collection
- Web UI dashboard
- Automated correlation between entities
- Export CSV, JSON, GEXF (graph)
- `pip install spiderfoot`

### 2. Recon-ng (free)
- Modular reconnaissance framework
- 100+ modules for different data sources
- Database-backed result storage
- API key management for free-tier services

### 3. Maltego CE (Community Edition — free)
- Visual link analysis and entity transformation
- Graph-based relationship mapping
- Community transforms (free)

### 4. theHarvester (free)
- Email, subdomain, host, name discovery
- Multiple search engine backends

### 5. Photon (free)
- High-speed web crawler for OSINT
- Extracts URLs, emails, social accounts, files

### 6. Metagoofil (free)
- Metadata extractor from public documents
- Finds usernames, software versions, email addresses

### 7. ExifTool (free)
- EXIF/metadata from images and files
- GPS coordinates, camera data, timestamps

### 8. Twint (free) — Twitter intelligence
- No API required, scrapes directly
- Advanced Twitter OSINT

---

## Part 5: Massive Data Ingestion Architecture

### Bulk Data Sources (Free, High-Volume)

| Source | Volume | Format | Update Frequency |
|--------|--------|--------|-----------------|
| Common Crawl | 250TB+ per crawl | WARC | Monthly |
| GDELT | 750M+ events | CSV/BigQuery | Real-time (15min) |
| OpenSanctions | 500K+ entities | JSON/CSV | Daily |
| SEC EDGAR Full Index | Millions of filings | HTML/XML | Real-time |
| Census Data | 330M+ person records | CSV | Annual |
| FEC Bulk Data | Millions of contributions | CSV | Weekly |
| USPTO Bulk Data | Millions of patents | XML | Weekly |
| OFAC Sanctions | 10,000+ entities | XML/CSV | Daily |
| SSA Death Master | Millions of records | Fixed-width | Monthly |
| GeoNames | 25M+ locations | CSV | Daily |
| OpenStreetMap | 8B+ nodes | PBF/XML | Real-time |
| OpenCorporates Bulk | 200M+ companies | JSON | Monthly |
| Wikidata | 100M+ entities | JSON | Real-time |

### Ingestion Pipeline

```
Data Sources (169 scrapers + bulk feeds)
         │
         ▼
┌─────────────────────┐
│  Ingestion Gateway   │  ← Rate limit, schema validation, dedup check
└──────────┬──────────┘
           │
    ┌──────┼──────┐
    │      │      │
    ▼      ▼      ▼
 Stream   Batch   Bulk
 (Redis)  (Temp)  (DuckDB)
    │      │      │
    └──────┼──────┘
           ▼
┌─────────────────────┐
│  Entity Resolution   │  ← 4-pass dedup (see doc 03)
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Enrichment Engine   │  ← Tags, scores, verify (see docs 05, 06, 10)
└──────────┬──────────┘
           │
    ┌──────┼──────┐
    ▼      ▼      ▼
 Postgres  ES    Qdrant
 (primary) (FTS) (vector)
```

### Ingestion Performance Targets

| Metric | Target |
|--------|--------|
| Real-time ingestion | 10,000 records/sec |
| Bulk import | 1M records/min |
| Dedup check | < 1ms per record |
| End-to-end latency | < 500ms (scrape → searchable) |

---

## Part 6: Adding a New Scraper (5 Steps)

1. **Create file** in appropriate category folder
2. **Extend BaseCrawler**, implement `crawl()` and `health_check()`
3. **Register** in scraper registry (`CRAWLER_REGISTRY`)
4. **Write tests** with mock data
5. **Deploy** — hot-reload capable, no restart needed

---

## Summary

**Total scrapers: 169**
- 20 People Search & Identity
- 20 Social Media (ALL platforms)
- 25 Public Records & Government
- 20 Financial & Corporate
- 12 Sanctions & AML
- 10 Dark Web & Deep Web
- 10 Geospatial
- 12 Cyber Intelligence
- 10 Phone & Email
- 10 Property & Vehicle
- 8 News & Media
- 12 Continuous Monitoring Bots

**All free. All open-source. All follow the same BaseCrawler interface.**
**Exceeds Palantir's public data collection scope using zero paid tools.**
