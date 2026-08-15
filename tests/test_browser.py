import pytest

from chatgpt_archive.browser import validate_cdp_url


@pytest.mark.parametrize("url", ["http://127.0.0.1:9222", "ws://localhost:9222/devtools/browser/id", "http://[::1]:9222"])
def test_loopback_cdp_urls_are_accepted(url: str) -> None:
    assert validate_cdp_url(url) == url


@pytest.mark.parametrize("url", ["https://example.test", "http://remote.example:9222", "http://user:secret@127.0.0.1:9222"])
def test_non_local_or_credential_bearing_cdp_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_cdp_url(url)
