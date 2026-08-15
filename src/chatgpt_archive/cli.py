from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer

from .browser import CHATGPT_HOME, authenticated_page, interface_is_authenticated
from .discovery import discover
from .extractor import PlaywrightAcquirer
from .markdown import render_conversation
from .models import CaptureStatus
from .storage import ArchiveStore

app = typer.Typer(help="Local-first archival for conversations owned by the authenticated ChatGPT user.")


def paths(data_dir: Path, profile_dir: Path) -> tuple[ArchiveStore, Path]:
    return ArchiveStore(data_dir), profile_dir


@app.command()
def login(profile_dir: Path = typer.Option(Path(".playwright-profile"), help="Ignored persistent Playwright profile")) -> None:
    """Open ChatGPT for manual sign-in. Credentials are never requested or read."""
    with authenticated_page(profile_dir) as page:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        typer.echo("Complete sign-in in Chromium. Press Enter here when the ChatGPT interface is visible.")
        input()
        if not interface_is_authenticated(page):
            raise typer.Exit("Authentication was not detected. No credentials were collected.")
    typer.echo("Authenticated interface detected; profile retained locally.")


@app.command(name="discover")
def discover_command(
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(Path(".playwright-profile")),
) -> None:
    """Discover sidebar conversations and merge them into a resumable manifest."""
    store, profile = paths(data_dir, profile_dir)
    with authenticated_page(profile, headless=True) as page:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        manifest = store.merge_discovery(discover(page))
    typer.echo(f"Discovered {len(manifest.entries)} unique conversations.")


@app.command(name="sync")
def sync(
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(Path(".playwright-profile")),
) -> None:
    """Archive pending/failed entries, continuing after individual failures."""
    store, profile = paths(data_dir, profile_dir)
    manifest = store.load_manifest()
    pending = [entry for entry in manifest.entries if entry.status != CaptureStatus.COMPLETED]
    with authenticated_page(profile, headless=True) as page:
        if not interface_is_authenticated(page):
            page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        acquirer = PlaywrightAcquirer(page)
        for entry in pending:
            try:
                conversation = acquirer.fetch(entry.source_url, entry.conversation_id, entry.title)
                store.save_conversation(conversation, render_conversation(conversation))
                store.mark_complete(entry.conversation_id)
            except Exception as exc:
                store.mark_failed(entry.conversation_id, f"{type(exc).__name__}: {exc}")
                typer.echo(f"Failed {entry.conversation_id}: {type(exc).__name__}", err=True)
    status(data_dir)


@app.command()
def status(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Print manifest state without opening a browser."""
    manifest = ArchiveStore(data_dir).load_manifest()
    counts = Counter(entry.status.value for entry in manifest.entries)
    typer.echo(f"discovered={len(manifest.entries)} pending={counts['pending']} completed={counts['completed']} failed={counts['failed']}")
    typer.echo(f"last_synchronization={manifest.last_synchronization_at.isoformat() if manifest.last_synchronization_at else 'never'}")


if __name__ == "__main__":
    app()
