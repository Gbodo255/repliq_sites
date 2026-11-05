import pytest

from app.core.security import (
    UnsafeUrlError,
    host_is_allowed,
    is_safe_url,
    normalize_url,
    validate_target_url,
)


def test_normalize_adds_scheme_and_strips_fragment():
    assert normalize_url("example.com") == "https://example.com/"
    assert normalize_url("https://x.com/a#frag") == "https://x.com/a"


def test_public_ip_literals_allowed():
    assert host_is_allowed("8.8.8.8") is True
    assert is_safe_url("https://8.8.8.8/x") is True


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "0.0.0.0"])
def test_private_and_metadata_ips_blocked(host):
    assert host_is_allowed(host) is False
    assert is_safe_url(f"http://{host}/") is False


def test_localhost_names_blocked():
    assert host_is_allowed("localhost") is False
    assert host_is_allowed("foo.localhost") is False
    assert host_is_allowed("metadata.google.internal") is False


def test_non_http_scheme_rejected():
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("ftp://8.8.8.8/x") is False


def test_validate_target_rejects_private():
    with pytest.raises(UnsafeUrlError):
        validate_target_url("http://127.0.0.1:8000")
