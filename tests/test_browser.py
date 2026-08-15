import pytest

from chatgpt_archive.browser import validate_cdp_url
from chatgpt_archive.browser import interface_is_authenticated


@pytest.mark.parametrize("url", ["http://127.0.0.1:9222", "ws://localhost:9222/devtools/browser/id", "http://[::1]:9222"])
def test_loopback_cdp_urls_are_accepted(url: str) -> None:
    assert validate_cdp_url(url) == url


@pytest.mark.parametrize("url", ["https://example.test", "http://remote.example:9222", "http://user:secret@127.0.0.1:9222"])
def test_non_local_or_credential_bearing_cdp_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_cdp_url(url)


class _Locator:
    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


class _Page:
    url = "https://chatgpt.com/"

    def __init__(self, login_controls: int, shell: int):
        self.login_controls = login_controls
        self.shell = shell

    def locator(self, selector: str) -> _Locator:
        return _Locator(self.login_controls if "auth/login" in selector else self.shell)


def test_login_controls_fail_closed_even_when_shell_is_visible() -> None:
    assert not interface_is_authenticated(_Page(login_controls=1, shell=2))
    assert interface_is_authenticated(_Page(login_controls=0, shell=2))
