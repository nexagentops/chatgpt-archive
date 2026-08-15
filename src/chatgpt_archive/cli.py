from __future__ import annotations

from collections import Counter
from pathlib import Path
import time

import typer

from .browser import CHATGPT_HOME, NetworkObserver, authenticated_page, interface_is_authenticated
from .diagnostics import capture_failure_artifacts
from .discovery import discover
from .extractor import PlaywrightAcquirer
from .markdown import render_conversation
from .models import CaptureStatus, FailureRecord
from .storage import ArchiveStore

app = typer.Typer(help="Local-first archival for conversations owned by the authenticated ChatGPT user.")


def paths(data_dir: Path, profile_dir: Path) -> tuple[ArchiveStore, Path]:
    return ArchiveStore(data_dir), profile_dir


@app.command()
def login(
    profile_dir: Path = typer.Option(Path(".playwright-profile"), help="Ignored persistent Playwright profile"),
    timeout_seconds: int = typer.Option(600, min=10, help="How long to wait for manual browser sign-in."),
) -> None:
    """Open ChatGPT for manual sign-in. Credentials are never requested or read."""
    with authenticated_page(profile_dir) as page:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        typer.echo("Complete sign-in in Chromium. The command detects the ChatGPT interface automatically.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if interface_is_authenticated(page):
                break
            page.wait_for_timeout(1000)
        else:
            raise typer.Exit("Authentication was not detected before timeout. No credentials were collected.")
    typer.echo("Authenticated interface detected; profile retained locally.")


@app.command(name="discover")
def discover_command(
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(Path(".playwright-profile")),
    limit: int | None = typer.Option(None, min=1, help="Stop after this many unique conversations."),
    verbose: bool = typer.Option(False, help="Print non-sensitive discovery counts."),
    cdp_url: str | None = typer.Option(None, help="Optional loopback Chrome Beta CDP endpoint; never a profile path."),
) -> None:
    """Discover sidebar conversations and merge them into a resumable manifest."""
    store, profile = paths(data_dir, profile_dir)
    with authenticated_page(profile, headless=not cdp_url, cdp_url=cdp_url) as page:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        entries = discover(page, limit=limit)
        manifest = store.merge_discovery(entries)
    if verbose:
        typer.echo(f"run_discovered={len(entries)} manifest_total={len(manifest.entries)}")
    typer.echo(f"Discovered {len(manifest.entries)} unique conversations.")


@app.command(name="sync")
def sync(
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(Path(".playwright-profile")),
    limit: int | None = typer.Option(None, min=1, help="Archive at most this many entries."),
    conversation: str | None = typer.Option(None, help="Archive one discovered conversation ID."),
    debug_dir: Path | None = typer.Option(None, help="Opt-in ignored directory for failed-page screenshot and HTML."),
    verbose: bool = typer.Option(False, help="Print non-sensitive per-conversation progress."),
    cdp_url: str | None = typer.Option(None, help="Optional loopback Chrome Beta CDP endpoint; never a profile path."),
) -> None:
    """Archive pending/failed entries, continuing after individual failures."""
    store, profile = paths(data_dir, profile_dir)
    manifest = store.load_manifest()
    pending = [entry for entry in manifest.entries if entry.status != CaptureStatus.COMPLETED]
    if conversation:
        pending = [entry for entry in pending if entry.conversation_id == conversation]
        if not pending:
            raise typer.BadParameter("Conversation ID is not pending in this manifest.", param_hint="--conversation")
    if limit:
        pending = pending[:limit]
    with authenticated_page(profile, headless=not cdp_url, cdp_url=cdp_url) as page:
        if not interface_is_authenticated(page):
            page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        acquirer = PlaywrightAcquirer(page)
        for entry in pending:
            try:
                if verbose:
                    typer.echo(f"syncing={entry.conversation_id}")
                conversation = acquirer.fetch(entry.source_url, entry.conversation_id, entry.title)
                store.save_conversation(conversation, render_conversation(conversation))
                store.mark_complete(entry.conversation_id)
            except Exception as exc:
                artifacts = capture_failure_artifacts(page, debug_dir, entry.conversation_id) if debug_dir else []
                store.record_failure(FailureRecord(
                    conversation_id=entry.conversation_id, source_url=entry.source_url, stage="sync",
                    category=type(exc).__name__, message=str(exc), debug_artifacts=artifacts,
                ))
                typer.echo(f"Failed {entry.conversation_id}: {type(exc).__name__}", err=True)
    status(data_dir)


@app.command()
def status(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Print manifest state without opening a browser."""
    manifest = ArchiveStore(data_dir).load_manifest()
    counts = Counter(entry.status.value for entry in manifest.entries)
    typer.echo(f"discovered={len(manifest.entries)} pending={counts['pending']} completed={counts['completed']} failed={counts['failed']}")
    typer.echo(f"last_synchronization={manifest.last_synchronization_at.isoformat() if manifest.last_synchronization_at else 'never'}")


@app.command()
def inspect(
    conversation_id: str,
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(Path(".playwright-profile")),
    cdp_url: str | None = typer.Option(None, help="Optional loopback Chrome Beta CDP endpoint; never a profile path."),
) -> None:
    """Inspect one discovered conversation's browser workflow without printing content."""
    entry = next((item for item in ArchiveStore(data_dir).load_manifest().entries if item.conversation_id == conversation_id), None)
    if entry is None:
        raise typer.BadParameter("Conversation ID is not present in the manifest.")
    with authenticated_page(profile_dir, headless=not cdp_url, cdp_url=cdp_url) as page:
        observer = NetworkObserver()
        observer.attach(page)
        page.goto(entry.source_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        turns = page.locator("[data-message-author-role]").count()
    typer.echo(f"conversation_id={conversation_id} visible_turns={turns} relevant_responses={len(observer.responses)}")
    for response in observer.responses:
        typer.echo(f"response={response['status']} {response['content_type']} {response['origin']}{response['path']}")


if __name__ == "__main__":
    app()
