"""Tests for input validation on search endpoints."""

import pytest
from pydantic import ValidationError


def _make_request(**kwargs):
    """Import SearchRequest and create an instance."""
    from api.routes.search import SearchRequest
    return SearchRequest(**kwargs)


# --- Value field validation ---

def test_valid_name():
    req = _make_request(value="John Smith")
    assert req.value == "John Smith"


def test_valid_email():
    req = _make_request(value="john@example.com")
    assert req.value == "john@example.com"


def test_valid_phone():
    req = _make_request(value="+1-555-000-1234")
    assert req.value == "+1-555-000-1234"


def test_valid_crypto_address():
    req = _make_request(value="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68")
    assert req.value == "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68"


def test_valid_ip_address():
    req = _make_request(value="192.168.1.1")
    assert req.value == "192.168.1.1"


def test_valid_domain():
    req = _make_request(value="example.com")
    assert req.value == "example.com"


def test_valid_username():
    req = _make_request(value="john_doe_123")
    assert req.value == "john_doe_123"


# --- Injection prevention ---

def test_html_tags_stripped():
    req = _make_request(value="<script>alert('xss')</script>John")
    assert "<script>" not in req.value
    assert "alert" in req.value  # text content preserved


def test_sql_injection_sanitized():
    req = _make_request(value="'; DROP TABLE persons; --")
    # Dangerous chars removed, but safe parts preserved
    assert "DROP" in req.value  # text preserved
    assert ";" not in req.value  # semicolons stripped


def test_command_injection_sanitized():
    req = _make_request(value="$(rm -rf /)")
    assert "$" not in req.value
    assert "`" not in req.value


def test_shell_backtick_stripped():
    req = _make_request(value="`whoami`")
    assert "`" not in req.value


def test_backslash_stripped():
    req = _make_request(value="test\\ninjection")
    assert "\\" not in req.value


# --- Empty/blank validation ---

def test_empty_string_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="")


def test_whitespace_only_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="   ")


def test_too_long_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="a" * 201)


def test_only_special_chars_rejected():
    """Value with only stripped chars should fail."""
    with pytest.raises(ValidationError):
        _make_request(value="$$$`\\`$$$")


# --- Context field validation ---

def test_valid_contexts():
    for ctx in ("general", "risk", "wealth", "identity"):
        req = _make_request(value="test", context=ctx)
        assert req.context == ctx


def test_invalid_context_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="test", context="hacking")


# --- max_depth validation ---

def test_max_depth_bounds():
    req = _make_request(value="test", max_depth=1)
    assert req.max_depth == 1
    req = _make_request(value="test", max_depth=5)
    assert req.max_depth == 5


def test_max_depth_zero_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="test", max_depth=0)


def test_max_depth_too_high_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="test", max_depth=6)


# --- Priority validation ---

def test_valid_priorities():
    for p in ("high", "normal", "low"):
        req = _make_request(value="test", priority=p)
        assert req.priority == p


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        _make_request(value="test", priority="critical")


# --- BatchSearchRequest validation ---

def test_batch_max_size():
    from api.routes.search import BatchSearchRequest
    with pytest.raises(ValidationError):
        BatchSearchRequest(seeds=[{"value": f"person{i}"} for i in range(51)])


def test_batch_empty_rejected():
    from api.routes.search import BatchSearchRequest
    with pytest.raises(ValidationError):
        BatchSearchRequest(seeds=[])


def test_batch_valid():
    from api.routes.search import BatchSearchRequest
    batch = BatchSearchRequest(seeds=[{"value": "John Smith"}, {"value": "Jane Doe"}])
    assert len(batch.seeds) == 2
