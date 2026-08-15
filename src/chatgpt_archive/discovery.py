"""Conversation-list discovery with centralized, progressively weaker selectors."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .models import ManifestEntry


@dataclass(frozen=True)
class Selectors:
    # Assumptions: sidebar conversation links use /c/<id>; semantic attributes win.
    conversation_links: tuple[str, ...] = (
        "a[data-testid='conversation-turn']",
        "nav a[href*='/c/']",
        "a[href*='/c/']",
    )
    sidebar_scroll_container: tuple[str, ...] = (
        "nav[aria-label]",
        "nav",
        "aside",
    )


SELECTORS = Selectors()


def conversation_id_from_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        return parts[parts.index("c") + 1]
    except (ValueError, IndexError):
        return None


def normalize_links(links: list[tuple[str, str]], base_url: str) -> list[ManifestEntry]:
    found: dict[str, ManifestEntry] = {}
    for href, title in links:
        url = urljoin(base_url, href)
        identifier = conversation_id_from_url(url)
        if identifier:
            found.setdefault(identifier, ManifestEntry(conversation_id=identifier, title=title.strip() or "Untitled conversation", source_url=url))
    return list(found.values())


def discover(page: object, max_scrolls: int = 80) -> list[ManifestEntry]:
    """Enumerate and scroll the visible history. Re-running safely merges the manifest."""
    seen: dict[str, ManifestEntry] = {}
    for _ in range(max_scrolls):
        pairs: list[tuple[str, str]] = []
        for selector in SELECTORS.conversation_links:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                pairs.append((item.get_attribute("href") or "", item.inner_text(timeout=1000)))
        for entry in normalize_links(pairs, page.url):
            seen.setdefault(entry.conversation_id, entry)
        container = next((page.locator(item) for item in SELECTORS.sidebar_scroll_container if page.locator(item).count()), None)
        if container is None:
            break
        before = container.evaluate("element => element.scrollHeight - element.scrollTop")
        container.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        page.wait_for_timeout(400)
        after = container.evaluate("element => element.scrollHeight - element.scrollTop")
        if after >= before:
            break
    return list(seen.values())
