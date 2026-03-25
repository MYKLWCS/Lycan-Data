# Lycan OSINT Platform — Build Context

## What This Is
Recursive people-intelligence OSINT + data broker platform for Rand Financial Holdings.
Government/enterprise grade. 100% free open-source tools.

## Critical Rules
- NO AGPL licensed tools (banned for government). NO BSL licensed tools.
- Only MIT, Apache 2.0, BSD, MPL 2.0, GPL-2/3, LGPL-3 (dynamic link only).
- Playwright + playwright-stealth (NOT Nodriver). Typesense (NOT MeiliSearch).
- ALL scrapers must extend BaseCrawler interface (see docs/specs/09-bots-crawlers-catalog.md).
- ALL scrapers must run async parallel with asyncio.gather(), never sequential.
- Every scraper needs: circuit breaker, retry with backoff, error handling, health check.
- Every search must emit SSE progress events.
- Zero duplicates — bloom filter + 4-pass entity resolution.

## Stack
- Python 3.12+ (Rust via PyO3 for hot paths in future)
- PostgreSQL 16 + Apache AGE (graph)
- Microsoft Garnet (Redis-compatible cache)
- Typesense (instant search)
- Qdrant (vector embeddings)
- Dramatiq + Apache Pulsar (task queue)
- Playwright + playwright-stealth (browser automation)
- FastAPI (API server)
- SSE for progress, WebSocket optional

## Spec Docs
All specs are in docs/specs/. Read 00-MASTER-SPEC.md first.
The audit of current bugs is in docs/specs/14-deep-code-audit.md.