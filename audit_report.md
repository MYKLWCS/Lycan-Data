# 🔍 Lycan OSINT — Automated System Audit
**Generated:** 2026-03-25 02:01 UTC
**Crawlers registered:** 121
**Missing crawlers:** 5 (email_leakcheck, ip_geolocation, mastodon, steam, twitch)
**Missing enrichers:** 0 (none)
**Stubs found:** 2
**TODO comments:** 0
**Tests collected:** 0
**High severity issues:** 0

---


---

Ollama unavailable (HTTP Error 404: Not Found) — skipping AI analysis.

---
<details>
<summary>Raw audit data</summary>

```json
{
  "timestamp": "2026-03-25T02:01:18.768553+00:00",
  "summary": {
    "registered_crawlers": 121,
    "missing_crawlers": [
      "email_leakcheck",
      "ip_geolocation",
      "mastodon",
      "steam",
      "twitch"
    ],
    "missing_enrichers": [],
    "stub_count": 2,
    "todo_count": 0,
    "high_severity_issues": 0,
    "total_tests": 0
  },
  "pipeline_issues": [],
  "crawler_quality_issues": [],
  "reliability_issues": [],
  "api_issues": [],
  "git_stats": {
    "recent_commits": "a23ad3e Add comprehensive tests for coverage gaps in crawlers, enrichers, and shared modules\n12c9914 fix(search): add .lower() normalization to _auto_detect_type, add 3 SeedTypes, wire 6 new crawlers to SEED_PLATFORM_MAP\n81db58d fix(db): swap UniqueConstraint to normalized_value, backfill NOT NULL \u2014 deploy atomically with migration\na823735 fix(health,transport): dragonfly connection leak + incr fallback + counter reset after promotion\n918e2f5 feat(shared): add Dragonfly-backed transport registry with auto-promotion after 3 blocks\n2b700e4 feat(shared): add bypass-layer health check for startup diagnostics\n8e1839a feat(crawlers): add CamoufoxCrawler using Firefox stealth browser\n6cd3f32 fix(crawlers): fix import order and unused variable in flaresolverr test\nb313a05 feat(crawlers): add FlareSolverrCrawler with class-level health cache and 60s negative TTL\nafb10ec Add FlareSolverrCrawler for Cloudflare JS-challenge bypass\n69b7b20 merge: feat/crawler-overhaul into master\n1973e0d feat(crawlers): wave3 test suite and crawler/enricher fixes\nfcd5149 fix(crawlers): fix lint in curl_base test\n992ac76 feat(crawlers): add CurlCrawler with Chrome 130 TLS fingerprint impersonation\ncc6e725 fix(crawlers): make is_blocked async, use self.USER_AGENTS, remove unused import\n3670ea8 docs: add Phase 7 \u2014 family tree builder to platform overhaul spec\n77916e5 feat(crawlers): upgrade playwright_base to patchright with Chrome 130+ UAs and full nav patches\n89a39e6 feat(infra): add FlareSolverr sidecar service\n9bad719 docs: fix spec review issues in platform overhaul design\ndabff7a feat(deps): add stealth transport libs; phoneinfoga requires Go binary install\n",
    "recent_changes": " api/routes/search.py                               |   19 +-\n .../2026-03-25-phase2-contact-intelligence-card.md | 1593 +++++++++++\n .../plans/2026-03-25-phase3-knowledge-graph-d3.md  | 1844 +++++++++++++\n .../plans/2026-03-25-phase6-in-app-audit.md        | 1623 +++++++++++\n .../plans/2026-03-25-phase7-family-tree.md         | 2840 ++++++++++++++++++++\n ...0862064daa56_normalize_identifier_constraint.py |   56 +\n shared/constants.py                                |    3 +\n shared/health.py                                   |    8 +-\n shared/models/identifier.py                        |    4 +-\n shared/transport_registry.py                       |   92 +\n tests/test_api/test_api_main_wave3.py              |  301 +++\n tests/test_api/test_api_wave3.py           
```
</details>
