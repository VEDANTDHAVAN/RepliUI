"""URL validation: the analyzer's deterministic pre-flight guard.

No network access is required; every case here is a pure input check.
"""

from __future__ import annotations

import pytest

from app.analyzers.urls import MAX_URL_LENGTH, InvalidURLError, validate_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("  https://example.com/path?q=1  ", "https://example.com/path?q=1"),
        ("example.com", "https://example.com"),
        ("http://sub.domain.co.uk/x", "http://sub.domain.co.uk/x"),
    ],
)
def test_accepts_public_http_urls(raw, expected):
    assert validate_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://",
        "https://localhost",
        "https://intranet",
        "https://127.0.0.1",
        "https://127.0.0.1:8000/admin",
        "https://10.0.0.5",
        "https://192.168.1.10",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/",
        "https://printer.local",
    ],
)
def test_rejects_unsafe_or_invalid_urls(raw):
    with pytest.raises(InvalidURLError):
        validate_url(raw)


def test_rejects_overlong_url():
    with pytest.raises(InvalidURLError):
        validate_url("https://example.com/" + "a" * MAX_URL_LENGTH)


def test_error_message_is_user_facing_without_stack_details():
    with pytest.raises(InvalidURLError) as excinfo:
        validate_url("https://127.0.0.1")
    message = str(excinfo.value)
    assert "local or private" in message
    assert "Traceback" not in message
