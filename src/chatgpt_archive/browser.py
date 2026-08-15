"""Browser boundary. Authentication remains inside Playwright's ignored profile."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse


CHATGPT_HOME = "https://chatgpt.com/"


@contextmanager
def authenticated_page(profile_dir: Path, *, headless: bool = False) -> Iterator[object]:
    """Yield a page backed by a persistent local profile; never expose its cookies."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised only by CLI setup
        raise RuntimeError("Playwright is required. Install dependencies and run `playwright install chromium`.") from exc

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            context.close()


def interface_is_authenticated(page: object) -> bool:
    """Conservative UI check; it intentionally does not inspect storage or cookies."""
    url = getattr(page, "url", "")
    if "chatgpt.com" not in url or "/auth/" in url:
        return False
    try:
        return bool(page.locator("nav, [role='navigation'], main").count())
    except Exception:
        return False


class NetworkObserver:
    """Records only endpoint metadata; bodies, headers, and cookies are never retained."""

    def __init__(self) -> None:
        self.responses: list[dict[str, object]] = []

    def attach(self, page: object) -> None:
        page.on("response", self._on_response)

    def _on_response(self, response: object) -> None:
        parsed = urlparse(response.url)
        path = parsed.path
        if "/conversation" in path or "/backend-api/" in path:
            self.responses.append({"origin": f"{parsed.scheme}://{parsed.netloc}", "path": path, "status": response.status, "content_type": response.headers.get("content-type", "").split(";", 1)[0]})
