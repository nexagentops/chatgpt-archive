"""Conversation-list discovery with centralized, progressively weaker selectors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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
        "nav[aria-label='Sidebar']",
        "nav[aria-label*='Sidebar' i]",
        "aside",
    )


SELECTORS = Selectors()


@dataclass
class DiscoveryResult:
    entries: list[ManifestEntry]
    complete: bool
    termination_reason: str
    source_method_counts: dict[str, int]
    batches: int


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


def discover(page: object, max_scrolls: int = 80, limit: int | None = None) -> list[ManifestEntry]:
    """Enumerate and scroll the visible history. Re-running safely merges the manifest."""
    seen: dict[str, ManifestEntry] = {}
    # ChatGPT renders the sidebar after initial document readiness. A bounded wait
    # avoids treating an authenticated but not-yet-hydrated sidebar as empty.
    page.wait_for_timeout(750)
    for _ in range(max_scrolls):
        pairs: list[tuple[str, str]] = []
        for selector in SELECTORS.conversation_links:
            locator = page.locator(selector)
            for index in range(locator.count()):
                item = locator.nth(index)
                pairs.append((item.get_attribute("href") or "", item.inner_text(timeout=1000)))
        for entry in normalize_links(pairs, page.url):
            seen.setdefault(entry.conversation_id, entry)
        if limit and len(seen) >= limit:
            return list(seen.values())[:limit]
        container = next((page.locator(item).first for item in SELECTORS.sidebar_scroll_container if page.locator(item).count()), None)
        if container is None:
            break
        before = container.evaluate("element => element.scrollHeight - element.scrollTop")
        container.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        page.wait_for_timeout(400)
        after = container.evaluate("element => element.scrollHeight - element.scrollTop")
        if after >= before:
            break
    return list(seen.values())


def discover_with_metadata(
    page: object, limit: int | None = None,
    on_batch: Callable[[list[ManifestEntry]], None] | None = None,
) -> DiscoveryResult:
    """Prefer browser-observed structured history; fall back to sidebar DOM safely."""
    responses: list[object] = []
    def observe(response: object) -> None:
        if "/backend-api/conversation" in urlparse(response.url).path:
            responses.append(response)
    page.on("response", observe)
    try:
        # A bounded navigation gives the normal application workflow a chance to
        # issue its own history request without relying on its virtualized DOM.
        page.reload(wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(900)
        for response in reversed(responses):
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("items"), list) and isinstance(payload.get("total"), int):
                    return _structured_history(page, response.url, payload, limit, on_batch)
            except Exception:
                continue
    finally:
        page.remove_listener("response", observe)
    entries = discover(page, limit=limit)
    return DiscoveryResult(
        entries,
        False,
        "structured_unavailable" if entries else "pagination_stalled",
        {"sidebar_dom": len(entries)},
        0,
    )


def _structured_history(
    page: object, response_url: str, first: dict, limit: int | None,
    on_batch: Callable[[list[ManifestEntry]], None] | None = None,
) -> DiscoveryResult:
    seen: dict[str, ManifestEntry] = {}
    total = int(first["total"])
    offset = int(first.get("offset") or 0)
    batch_size = int(first.get("limit") or len(first["items"]) or 1)
    batches = 0
    payload = first
    while True:
        batches += 1
        batch_entries: list[ManifestEntry] = []
        for item in payload.get("items", []):
            entry = _history_entry(item)
            if entry and entry.conversation_id not in seen:
                seen[entry.conversation_id] = entry
                batch_entries.append(entry)
            if limit and len(seen) >= limit:
                if on_batch and batch_entries:
                    on_batch(batch_entries)
                return DiscoveryResult(list(seen.values())[:limit], False, "limit_reached", {"structured_history": len(seen)}, batches)
        if on_batch and batch_entries:
            on_batch(batch_entries)
        offset += len(payload.get("items", []))
        if offset >= total:
            return DiscoveryResult(list(seen.values()), True, "history_exhausted", {"structured_history": len(seen)}, batches)
        if not payload.get("items"):
            return DiscoveryResult(list(seen.values()), False, "pagination_stalled", {"structured_history": len(seen)}, batches)
        try:
            response = page.evaluate(
                """async (url) => {
                    const response = await fetch(url, {credentials: 'same-origin'});
                    const payload = response.ok ? await response.json() : null;
                    return {status: response.status, payload};
                }""",
                _paged_url(response_url, offset, min(batch_size, total - offset)),
            )
        except Exception:
            return DiscoveryResult(list(seen.values()), False, "fatal_error", {"structured_history": len(seen)}, batches)
        if not isinstance(response, dict):
            return DiscoveryResult(list(seen.values()), False, "fatal_error", {"structured_history": len(seen)}, batches)
        if response.get("status") in {401, 403}:
            return DiscoveryResult(list(seen.values()), False, "authentication_required", {"structured_history": len(seen)}, batches)
        payload = response.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            return DiscoveryResult(list(seen.values()), False, "fatal_error", {"structured_history": len(seen)}, batches)
        # The server can report a smaller, current total after an intervening
        # deletion/retention change. Its empty response at the requested offset
        # is authoritative completion; it is not a sidebar inference.
        if int(payload.get("total") or total) <= offset and not payload["items"]:
            return DiscoveryResult(list(seen.values()), True, "history_exhausted", {"structured_history": len(seen)}, batches)


def _paged_url(url: str, offset: int, limit: int) -> str:
    parsed = urlparse(url); query = parse_qs(parsed.query); query["offset"] = [str(offset)]; query["limit"] = [str(limit)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _history_entry(item: object) -> ManifestEntry | None:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str): return None
    identifier = item["id"]
    return ManifestEntry(conversation_id=identifier, title=str(item.get("title") or "Untitled conversation"), source_url=f"https://chatgpt.com/c/{identifier}", created_at=_timestamp(item.get("create_time")), updated_at=_timestamp(item.get("update_time")), source_method="structured_history")


def _timestamp(value: object) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if isinstance(value, (int, float)) else None
