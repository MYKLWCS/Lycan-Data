"""Tests for API key authentication middleware."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.deps import verify_api_key


@pytest.fixture(autouse=True)
def restore_auth_for_auth_tests():
    """Remove the conftest auth override so auth tests actually test auth."""
    from api.main import app
    app.dependency_overrides.pop(verify_api_key, None)
    yield
    app.dependency_overrides.pop(verify_api_key, None)


def _get_app():
    """Import app fresh so settings patches take effect."""
    from api.main import app
    return app


def test_unauthenticated_request_rejected():
    """Endpoints reject requests without Authorization header."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "testkey123"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/search", json={"value": "John Smith"})
        assert resp.status_code in (401, 403)


def test_invalid_api_key_rejected():
    """Endpoints reject requests with wrong API key."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "testkey123"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/search",
            json={"value": "John Smith"},
            headers={"Authorization": "Bearer wrongkey"},
        )
        assert resp.status_code == 401


def test_valid_api_key_passes():
    """Endpoints accept requests with valid API key."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "testkey123,otherkey"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/search",
            json={"value": "John Smith"},
            headers={"Authorization": "Bearer testkey123"},
        )
        # Should not be 401/403 — may fail downstream (DB etc.) but auth passed
        assert resp.status_code not in (401, 403)


def test_health_endpoint_no_auth_required():
    """Health check must remain accessible without auth."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "testkey123"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/system/health")
        # Health may return 200 or 503 depending on services, but never 401
        assert resp.status_code != 401


def test_auth_disabled_passes_all():
    """When auth is disabled, requests pass without key."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = False
        mock_settings.api_keys = ""
        client = TestClient(app, raise_server_exceptions=False)
        # Still need a header since HTTPBearer auto_error=True
        resp = client.post(
            "/search",
            json={"value": "John Smith"},
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code not in (401, 403)


def test_no_keys_configured_returns_503():
    """If auth is enabled but no keys configured, return 503."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = ""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/search",
            json={"value": "John Smith"},
            headers={"Authorization": "Bearer something"},
        )
        assert resp.status_code == 503


def test_multiple_api_keys():
    """All configured keys should be accepted."""
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "key1, key2, key3"
        client = TestClient(app, raise_server_exceptions=False)
        for key in ("key1", "key2", "key3"):
            resp = client.post(
                "/search",
                json={"value": "Test"},
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code not in (401, 403), f"Key {key} was rejected"
