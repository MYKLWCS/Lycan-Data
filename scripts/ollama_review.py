#!/usr/bin/env python3
"""
Lycan OSINT — Ollama-powered PR code review.

Usage:
    python scripts/ollama_review.py <diff_file> <output_file>
"""

import json
import sys
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"

PROMPT_TEMPLATE = """You are reviewing a pull request for the Lycan OSINT platform.

Review this PR diff specifically for:

1. DATA QUALITY BUGS
- Crawlers returning consent/GDPR pages as real data
- Platform suffixes not stripped from display names
- False positive found=True results
- Pivot enricher running on garbage strings

2. PIPELINE CORRECTNESS
- source_reliability values overwritten by apply_quality_to_model
- Person.full_name set from garbage display_names
- Enrichment orchestrator steps not persisting to Person model
- Missing transaction rollbacks on DB errors

3. SECURITY
- SQL injection risks in raw queries
- Unvalidated user input reaching crawler URLs
- Secrets hardcoded in code
- Tor bypass scenarios where real IPs could leak

4. SPEC COMPLIANCE
- Features required by lycan-osint-spec.md that are missing or stubbed

5. CODE QUALITY
- Missing error handling in crawlers (return found=False, not raise)
- N+1 query problems
- Unhandled async context manager leaks

Be specific. Point to exact files and line numbers.
Prioritize by severity. Skip style/formatting comments.
If the diff is clean, say so briefly.

PR DIFF:
{diff}
"""


def main() -> None:
    diff_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pr_diff.txt"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/review_output.md"

    with open(diff_file) as f:
        diff = f.read()[:12000]

    prompt = PROMPT_TEMPLATE.format(diff=diff)
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            review = result.get("response", "").strip()
    except urllib.error.URLError as exc:
        review = f"Ollama unavailable ({exc}) — automated review skipped."
    except Exception as exc:  # noqa: BLE001
        review = f"Ollama error ({exc}) — automated review skipped."

    with open(out_file, "w") as f:
        f.write(review)
    print(review[:500])


if __name__ == "__main__":
    main()
