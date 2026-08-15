"""Opt-in local failure artifacts. Nothing is captured unless explicitly requested."""
from __future__ import annotations

from pathlib import Path


def capture_failure_artifacts(page: object, directory: Path, conversation_id: str) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(char if char.isalnum() or char in "-_" else "-" for char in conversation_id)[:80] or "conversation"
    artifacts: list[str] = []
    screenshot = directory / f"{safe_id}.png"
    html = directory / f"{safe_id}.html"
    try:
        page.screenshot(path=str(screenshot), full_page=True)
        artifacts.append(screenshot.name)
    except Exception:
        pass
    try:
        html.write_text(page.content(), encoding="utf-8")
        artifacts.append(html.name)
    except Exception:
        pass
    return artifacts
