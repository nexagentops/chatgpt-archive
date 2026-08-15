from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import time
import resource
import os
import subprocess

import typer

from . import __version__
from .browser import DEFAULT_PROFILE_DIR, CHATGPT_HOME, NetworkObserver, authenticated_page, interface_is_authenticated
from .diagnostics import capture_failure_artifacts
from .discovery import discover_with_metadata
from .extractor import PlaywrightAcquirer
from .markdown import render_conversation
from .models import CaptureStatus, FailureRecord
from .storage import ArchiveStore
from .operations import backup as create_backup, export_csv, migrate as migrate_archive, reindex, render_markdown, verify as verify_archive

app = typer.Typer(help="Local-first archival for conversations owned by the authenticated ChatGPT user.")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True, help="Show package version."),
) -> None:
    """Archive conversations from an authenticated local browser session."""


def _rss_mb() -> float | None:
    """Return current process RSS using the platform process inspector only."""
    try:
        kilobytes = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True).strip())
        return kilobytes / 1024
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def paths(data_dir: Path, profile_dir: Path) -> tuple[ArchiveStore, Path]:
    return ArchiveStore(data_dir), profile_dir


@app.command()
def login(
    profile_dir: Path = typer.Option(DEFAULT_PROFILE_DIR, help="Persistent browser profile outside the repository by default"),
    timeout_seconds: int = typer.Option(600, min=10, help="How long to wait for manual browser sign-in."),
) -> None:
    """Open ChatGPT for manual sign-in. Credentials are never requested or read."""
    typer.echo(f"Using browser profile: {profile_dir}")
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
    profile_dir: Path = typer.Option(DEFAULT_PROFILE_DIR, help="Persistent browser profile outside the repository by default"),
    limit: int | None = typer.Option(None, min=1, help="Stop after this many unique conversations."),
    verbose: bool = typer.Option(False, help="Print non-sensitive discovery counts."),
    cdp_url: str | None = typer.Option(None, help="Optional loopback Chrome Beta CDP endpoint; never a profile path."),
) -> None:
    """Discover sidebar conversations and merge them into a resumable manifest."""
    store, profile = paths(data_dir, profile_dir)
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    previous = store.load_manifest()
    previous_ids = {entry.conversation_id for entry in previous.entries}
    with authenticated_page(profile, headless=not cdp_url, cdp_url=cdp_url) as page:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        result = discover_with_metadata(page, limit=limit, on_batch=store.merge_discovery)
        manifest = store.merge_discovery(result.entries)
    # A complete structured enumeration is the only authority that can mark a
    # historical local archive remote-missing.  Canonical JSON is never deleted.
    store.index.reconcile_remote_presence(
        {entry.conversation_id for entry in result.entries}, history_complete=result.complete,
    )
    new_count = sum(entry.conversation_id not in previous_ids for entry in result.entries)
    existing_count = len(result.entries) - new_count
    duplicate_count = len(result.entries) - len({entry.conversation_id for entry in result.entries})
    store.index.record_discovery_run(
        requested_limit=limit,
        discovered_count=len(result.entries), new_count=new_count, existing_count=existing_count,
        duplicate_count=duplicate_count, complete=result.complete,
        termination_reason=result.termination_reason, source_method_counts=result.source_method_counts,
        pages_or_batches=result.batches, started_at=started_at,
        elapsed_seconds=time.monotonic() - started,
    )
    if verbose:
        typer.echo(f"run_discovered={len(result.entries)} new={new_count} existing={existing_count} duplicates={duplicate_count} manifest_total={len(manifest.entries)} termination={result.termination_reason} complete={result.complete} batches={result.batches} sources={result.source_method_counts}")
    typer.echo(f"Discovered {len(manifest.entries)} unique conversations.")


@app.command(name="sync")
def sync(
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(DEFAULT_PROFILE_DIR, help="Persistent browser profile outside the repository by default"),
    limit: int | None = typer.Option(None, min=1, help="Archive at most this many entries."),
    conversation: str | None = typer.Option(None, help="Archive one discovered conversation ID."),
    debug_dir: Path | None = typer.Option(None, help="Opt-in ignored directory for failed-page screenshot and HTML."),
    verbose: bool = typer.Option(False, help="Print non-sensitive per-conversation progress."),
    cdp_url: str | None = typer.Option(None, help="Optional loopback Chrome Beta CDP endpoint; never a profile path."),
    refresh: bool = typer.Option(False, help="Recapture completed entries; unchanged hashes are not rewritten."),
    max_attempts: int = typer.Option(3, min=1, max=5, help="Bounded attempts for temporary browser failures."),
) -> None:
    """Archive pending/failed entries, continuing after individual failures."""
    store, profile = paths(data_dir, profile_dir)
    manifest = store.load_manifest()
    pending = list(manifest.entries) if refresh else [entry for entry in manifest.entries if entry.status != CaptureStatus.COMPLETED]
    if conversation:
        pending = [entry for entry in pending if entry.conversation_id == conversation]
        if not pending:
            raise typer.BadParameter("Conversation ID is not pending in this manifest.", param_hint="--conversation")
    if limit:
        pending = pending[:limit]
    run_id = store.index.start_run(limit, len(manifest.entries))
    started = time.monotonic()
    metrics = {"archived": 0, "failed": 0, "new_count": 0, "changed_count": 0, "unchanged_count": 0, "retried": 0, "structured_count": 0, "dom_count": 0, "structured_failures": 0, "dom_failures": 0, "longest_capture_seconds": 0.0, "starting_rss_mb": _rss_mb()}
    with authenticated_page(profile, headless=not cdp_url, cdp_url=cdp_url) as page:
        if not interface_is_authenticated(page):
            page.goto(CHATGPT_HOME, wait_until="domcontentloaded")
        if not interface_is_authenticated(page):
            raise typer.Exit("Not authenticated. Run `chatgpt-archive login` first.")
        acquirer = PlaywrightAcquirer(page)
        for entry in pending:
            for attempt in range(1, max_attempts + 1):
                try:
                    if verbose:
                        typer.echo(f"syncing={entry.conversation_id} attempt={attempt}")
                    capture_started = time.monotonic()
                    captured = acquirer.fetch(entry.source_url, entry.conversation_id, entry.title)
                    metrics["longest_capture_seconds"] = max(metrics["longest_capture_seconds"], time.monotonic() - capture_started)
                    metrics["structured_failures"] += acquirer.structured_failures
                    existing = store.index.get(entry.conversation_id)
                    content_hash = store.content_hash(captured)
                    if existing is None:
                        metrics["new_count"] += 1
                    elif existing["content_hash"] == content_hash:
                        metrics["unchanged_count"] += 1
                    else:
                        metrics["changed_count"] += 1
                    if existing is None or existing["content_hash"] != content_hash:
                        store.save_conversation(captured, render_conversation(captured))
                        metrics["archived"] += 1
                    metrics["structured_count" if captured.capture_method == "structured_browser_response" else "dom_count"] += 1
                    store.mark_complete(entry.conversation_id)
                    break
                except Exception as exc:
                    if acquirer.used_dom_fallback:
                        metrics["dom_failures"] += 1
                    else:
                        metrics["structured_failures"] += acquirer.structured_failures
                    if attempt < max_attempts and type(exc).__name__ in {"RuntimeError", "TimeoutError"}:
                        metrics["retried"] += 1; time.sleep(min(2 ** (attempt - 1), 4)); continue
                    artifacts = capture_failure_artifacts(page, debug_dir, entry.conversation_id) if debug_dir else []
                    store.record_failure(FailureRecord(
                        conversation_id=entry.conversation_id, source_url=entry.source_url, stage="sync",
                        category=type(exc).__name__, message=str(exc), debug_artifacts=artifacts,
                    ))
                    typer.echo(f"Failed {entry.conversation_id}: {type(exc).__name__}", err=True)
                    metrics["failed"] += 1
                    break
    metrics["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    metrics["ending_rss_mb"] = _rss_mb()
    metrics["elapsed_seconds"] = time.monotonic() - started
    store.index.finish_run(run_id, "completed" if not metrics["failed"] else "completed_with_failures", **metrics)
    status(data_dir)


@app.command()
def status(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Print manifest state without opening a browser."""
    manifest = ArchiveStore(data_dir).load_manifest()
    counts = Counter(entry.status.value for entry in manifest.entries)
    typer.echo(f"discovered={len(manifest.entries)} pending={counts['pending']} completed={counts['completed']} failed={counts['failed']}")
    typer.echo(f"last_synchronization={manifest.last_synchronization_at.isoformat() if manifest.last_synchronization_at else 'never'}")


@app.command(name="reindex")
def reindex_command(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Rebuild the SQLite operational index from canonical JSON without altering archives."""
    typer.echo(f"indexed={reindex(ArchiveStore(data_dir))}")


@app.command(name="render-markdown")
def render_markdown_command(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Regenerate derived Markdown from canonical JSON without recapturing."""
    typer.echo(f"rendered={render_markdown(ArchiveStore(data_dir))}")


@app.command()
def migrate(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Explicitly migrate canonical archive files to the supported schema version."""
    typer.echo(f"migrated={migrate_archive(ArchiveStore(data_dir))}")


@app.command(name="export-csv")
def export_csv_command(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Regenerate deterministic CSV exports from canonical JSON."""
    counts = export_csv(ArchiveStore(data_dir))
    typer.echo(f"conversations={counts['conversations']} messages={counts['messages']}")


@app.command()
def verify(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Check canonical files, derived Markdown, hashes, and the operational index."""
    result = verify_archive(ArchiveStore(data_dir))
    typer.echo(" ".join(f"{key}={value}" for key, value in sorted(result.items())))
    if result["errors"]:
        raise typer.Exit(1)


@app.command()
def stats(data_dir: Path = typer.Option(Path("data"))) -> None:
    """Show fast operational totals from SQLite."""
    store = ArchiveStore(data_dir)
    totals = store.index.totals()
    typer.echo(f"conversations={totals['conversations']} messages={totals['messages']}")
    if run := store.index.latest_run():
        typer.echo(f"last_run={run['result']} archived={run['archived']} failed={run['failed']} structured={run['structured_count']} dom={run['dom_count']} peak_rss_mb={run['peak_rss_mb']}")


@app.command()
def doctor(
    data_dir: Path = typer.Option(Path("data")),
    cdp_url: str | None = typer.Option(None, help="Optional loopback endpoint to validate connectivity."),
) -> None:
    """Check local archive health without inspecting browser storage or credentials."""
    store = ArchiveStore(data_dir); store.initialize()
    result = {"archive_writable": store.root.exists(), "sqlite": store.index.path.exists(), "cdp": "not_checked"}
    if cdp_url:
        try:
            with authenticated_page(DEFAULT_PROFILE_DIR, cdp_url=cdp_url) as page:
                result["cdp"] = "connected"; result["chatgpt_authenticated"] = interface_is_authenticated(page)
        except Exception:
            result["cdp"] = "unavailable"
    typer.echo(" ".join(f"{key}={value}" for key, value in sorted(result.items())))


@app.command()
def backup(destination: Path, data_dir: Path = typer.Option(Path("data"))) -> None:
    """Copy archival data only; browser authentication state is never included."""
    typer.echo(f"backup={create_backup(ArchiveStore(data_dir), destination)}")


@app.command()
def inspect(
    conversation_id: str,
    data_dir: Path = typer.Option(Path("data")),
    profile_dir: Path = typer.Option(DEFAULT_PROFILE_DIR, help="Persistent browser profile outside the repository by default"),
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
