#!/usr/bin/env python3
"""
Self-healing test runner for Lycan-Data.

Runs the test suite, diagnoses failures, applies known fixes, and re-runs to verify.
"""

import subprocess
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

PYTEST_CMD = [
    ".venv/bin/python",
    "-m",
    "pytest",
    "tests/",
    "--tb=short",
    "-q",
    "--ignore=tests/test_crawlers",
    "--ignore=tests/test_darkweb",
    "--ignore=tests/test_government",
    "-k",
    "not integration and not playwright",
]

FIXES_APPLIED = []


def run_tests() -> tuple[int, str]:
    result = subprocess.run(
        PYTEST_CMD,
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

    if (
        "could not connect" in output.lower()
        or "does not exist" in output.lower()
        and "database" in output.lower()
    ):
        fixes.append("create_test_db")

    if (
        "target database is not up to date" in output.lower()
        or "alembic" in output.lower()
        or "can't adapt type" in output.lower()
    ):
        fixes.append("run_migrations")

    if "assert 0 >= 1" in output or "queue" in output.lower() and "assert" in output.lower():
        fixes.append("flush_queues")

    return fixes


FIX_FUNCTIONS = {
    "missing_deps": apply_fix_missing_deps,
    "create_test_db": apply_fix_create_test_db,
    "run_migrations": apply_fix_run_migrations,
    "flush_queues": apply_fix_flush_queues,
}


def main():
    print("=" * 60)
    print("Lycan-Data Self-Healing Test Runner")
    print("=" * 60)

    print("\n[1/3] Running test suite...")
    code, output = run_tests()

    if code == 0:
        print("All tests passed. Nothing to heal.")
        # Print summary line
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
        # Print just the FAILED lines and error context
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
        print(f"\nSelf-healed successfully!")
        print(f"  Applied: {', '.join(FIXES_APPLIED)}")
        return 0
    else:
        failed2 = len(re.findall(r"^FAILED ", output2, re.MULTILINE))
        print(f"\nStill failing after healing ({failed2} failures).")
        print("  Manual intervention required.")
        for line in output2.splitlines():
            if line.startswith("FAILED"):
                print(f"  {line}")
        return code2


if __name__ == "__main__":
    sys.exit(main())
