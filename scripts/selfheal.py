#!/usr/bin/env python3
"""
Self-healing test runner for Lycan-Data.

Runs the test suite, diagnoses failures, applies known fixes, and re-runs to verify.

Usage:
  python scripts/selfheal.py           # diagnose + heal
  python scripts/selfheal.py --report  # health summary only, no fixes
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

PYTEST_CMD_FULL = [
    ".venv/bin/python",
    "-m",
    "pytest",
    "tests/",
    "--tb=short",
    "-q",
]

PYTEST_CMD_COVERAGE = [
    ".venv/bin/python",
    "-m",
    "pytest",
    "tests/",
    "--tb=short",
    "-q",
    "--cov=.",
    "--cov-report=term-missing",
]

FIXES_APPLIED = []


def run_tests(with_coverage: bool = False) -> tuple[int, str]:
    cmd = PYTEST_CMD_COVERAGE if with_coverage else PYTEST_CMD_FULL
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def apply_fix_missing_deps():
    print("  -> Installing missing dependencies...")
    result = subprocess.run(
        ["pip", "install", "-r", "requirements.txt"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(
            [
                ".venv/bin/pip",
                "install",
                "fastapi",
                "sqlalchemy",
                "asyncpg",
                "alembic",
                "pydantic",
                "pydantic-settings",
                "redis",
                "httpx",
                "phonenumbers",
                "python-dateutil",
                "aiofiles",
                "networkx",
                "stem",
                "pytest",
                "pytest-asyncio",
                "pytest-cov",
                "anyio",
            ],
            cwd=ROOT,
            capture_output=True,
        )
    FIXES_APPLIED.append("installed missing dependencies")


def apply_fix_run_migrations():
    print("  -> Running database migrations...")
    result = subprocess.run(
        [".venv/bin/python", "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fall back to bare alembic in PATH
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=ROOT,
            capture_output=True,
        )
    FIXES_APPLIED.append("ran database migrations")


def apply_fix_create_test_db():
    print("  -> Creating test database...")
    subprocess.run(
        [
            "docker",
            "exec",
            "osnit-postgres-1",
            "psql",
            "-U",
            "lycan",
            "-c",
            "CREATE DATABASE lycan_test;",
        ],
        cwd=ROOT,
        capture_output=True,
    )
    FIXES_APPLIED.append("created test database")


def apply_fix_flush_queues():
    print("  -> Flushing stale Redis/Dragonfly queues...")
    subprocess.run(
        ["docker", "exec", "osnit-dragonfly-1", "redis-cli", "FLUSHDB"],
        cwd=ROOT,
        capture_output=True,
    )
    FIXES_APPLIED.append("flushed stale queues")


def diagnose(output: str) -> list[str]:
    fixes = []

    if "ModuleNotFoundError" in output or "ImportError" in output:
        fixes.append("missing_deps")

    # DB does not exist
    if (
        "could not connect" in output.lower()
        or "does not exist" in output.lower()
        and "database" in output.lower()
    ):
        fixes.append("create_test_db")

    # Missing table / relation — need migrations
    if re.search(r"No such table|relation .* does not exist", output, re.IGNORECASE):
        if "run_migrations" not in fixes:
            fixes.append("run_migrations")

    # Alembic / schema version drift
    if (
        "target database is not up to date" in output.lower()
        or "alembic" in output.lower()
        or "can't adapt type" in output.lower()
    ):
        if "run_migrations" not in fixes:
            fixes.append("run_migrations")

    # Redis/Dragonfly connection refused — log but don't add a blocking fix
    if re.search(r"Connection refused.*637[89]|637[89].*Connection refused", output):
        print("  [warn] Redis/Dragonfly connection refused — skipping queue fix, continuing")

    # Stale queue assertions
    if (
        "assert 0 >= 1" in output
        or "assert None is not None" in output
        or re.search(r"assert None\b", output)
        or ("queue" in output.lower() and "assert" in output.lower())
    ):
        fixes.append("flush_queues")

    # Coverage drop — log but don't add a fix action
    if "coverage" in output.lower() and ("fail" in output.lower() or "under" in output.lower()):
        print("  [warn] Coverage threshold not met — review coverage report")

    return fixes


FIX_FUNCTIONS = {
    "missing_deps": apply_fix_missing_deps,
    "create_test_db": apply_fix_create_test_db,
    "run_migrations": apply_fix_run_migrations,
    "flush_queues": apply_fix_flush_queues,
}


def extract_summary(output: str) -> dict:
    """Parse pytest output into structured summary values."""
    passed = 0
    failed = 0
    errors = 0
    coverage_pct = None

    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))

    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))

    m = re.search(r"(\d+) error", output)
    if m:
        errors = int(m.group(1))

    # pytest-cov prints "TOTAL  ... XX%"
    m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", output, re.MULTILINE)
    if m:
        coverage_pct = int(m.group(1))

    top_failures = re.findall(r"^FAILED (.+?)(?:\s+-\s+.+)?$", output, re.MULTILINE)

    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "coverage_pct": coverage_pct,
        "top_failures": top_failures[:10],
    }


def run_report():
    """--report mode: run tests, print health summary, exit cleanly."""
    print("=" * 60)
    print("Lycan-Data Health Report")
    print("=" * 60)
    print("\nRunning full test suite with coverage...\n")

    code, output = run_tests(with_coverage=True)
    summary = extract_summary(output)

    total = summary["passed"] + summary["failed"] + summary["errors"]
    pass_rate = (summary["passed"] / total * 100) if total else 0.0

    print(f"  Pass rate  : {pass_rate:.1f}%  ({summary['passed']}/{total})")
    print(f"  Failed     : {summary['failed']}")
    print(f"  Errors     : {summary['errors']}")

    if summary["coverage_pct"] is not None:
        print(f"  Coverage   : {summary['coverage_pct']}%")
    else:
        print("  Coverage   : n/a (run with --cov flags)")

    if summary["top_failures"]:
        print(f"\n  Top failures ({len(summary['top_failures'])}):")
        for f in summary["top_failures"]:
            print(f"    - {f}")
    else:
        print("\n  No failures.")

    print("\n" + "=" * 60)
    return 0  # --report never fails the process


def main():
    parser = argparse.ArgumentParser(description="Lycan-Data self-healing test runner")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print health summary only — do not apply any fixes",
    )
    args = parser.parse_args()

    if args.report:
        return run_report()

    print("=" * 60)
    print("Lycan-Data Self-Healing Test Runner")
    print("=" * 60)

    print("\n[1/3] Running test suite...")
    code, output = run_tests()

    if code == 0:
        print("All tests passed. Nothing to heal.")
        for line in output.splitlines():
            if "passed" in line or "failed" in line:
                print(f"  {line}")
        return 0

    # Count failures
    failed = len(re.findall(r"^FAILED ", output, re.MULTILINE))
    passed = re.search(r"(\d+) passed", output)
    print(f"  {failed} failed, {passed.group(0) if passed else '?'}")

    print("\n[2/3] Diagnosing failures...")
    fixes_needed = diagnose(output)

    if not fixes_needed:
        print("  Unknown failure pattern — printing output for manual inspection:")
        print("-" * 60)
        in_failure = False
        for line in output.splitlines():
            if line.startswith("FAILED") or line.startswith("ERROR"):
                print(f"  {line}")
                in_failure = True
            elif in_failure and line.startswith("_"):
                in_failure = False
        print("-" * 60)
        return code

    print(f"  Diagnosed: {', '.join(fixes_needed)}")
    print("\n[2.5/3] Applying fixes...")
    for fix in fixes_needed:
        FIX_FUNCTIONS[fix]()

    print("\n[3/3] Re-running tests to verify healing...")
    code2, output2 = run_tests()

    for line in output2.splitlines():
        if "passed" in line or "failed" in line or "error" in line.lower():
            print(f"  {line}")

    if code2 == 0:
        print("\nSelf-healed successfully!")
        print(f"  Applied: {', '.join(FIXES_APPLIED)}")
        return 0

    failed2 = len(re.findall(r"^FAILED ", output2, re.MULTILINE))
    print(f"\nStill failing after healing ({failed2} failures).")
    print("  Manual intervention required.")
    for line in output2.splitlines():
        if line.startswith("FAILED"):
            print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
