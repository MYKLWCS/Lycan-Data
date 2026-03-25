"""Verify CommercialTaggerDaemon can be imported and integrated."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_commercial_tagger_daemon_importable():
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

    daemon = CommercialTaggerDaemon()
    assert hasattr(daemon, "start")
    assert hasattr(daemon, "stop")
    assert hasattr(daemon, "_run_batch")


@pytest.mark.asyncio
async def test_daemon_start_stops_cleanly():
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

    daemon = CommercialTaggerDaemon()

    async def _stop_after_one_cycle():
        await asyncio.sleep(0.05)
        daemon.stop()

    with patch.object(daemon, "_run_batch", new_callable=AsyncMock) as mock_batch:
        with patch("modules.enrichers.commercial_tagger._SLEEP_SECONDS", 0):
            stopper = asyncio.create_task(_stop_after_one_cycle())
            runner = asyncio.create_task(daemon.start())
            await asyncio.gather(stopper, runner, return_exceptions=True)

    assert mock_batch.call_count >= 1


def test_worker_has_no_commercial_flag():
    """worker.py argparse must accept --no-commercial flag."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "worker.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/wolf/Lycan-Data",
    )
    assert "--no-commercial" in result.stdout
