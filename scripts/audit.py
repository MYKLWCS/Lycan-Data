#!/usr/bin/env python3
"""
Lycan OSINT Platform — Automated System Audit

Scans the codebase against lycan-osint-spec.md, identifies stubs,
gaps, and bugs, then uses a local Ollama model to generate a prioritised
issue report and posts it as a GitHub Issue.

Run locally:  python scripts/audit.py
Run in CI:    triggered by .github/workflows/audit.yml
"""

import json
import os
import re
import subprocess
import sys
from datetime import timezone, datetime
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
SPEC_FILE = ROOT / "lycan-osint-spec.md"
CRAWLERS_DIR = ROOT / "modules" / "crawlers"
ENRICHERS_DIR = ROOT / "modules" / "enrichers"
PIPELINE_DIR = ROOT / "modules" / "pipeline"
API_DIR = ROOT / "api"
SHARED_DIR = ROOT / "shared"
TESTS_DIR = ROOT / "tests"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")

# ──────────────────────────────────────────────────────────────────────────────
# 1. Static Scanners
# ──────────────────────────────────────────────────────────────────────────────

STUB_PATTERNS = [
    (re.compile(r"\bNotImplementedError\b"), "NotImplementedError raised"),
    (re.compile(r"\bpass\b\s*$", re.M), "bare pass statement"),
    (re.compile(r"return\s+\{\}\s*$", re.M), "returns empty dict"),
    (re.compile(r"return\s+\[\]\s*$", re.M), "returns empty list"),
    (re.compile(r"return\s+None\s*$", re.M), "returns None unconditionally"),
    (re.compile(r"#\s*TODO", re.I), "TODO comment"),
    (re.compile(r"#\s*FIXME", re.I), "FIXME comment"),
    (re.compile(r"#\s*STUB", re.I), "STUB comment"),
    (re.compile(r"#\s*PLACEHOLDER", re.I), "PLACEHOLDER comment"),
    (re.compile(r'raise\s+Exception\("not implemented', re.I), "not-implemented exception"),
]

CONSENT_PAGE_PATTERNS = [
    re.compile(r"before you continue", re.I),
    re.compile(r"bevor sie zu", re.I),
    re.compile(r"cookie.*consent", re.I),
]

# Platforms that should be in CRAWLER_REGISTRY based on SEED_PLATFORM_MAP
EXPECTED_CRAWLERS_FROM_SPEC = {
    # Social
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
    "mastodon",
    "twitch",
    "steam",
    # Phone
    "phone_carrier",
    "phone_truecaller",
    "phone_numlookup",
    "whatsapp",
    # Email
    "email_hibp",
    "email_holehe",
    "email_leakcheck",
    "email_emailrep",
    # People search
    "whitepages",
    "fastpeoplesearch",
    "truepeoplesearch",
    # Sanctions
    "sanctions_ofac",
    "sanctions_un",
    "sanctions_fbi",
    "sanctions_eu",
    "sanctions_uk",
    "sanctions_opensanctions",
    # Court/legal
    "court_courtlistener",
    # Dark web
    "darkweb_ahmia",
    "paste_pastebin",
    # Domain/IP/Crypto
    "domain_whois",
    "ip_geolocation",
    "crypto_bitcoin",
    # Username sweep
    "username_sherlock",
    # Government
    "public_npi",
    "public_faa",
    # Company
    "company_opencorporates",
    "company_sec",
}

# Enrichers required by spec
REQUIRED_ENRICHERS = {
    "financial_aml",  # credit score, AML screening
    "burner_detector",  # phone burner detection
    "verification",  # multi-source verification
    "deduplication",  # entity dedup
    "ranking",  # importance scoring
    "biographical",  # biographical data extraction
    "marketing_tags",  # behavioural tags
    "psychological",  # psychological profiling
}

# Required API endpoints
REQUIRED_ENDPOINTS = {
    "/search": "POST search endpoint",
    "/persons": "persons listing",
    "/system/health": "health check",
    "/system/queues": "queue stats",
    "/graph": "graph data",
    "/export": "PDF/CSV export",
    "/enrich": "manual enrichment trigger",
    "/watchlist": "watchlist management",
    "/alerts": "alerts system",
    "/compliance": "compliance checks",
}


def scan_file_for_stubs(path: Path) -> list[dict]:
    """Return list of stub findings in a Python file."""
    findings = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        for pattern, description in STUB_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                findings.append(
                    {
                        "file": str(path.relative_to(ROOT)),
                        "line": line_no,
                        "issue": description,
                        "snippet": content[match.start() : match.start() + 80].strip(),
                    }
                )
    except Exception:
        pass
    return findings


def get_registered_crawlers() -> set[str]:
    """Parse crawler files to find all @register('x') decorators."""
    registered = set()
    for f in CRAWLERS_DIR.glob("*.py"):
        try:
            content = f.read_text()
            for match in re.finditer(r'@register\(["\'](\w+)["\']', content):
                registered.add(match.group(1))
        except Exception:
            pass
    return registered


def get_registered_enrichers() -> set[str]:
    """Return enricher module names in modules/enrichers/."""
    enrichers = set()
    for f in ENRICHERS_DIR.glob("*.py"):
        if f.name.startswith("_"):
            continue
        enrichers.add(f.stem)
    return enrichers


def check_test_coverage() -> dict:
    """Run pytest --collect-only to count collected tests per module."""
    try:
        result = subprocess.run(
            [
                "python",
                "-m",
                "pytest",
                "tests/",
                "--collect-only",
                "-q",
                "--ignore=tests/test_crawlers",
                "--ignore=tests/test_darkweb",
                "--ignore=tests/test_government",
                "--no-header",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=60,
        )
        lines = result.stdout.splitlines()
        total = sum(1 for l in lines if "::" in l)
        return {"total_tests": total, "output": result.stdout[:2000]}
    except Exception as e:
        return {"total_tests": 0, "error": str(e)}


def check_pipeline_wiring() -> list[dict]:
    """Check that pipeline stages are properly connected."""
    issues = []

    # Check ingestion daemon imports pivot_enricher
    ingestion = (PIPELINE_DIR / "ingestion_daemon.py").read_text()
    if "pivot_from_result" not in ingestion:
        issues.append(
            {
                "severity": "HIGH",
                "component": "ingestion_daemon",
                "issue": "pivot_from_result not called — pivot chain broken",
            }
        )
    if "enrich_person" not in ingestion:
        issues.append(
            {
                "severity": "HIGH",
                "component": "ingestion_daemon",
                "issue": "enrich_person not called — risk scores never computed",
            }
        )

    # Check dispatcher pushes source_reliability
    dispatcher = (ROOT / "modules" / "dispatcher" / "dispatcher.py").read_text()
    if "source_reliability" not in dispatcher:
        issues.append(
            {
                "severity": "HIGH",
                "component": "dispatcher",
                "issue": "source_reliability not passed in ingest payload",
            }
        )

    # Check aggregator updates corroboration
    aggregator = (PIPELINE_DIR / "aggregator.py").read_text()
    if "corroboration_count" not in aggregator:
        issues.append(
            {
                "severity": "MEDIUM",
                "component": "aggregator",
                "issue": "corroboration_count never incremented on Person",
            }
        )

    # Check enrichment orchestrator writes back to Person
    orch = (PIPELINE_DIR / "enrichment_orchestrator.py").read_text()
    if "default_risk_score" not in orch and "financial_aml" not in orch:
        issues.append(
            {
                "severity": "HIGH",
                "component": "enrichment_orchestrator",
                "issue": "risk scores not written back to Person model",
            }
        )

    return issues


def check_crawler_quality() -> list[dict]:
    """Check crawlers for known data quality anti-patterns."""
    issues = []

    youtube = (CRAWLERS_DIR / "youtube.py").read_text()
    if "consent" not in youtube.lower() and "before you continue" not in youtube.lower():
        issues.append(
            {
                "severity": "HIGH",
                "component": "youtube_crawler",
                "issue": "No consent page detection — GDPR redirect returns garbage display_name",
            }
        )

    snapchat = (CRAWLERS_DIR / "snapchat.py").read_text()
    if "sur snapchat" not in snapchat.lower() and "on snapchat" not in snapchat.lower():
        issues.append(
            {
                "severity": "HIGH",
                "component": "snapchat_crawler",
                "issue": "No OG title suffix stripping — 'Name sur Snapchat' stored as full_name",
            }
        )

    whatsapp = (CRAWLERS_DIR / "whatsapp.py").read_text()
    if "invalid_phone" not in whatsapp and "len(digits)" not in whatsapp:
        issues.append(
            {
                "severity": "HIGH",
                "component": "whatsapp_crawler",
                "issue": "No phone validation — accepts usernames, returns false positive found=True",
            }
        )

    # Check pivot enricher rejects garbage names
    pivot = (PIPELINE_DIR / "pivot_enricher.py").read_text()
    if "youtube" not in pivot.lower() and "snapchat" not in pivot.lower():
        issues.append(
            {
                "severity": "HIGH",
                "component": "pivot_enricher",
                "issue": "No platform-word rejection — pivots on 'Juliana Bentel sur Snapchat'",
            }
        )

    return issues


def check_source_reliability() -> list[dict]:
    """Check SOURCE_RELIABILITY dict covers all registered crawlers."""
    issues = []
    try:
        constants = (SHARED_DIR / "constants.py").read_text()
        # Extract keys from SOURCE_RELIABILITY dict
        match = re.search(r"SOURCE_RELIABILITY[^{]+\{(.+?)\}", constants, re.DOTALL)
        if match:
            keys_block = match.group(1)
            keys = set(re.findall(r'"(\w+)":', keys_block))
            missing_platforms = []
            for crawler in ["snapchat", "youtube", "whatsapp", "reddit", "discord", "twitch"]:
                if not any(k in crawler or crawler in k for k in keys):
                    missing_platforms.append(crawler)
            if missing_platforms:
                issues.append(
                    {
                        "severity": "HIGH",
                        "component": "constants.SOURCE_RELIABILITY",
                        "issue": f"Missing platforms fall back to unknown=0.20: {missing_platforms}",
                    }
                )
    except Exception as e:
        issues.append({"severity": "LOW", "component": "constants", "issue": str(e)})
    return issues


def check_api_endpoints() -> list[dict]:
    """Check required API endpoints are registered."""
    issues = []
    try:
        main_py = (API_DIR / "main.py").read_text()
        routes_dir = API_DIR / "routes"
        all_route_content = " ".join(f.read_text() for f in routes_dir.glob("*.py"))
        for endpoint, description in REQUIRED_ENDPOINTS.items():
            # Simple check: endpoint path appears somewhere in routes
            path_part = endpoint.lstrip("/").split("/")[0]
            if path_part not in main_py and path_part not in all_route_content:
                issues.append(
                    {
                        "severity": "MEDIUM",
                        "component": f"api/{endpoint}",
                        "issue": f"Required endpoint '{endpoint}' ({description}) may be missing",
                    }
                )
    except Exception as e:
        issues.append({"severity": "LOW", "component": "api", "issue": str(e)})
    return issues


def get_git_stats() -> dict:
    """Get git activity stats."""
    try:
        log = subprocess.run(
            ["git", "log", "--oneline", "-20"], capture_output=True, text=True, cwd=ROOT
        ).stdout
        files_changed = subprocess.run(
            ["git", "diff", "--stat", "HEAD~5", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout
        return {"recent_commits": log, "recent_changes": files_changed[:1000]}
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# 2. Aggregate All Findings
# ──────────────────────────────────────────────────────────────────────────────


def run_full_audit() -> dict:
    print("Starting Lycan OSINT audit...")

    # Scan for stubs
    stub_findings = []
    for py_file in ROOT.rglob("*.py"):
        if any(skip in str(py_file) for skip in [".venv", "__pycache__", "migrations", "tests"]):
            continue
        stub_findings.extend(scan_file_for_stubs(py_file))

    # Crawler registry check
    registered_crawlers = get_registered_crawlers()
    missing_crawlers = EXPECTED_CRAWLERS_FROM_SPEC - registered_crawlers
    registered_crawlers - EXPECTED_CRAWLERS_FROM_SPEC

    # Enricher check
    registered_enrichers = get_registered_enrichers()
    missing_enrichers = REQUIRED_ENRICHERS - registered_enrichers

    # Pipeline wiring
    pipeline_issues = check_pipeline_wiring()

    # Crawler quality
    quality_issues = check_crawler_quality()

    # Source reliability gaps
    reliability_issues = check_source_reliability()

    # API endpoints
    api_issues = check_api_endpoints()

    # Tests
    test_stats = check_test_coverage()

    # Git stats
    git_stats = get_git_stats()

    # Summary counts
    high_severity = sum(
        1
        for i in pipeline_issues + quality_issues + reliability_issues + api_issues
        if i.get("severity") == "HIGH"
    )
    stubs_count = len(
        [
            f
            for f in stub_findings
            if f["issue"] in ("NotImplementedError raised", "STUB comment", "PLACEHOLDER comment")
        ]
    )

    audit_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "registered_crawlers": len(registered_crawlers),
            "missing_crawlers": sorted(missing_crawlers),
            "missing_enrichers": sorted(missing_enrichers),
            "stub_count": stubs_count,
            "todo_count": len([f for f in stub_findings if "TODO" in f["issue"]]),
            "high_severity_issues": high_severity,
            "total_tests": test_stats.get("total_tests", 0),
        },
        "pipeline_issues": pipeline_issues,
        "crawler_quality_issues": quality_issues,
        "reliability_issues": reliability_issues,
        "api_issues": api_issues,
        "top_stubs": stub_findings[:30],
        "git_stats": git_stats,
    }

    print(
        f"Audit complete: {high_severity} HIGH severity issues, "
        f"{len(missing_crawlers)} missing crawlers, "
        f"{stubs_count} stubs found"
    )
    return audit_result


# ──────────────────────────────────────────────────────────────────────────────
# 3. Ollama Analysis
# ──────────────────────────────────────────────────────────────────────────────


def generate_ollama_analysis(audit_data: dict, spec_excerpt: str) -> str:
    """Use a local Ollama model to generate a prioritised, actionable audit report."""
    import urllib.error
    import urllib.request

    prompt = f"""You are auditing the Lycan OSINT platform codebase against its spec.

Here is the spec summary (first 3000 chars):
{spec_excerpt[:3000]}

Here is the automated audit data:
{json.dumps(audit_data, indent=2, default=str)[:8000]}

Write a comprehensive GitHub Issue report with these sections:

## 🔴 Critical Issues (blocking real data flow)
List what is ACTUALLY broken right now that prevents the system from working.
For each issue: what is broken, why it matters, the exact fix needed.

## 🟡 Spec Gaps (built vs required)
What does the spec require that is not yet built or is a stub?
Be specific: "Section X.Y requires Z — current implementation does Y instead."

## 🟢 What Is Working
What actually works correctly? Give credit where due.

## 📊 Build Completeness
Estimate overall completion: X% of spec implemented, with breakdown by section.

## 🛠 Prioritised Fix List
Ordered list of what to fix first for maximum impact.

Use markdown. Be direct. No filler text. Focus on actionable findings.
"""

    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            return result.get("response", "")
    except urllib.error.URLError as exc:
        return f"Ollama unavailable ({exc}) — skipping AI analysis."
    except Exception as exc:  # noqa: BLE001
        return f"Ollama error ({exc}) — skipping AI analysis."


# ──────────────────────────────────────────────────────────────────────────────
# 4. Post GitHub Issue
# ──────────────────────────────────────────────────────────────────────────────


def post_github_issue(title: str, body: str) -> str | None:
    """Create or update a pinned audit issue on GitHub. Returns issue URL."""
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("No GITHUB_TOKEN or GITHUB_REPOSITORY — skipping issue creation")
        return None

    try:
        from github import Github

        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPOSITORY)

        # Find existing audit issue to update
        existing = None
        for issue in repo.get_issues(state="open", labels=["audit"]):
            if "System Audit" in issue.title:
                existing = issue
                break

        if existing:
            existing.edit(title=title, body=body)
            print(f"Updated existing audit issue: {existing.html_url}")
            return existing.html_url
        else:
            # Create audit label if it doesn't exist
            try:
                repo.get_label("audit")
            except Exception:
                repo.create_label("audit", "e11d48", "Automated system audit")

            issue = repo.create_issue(
                title=title,
                body=body,
                labels=["audit"],
            )
            print(f"Created audit issue: {issue.html_url}")
            return issue.html_url

    except Exception as e:
        print(f"Failed to post GitHub issue: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 5. Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    audit_data = run_full_audit()

    # Read spec for context
    spec_excerpt = ""
    if SPEC_FILE.exists():
        spec_excerpt = SPEC_FILE.read_text()[:5000]

    # Generate AI analysis
    print("Generating Ollama analysis...")
    ai_report = generate_ollama_analysis(audit_data, spec_excerpt)

    # Build full report
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M timezone.utc")
    s = audit_data["summary"]

    header = f"""# 🔍 Lycan OSINT — Automated System Audit
**Generated:** {now}
**Crawlers registered:** {s["registered_crawlers"]}
**Missing crawlers:** {len(s["missing_crawlers"])} ({", ".join(s["missing_crawlers"][:10]) or "none"})
**Missing enrichers:** {len(s["missing_enrichers"])} ({", ".join(s["missing_enrichers"]) or "none"})
**Stubs found:** {s["stub_count"]}
**TODO comments:** {s["todo_count"]}
**Tests collected:** {s["total_tests"]}
**High severity issues:** {s["high_severity_issues"]}

---

"""

    pipeline_section = ""
    if audit_data["pipeline_issues"]:
        pipeline_section = "\n## ⚠️ Pipeline Wiring Issues\n"
        for issue in audit_data["pipeline_issues"]:
            pipeline_section += (
                f"- `[{issue['severity']}]` **{issue['component']}**: {issue['issue']}\n"
            )

    quality_section = ""
    if audit_data["crawler_quality_issues"]:
        quality_section = "\n## 🐛 Crawler Quality Issues\n"
        for issue in audit_data["crawler_quality_issues"]:
            quality_section += (
                f"- `[{issue['severity']}]` **{issue['component']}**: {issue['issue']}\n"
            )

    full_report = header + pipeline_section + quality_section + "\n---\n\n" + ai_report

    # Add raw data appendix
    full_report += f"""

---
<details>
<summary>Raw audit data</summary>

```json
{json.dumps({k: v for k, v in audit_data.items() if k != "top_stubs"}, indent=2, default=str)[:3000]}
```
</details>
"""

    # Save report locally
    report_path = ROOT / "audit_report.md"
    report_path.write_text(full_report)
    print(f"Report saved to {report_path}")

    # Post to GitHub
    title = f"System Audit — {datetime.now(timezone.utc).strftime('%Y-%m-%d')} | {s['high_severity_issues']} critical issues"
    url = post_github_issue(title, full_report[:65000])

    if url:
        print(f"\nAudit issue: {url}")
    else:
        print("\n--- AUDIT REPORT ---")
        print(full_report[:3000])

    # Exit with error if critical issues found
    if s["high_severity_issues"] > 0:
        print(f"\n⚠️  {s['high_severity_issues']} high-severity issues found")
        sys.exit(0)  # Don't fail CI — just report


if __name__ == "__main__":
    main()
