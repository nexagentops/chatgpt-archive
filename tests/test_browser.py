import socket

import pytest

from chatgpt_archive.browser import default_profile_dir, validate_cdp_url
import chatgpt_archive.browser as browser
from chatgpt_archive.browser import interface_is_authenticated


@pytest.mark.parametrize("url", ["http://127.0.0.1:9222", "ws://localhost:9222/devtools/browser/id", "http://[::1]:9222"])
def test_loopback_cdp_urls_are_accepted(url: str) -> None:
    assert validate_cdp_url(url) == url


@pytest.mark.parametrize("url", ["https://example.test", "http://remote.example:9222", "http://user:secret@127.0.0.1:9222"])
def test_non_local_or_credential_bearing_cdp_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_cdp_url(url)


def test_default_profile_dir_is_user_local_and_not_relative_to_checkout(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert default_profile_dir() == tmp_path / "home" / ".local" / "state" / "chatgpt-archive" / "browser-profile"


def test_default_profile_dir_honors_absolute_xdg_state_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_profile_dir() == tmp_path / "state" / "chatgpt-archive" / "browser-profile"


def test_localhost_cdp_fails_closed_when_resolution_is_not_loopback(monkeypatch) -> None:
    monkeypatch.setattr(browser.socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, 0, 0, "", ("203.0.113.8", 0))])
    with pytest.raises(ValueError):
        validate_cdp_url("http://localhost:9222")


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
