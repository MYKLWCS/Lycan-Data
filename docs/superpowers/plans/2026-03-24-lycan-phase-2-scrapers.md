# Lycan Phase 2: Scrapers, Enrichment & Government Data

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** Build all scraping, enrichment, and government database modules. Every module is plug-and-play: one file = one source. Add a new source in 5 minutes. Every algorithm is auditable.

**Architecture:** Registry pattern — each scraper/enricher self-registers. Dispatcher routes jobs to registered handlers. Results flow through a unified pipeline → DB. Sorting/ranking runs on every result set before persistence.

**Tech Stack:** Python 3.12, Playwright (stealth), Scrapy + httpx, Telethon, PRAW, Holehe/Sherlock/theHarvester (subprocess), stem (Tor), BeautifulSoup4, asyncpg, SQLAlchemy async

**Modularity Principle:** Every scraper is ~100-150 lines max. If it grows, split it. Every signal is a named float in a dataclass. Every registry entry is one line.

---

## Tasks

### Task 1: Crawler Registry + Base Classes
### Task 2: Instagram Scraper
### Task 3: Facebook Scraper
### Task 4: Twitter/X Scraper (via nitter)
### Task 5: TikTok Scraper
### Task 6: LinkedIn Scraper
### Task 7: Reddit Scraper (PRAW)
### Task 8: YouTube Scraper
### Task 9: Telegram Probe (Telethon + web)
### Task 10: WhatsApp Probe
### Task 11: Snapchat + Pinterest + GitHub + Discord Scrapers
### Task 12: Phone Enrichment (CarrierLookup + Fonefinder + TrueCaller)
### Task 13: Burner Detector
### Task 14: Email Enrichment (Holehe + HIBP)
### Task 15: Username Enumeration (Sherlock)
### Task 16: People Search Scrapers (Whitepages, FastPeopleSearch, TruePeopleSearch)
### Task 17: Domain OSINT (theHarvester + WHOIS)
### Task 18: Crypto Tracer (Blockchain.info, Etherscan, Blockchair)
### Task 19: Dark Web - Onion Search (Ahmia + Torch)
### Task 20: Dark Web - Paste Monitor
### Task 21: Dark Web - Telegram Channel Scanner
### Task 22: Sanctions & Watchlists (OFAC, UN, EU, FBI, Interpol)
### Task 23: Court Records (CourtListener + state courts)
### Task 24: Company Registries (OpenCorporates, Companies House, SEC EDGAR, CIPC)
### Task 25: Property Records
### Task 26: Public Records (voter, licenses, FAA, NSOPW)
### Task 27: Crawl Job Dispatcher
### Task 28: Growth Daemon
### Task 29: Freshness Scheduler
### Task 30: Result Ranking & Sorting Engine
