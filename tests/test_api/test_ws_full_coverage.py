"""
test_ws_full_coverage.py — Async tests to cover ws.py lines missed by TestClient.

Missing lines:
  33-37  WS _forward: matching message forwarded + send_json exception swallowed
  55-58  WS timeout → server ping → send_json raises → break
  98-99  SSE heartbeat on queue.get() timeout
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# WS _forward callback coverage (lines 33-37)
# ---------------------------------------------------------------------------


class TestWSForwardCallback:
    """Drive the _forward inner closure via a cooperative subscribe mock."""

    def _make_app(self):
        from api.routes import ws

        app = FastAPI()
        app.include_router(ws.router)
        return app

    def test_forward_delivers_matching_message(self):
        """subscribe calls _forward with matching person_id → client receives JSON (lines 33-35)."""
        person_id = "fwd-123"

        async def _subscribe(channel, callback):
            # Yield a few times so the receive loop is established, then push a message
            for _ in range(3):
                await asyncio.sleep(0)
            await callback({"event": "progress", "person_id": person_id, "platform": "x"})
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _subscribe
            app = self._make_app()
            with TestClient(app, raise_server_exceptions=False) as c:
                with c.websocket_connect(f"/ws/progress/{person_id}") as ws_conn:
                    data = ws_conn.receive_json()
                    assert data["event"] == "progress"
                    assert data["person_id"] == person_id

    @pytest.mark.asyncio
    async def test_forward_send_exception_swallowed(self):
        """send_json raises inside _forward → exception caught silently (lines 36-37)."""
        from api.routes.ws import scrape_progress

        person_id = "ex-fwd"
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        send_attempts: list = []

        async def _send_json(msg):
            send_attempts.append(msg)
            raise RuntimeError("ws closed")

        mock_ws.send_json = _send_json

        async def _receive():
            # Yield enough times for the sub_task to call the callback first
            for _ in range(5):
                await asyncio.sleep(0)
            raise WebSocketDisconnect()

        mock_ws.receive_text = _receive

        async def _subscribe(channel, callback):
            await asyncio.sleep(0)
            await callback({"event": "x", "person_id": person_id})
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _subscribe
            # Must not raise even though send_json raises inside _forward
            await scrape_progress(mock_ws, person_id)

        assert len(send_attempts) >= 1


# ---------------------------------------------------------------------------
# WS timeout path coverage (lines 53-58)
# ---------------------------------------------------------------------------


class TestWSTimeoutPaths:
    """Patch asyncio.wait_for to trigger TimeoutError in the receive loop."""

    @pytest.mark.asyncio
    async def test_timeout_sends_server_ping(self):
        """TimeoutError → server sends {event: ping} (lines 53-57)."""
        from api.routes.ws import scrape_progress

        person_id = "ping-test"
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()

        sent: list = []

        async def _send(msg):
            sent.append(msg)

        mock_ws.send_json = _send

        original_wf = asyncio.wait_for
        call_n = [0]

        async def _patched_wf(coro, timeout):
            call_n[0] += 1
            if call_n[0] == 1:
                # Simulate a receive_text timeout on the first call
                try:
                    coro.close()
                except Exception:
                    pass
                raise asyncio.TimeoutError()
            # Second call: let receive_text raise WebSocketDisconnect immediately
            return await original_wf(coro, timeout=timeout)

        async def _receive():
            raise WebSocketDisconnect()

        mock_ws.receive_text = _receive

        async def _hang(ch, cb):
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _hang
            with patch("asyncio.wait_for", _patched_wf):
                await scrape_progress(mock_ws, person_id)

        assert {"event": "ping"} in sent

    @pytest.mark.asyncio
    async def test_timeout_send_fails_breaks_loop(self):
        """TimeoutError + send_json raises → except Exception: break (lines 55-58)."""
        from api.routes.ws import scrape_progress

        person_id = "break-test"
        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock(side_effect=RuntimeError("gone"))

        async def _patched_wf(coro, timeout):
            try:
                coro.close()
            except Exception:
                pass
            raise asyncio.TimeoutError()

        async def _hang(ch, cb):
            await asyncio.sleep(9999)

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.subscribe = _hang
            with patch("asyncio.wait_for", _patched_wf):
                await scrape_progress(mock_ws, person_id)

        mock_ws.send_json.assert_called_once_with({"event": "ping"})


# ---------------------------------------------------------------------------
# SSE heartbeat coverage (lines 98-99)
# ---------------------------------------------------------------------------


class TestSSEHeartbeat:
    """queue.get() timeout → yield SSE heartbeat event."""

    @pytest.mark.asyncio
    async def test_heartbeat_yielded_on_queue_timeout(self):
        """asyncio.TimeoutError from queue.get() yields heartbeat data (lines 98-99)."""
        from api.routes.ws import sse_progress

        person_id = "hb-person"

        disc_count = [0]
        mock_request = MagicMock()

        async def _is_disc():
            disc_count[0] += 1
            # False on first check (let heartbeat run), True on second (exit loop)
            return disc_count[0] > 1

        mock_request.is_disconnected = _is_disc

        original_wf = asyncio.wait_for
        wf_count = [0]

        async def _patched_wf(coro, timeout):
            wf_count[0] += 1
            if wf_count[0] == 1:
                try:
                    coro.close()
                except Exception:
                    pass
                raise asyncio.TimeoutError()
            return await original_wf(coro, timeout=timeout)

        async def _hang_sub(ch, cb):
            await asyncio.sleep(9999)

        chunks: list = []

        with patch("api.routes.ws.event_bus") as mock_bus:
            mock_bus.is_connected = True
            mock_bus.subscribe = _hang_sub
            with patch("asyncio.wait_for", _patched_wf):
                response = await sse_progress(person_id, mock_request)
                async for chunk in response.body_iterator:
                    chunks.append(chunk if isinstance(chunk, str) else chunk.decode())

        assert any("heartbeat" in c for c in chunks)
