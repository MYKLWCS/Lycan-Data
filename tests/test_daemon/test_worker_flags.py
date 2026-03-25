"""Verify worker.py argparse exposes --no-audit flag (Task 5, Phase 6)."""

import subprocess
import sys


def test_worker_has_no_audit_flag():
    result = subprocess.run(
        [sys.executable, "worker.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/wolf/Lycan-Data",
    )
    assert "--no-audit" in result.stdout


def test_worker_audit_flag_listed_with_others():
    result = subprocess.run(
        [sys.executable, "worker.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/wolf/Lycan-Data",
    )
    # All daemon flags should be present
    for flag in ("--no-growth", "--no-freshness", "--no-commercial", "--no-audit"):
        assert flag in result.stdout, f"Missing flag: {flag}"
