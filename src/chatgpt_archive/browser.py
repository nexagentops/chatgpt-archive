"""Browser boundary. Authentication remains inside Playwright's ignored profile."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
