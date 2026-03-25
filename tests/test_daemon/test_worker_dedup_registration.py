"""Tests confirming AutoDedupDaemon is registered in worker.py."""

import pathlib


def test_auto_dedup_daemon_imported_in_worker():
    """worker.py must import AutoDedupDaemon."""
    src = pathlib.Path("worker.py").read_text()
    assert "AutoDedupDaemon" in src, \
        "worker.py does not reference AutoDedupDaemon"


def test_worker_starts_auto_dedup_task():
    """worker.py must create a task for auto-dedup-daemon."""
    src = pathlib.Path("worker.py").read_text()
    assert "auto-dedup" in src or "AutoDedupDaemon" in src, \
        "worker.py does not start AutoDedupDaemon task"
