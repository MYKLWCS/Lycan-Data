# Lycan-Data

## What This Is

Recursive people-intelligence OSINT platform for Rand Financial Holdings. Search by any identifier (name, email, phone, username, domain, crypto wallet), crawl 181+ sources in parallel, build complete person profiles with identity resolution, family tree construction, and enrichment scoring. Government/enterprise grade, 100% open-source tools.

## Core Value

Given any piece of identifying information about a person, find and connect EVERYTHING — all identifiers, social profiles, addresses, employment, property, criminal records, financial data, relationships, and family tree — into one unified record.

## Requirements

### Validated

- ✓ Multi-identifier search (name, email, phone, username, domain, crypto) — existing
- ✓ 181 crawler implementations across 17 categories — existing
- ✓ Event-driven pipeline (search → dispatch → crawl → ingest → enrich) — existing
- ✓ Cross-type identity resolution (5-step: exact → cross-type → name → fuzzy → Typesense) — existing
- ✓ Enrichment scoring (9-component formula) — existing
- ✓ Progress tracking via SSE (0→100% with phase transitions) — existing
- ✓ Family tree with relationship fallback — existing
- ✓ Manual identifier linking API — existing
- ✓ 47 bidirectional Person model relationships — existing
- ✓ Docker Compose with 11 services — existing
- ✓ 6005 passing tests — existing

### Active

- [ ] Bypass Cloudflare-blocked people-search sites (WhitePages, FastPeopleSearch, TruePeopleSearch)
- [ ] Phone number discovery from name searches
- [ ] Address discovery from name searches
- [ ] Employment/education data from LinkedIn
- [ ] Social media profile photos (Instagram, Facebook)
- [ ] Automatic recursive growth (search → discover identifiers → search again → until exhausted)
- [ ] Family tree population from discovered relatives
- [ ] Enrichment score > 80% for persons with publicly available data
- [ ] Real-time progress showing discovered data as it arrives

### Out of Scope

- Paid API services (Pipl, FullContact, BeenVerified) — budget constraint
- Mobile app — web-first
- Multi-tenant SaaS — single-organization deployment
- Real-time surveillance/monitoring — batch intelligence only

## Context

- Stack: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL+AGE, Garnet (Redis), Typesense, Tor, Playwright
- 15+ audit rounds applied, 65+ files changed, 62+ bugs fixed
- Primary data gap: Cloudflare Enterprise blocks the 3 highest-value people-search sites
- Residential proxy support wired in but no proxy service configured
- Wikidata integration working (extracts DOB, social handles for notable persons)
- 3 new free crawlers added: Gravatar, Wikidata, Open Library

## Constraints

- **Budget**: No paid services — free/open-source tools only
- **Licensing**: No AGPL or BSL — MIT, Apache 2.0, BSD, GPL-2/3, LGPL-3 only
- **Infrastructure**: Single server (ASUS Gryphon Z87, i7-4770, 32GB DDR3, Ubuntu 24.04)
- **Browser**: Playwright + patchright (NOT Nodriver). Typesense (NOT MeiliSearch)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Garnet over Redis | Multi-threaded, Microsoft-backed, Redis-compatible | ✓ Good |
| Typesense over MeiliSearch | BSL 1.1 license banned for government | ✓ Good |
| Tor for anonymity | 3 independent circuits for IP rotation | ⚠️ Revisit (Cloudflare blocks Tor) |
| FlareSolverr for bypass | Free Cloudflare solver | ⚠️ Revisit (doesn't work for Enterprise CF) |
| Residential proxy tier | Configured but no provider | — Pending |

---
*Last updated: 2026-03-30 after GSD initialization*
