#!/usr/bin/env python3
"""
Lycan OSINT — Gemini-powered code review.

Priority:
  1. GEMINI_API_KEY env var → direct REST API (no quota sharing, no CLI issues)
  2. Gemini CLI with cached credentials → fallback
  3. Clean error message when both unavailable

Usage:
    python scripts/gemini_review.py <diff_file> <output_file>
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

PROMPT_TEMPLATE = """You are reviewing code for the Lycan OSINT platform.

Review specifically for:

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

4. CODE QUALITY
- Missing error handling in crawlers (return found=False, not raise)
- N+1 query problems
- Unhandled async context manager leaks

Be specific — exact files and line numbers. Prioritize by severity. Skip style comments.
If the code is clean, say so briefly.

CODE TO REVIEW:
{diff}
"""


def _call_api(api_key: str, prompt: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:  # noqa: BLE001
            msg = body
        if exc.code == 429:
            return f"# Code Review — Quota Limit\n\nGemini API quota exhausted. Review skipped.\n\n> {msg}"
        return f"# Code Review — API Error {exc.code}\n\n> {msg}"


def _call_cli(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["gemini", "--prompt", prompt],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        stderr = result.stderr or ""
        if "QUOTA_EXHAUSTED" in stderr or "quota" in stderr.lower():
            return "# Code Review — Quota Limit\n\nGemini CLI quota exhausted. Review skipped until quota resets."
        return (
            f"# Code Review — CLI Error\n\nGemini CLI exited {result.returncode}. Review skipped."
        )
    except FileNotFoundError:
        return "# Code Review — Skipped\n\nGemini CLI not found."
    except subprocess.TimeoutExpired:
        return "# Code Review — Timeout\n\nGemini review timed out after 300s."
    except Exception as exc:  # noqa: BLE001
        return f"# Code Review — Error\n\n{exc}"


def main() -> None:
    diff_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pr_diff.txt"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/gemini_review_output.md"

    with open(diff_file) as f:
        diff = f.read()[:120_000]

    prompt = PROMPT_TEMPLATE.format(diff=diff)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    review = _call_api(api_key, prompt) if api_key else _call_cli(prompt)

    with open(out_file, "w") as f:
        f.write(review)
    print(review[:500])


if __name__ == "__main__":
    main()
