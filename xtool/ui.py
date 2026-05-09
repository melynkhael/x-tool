"""Rich UI helpers for xtool's interactive mode.

Provides reusable components: banners, menus, prompts, status indicators,
and formatted output so the wizard and CLI share a consistent look.
"""

from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

if TYPE_CHECKING:  # pragma: no cover - hint only
    from .auth import Identity

console = Console()

# ── App identity ──────────────────────────────────────────────────────────

APP_TITLE = "X-Tool"
APP_SUBTITLE = "X / Twitter Account Cleanup"
APP_VERSION_LINE = ""  # filled lazily


def _version() -> str:
    global APP_VERSION_LINE
    if not APP_VERSION_LINE:
        from . import __version__
        APP_VERSION_LINE = f"v{__version__}"
    return APP_VERSION_LINE


# ── Banner ────────────────────────────────────────────────────────────────

def print_banner() -> None:
    """Print the app header banner."""
    title = Text(f" {APP_TITLE} ", style="bold white on blue")
    subtitle = Text(f" {APP_SUBTITLE}  {_version()} ", style="dim")
    console.print()
    console.print(Panel(
        Text.assemble(title, "\n", subtitle),
        box=box.ROUNDED,
        border_style="blue",
        expand=False,
        padding=(0, 2),
    ))
    console.print()


# ── Account / identity status ─────────────────────────────────────────────

def format_identity_line(identity: "Identity | None") -> Text:
    """Render a single-line "Account: ..." summary of the current login
    state. Always returns a Text object so callers can wrap it in a
    Panel or print it inline without losing styling.

    The text is colour-coded:
        verified  -> green
        partial   -> yellow ("cookies saved, identity not verified")
        none      -> dim    ("not logged in")
    """
    t = Text()
    t.append("Account: ", style="bold")
    if identity is None or identity.status == "none":
        t.append("not logged in", style="dim")
        return t
    if identity.status == "verified" and identity.handle:
        t.append(f"@{identity.handle}", style="bold green")
        t.append(" verified", style="green")
        return t
    # partial, or verified-without-handle.
    if identity.handle:
        t.append(f"@{identity.handle}", style="bold yellow")
        t.append(" (identity not verified)", style="yellow")
    elif identity.user_id:
        t.append(
            f"user_id {identity.user_id}, identity not verified",
            style="yellow",
        )
    else:
        t.append("cookies saved, identity not verified", style="yellow")
    return t


def print_identity_status(identity: "Identity | None") -> None:
    """Print the menu-header identity line with leading indent to match
    the rest of the menu output."""
    line = Text("  ")
    line.append_text(format_identity_line(identity))
    console.print(line)


def print_identity_banner(identity: "Identity | None") -> None:
    """Post-login welcome / status banner. Multi-line, visually distinct
    from the menu-header one-liner."""
    from pathlib import Path
    import os

    cookies_path = Path(os.path.expanduser("~/.xtool/cookies.json"))

    if identity is None or identity.status == "none":
        panel = Panel(
            Text.assemble(
                ("Not logged in.\n", "bold red"),
                ("Run `xtool login` to save your X session cookies.", "dim"),
            ),
            border_style="red",
            box=box.ROUNDED,
            expand=False,
            padding=(0, 2),
        )
        console.print(panel)
        return

    if identity.status == "verified":
        body = Text()
        handle = identity.handle or "(unknown)"
        body.append(f"Logged in as @{handle}\n", style="bold green")
        if identity.user_id:
            body.append(f"User ID: {identity.user_id}\n", style="green")
        body.append(f"Cookies saved to {cookies_path}\n", style="dim")
        body.append(f"Source: {identity.source}", style="dim")
        panel = Panel(
            body,
            border_style="green",
            box=box.ROUNDED,
            expand=False,
            padding=(0, 2),
        )
        console.print(panel)
        return

    # partial
    body = Text()
    body.append("Cookies were saved, but X identity verification failed.\n",
                style="bold yellow")
    if identity.user_id:
        body.append(f"twid user_id: {identity.user_id}\n", style="yellow")
    body.append(
        "You may still be able to run actions, but account safety checks are disabled.\n",
        style="yellow",
    )
    body.append("Use dry-run first.", style="dim")
    if identity.detail:
        body.append(f"\n\n{identity.detail}", style="dim")
    panel = Panel(
        body,
        border_style="yellow",
        box=box.ROUNDED,
        expand=False,
        padding=(0, 2),
    )
    console.print(panel)


# ── Menu ──────────────────────────────────────────────────────────────────

def print_menu(items: list[tuple[str, str]], *, title: str = "") -> None:
    """Print a numbered menu.

    Args:
        items: list of (key, description) pairs.
               key is shown left-aligned (usually a number or letter).
        title: optional heading above the menu.
    """
    if title:
        console.print(f"[bold]{title}[/bold]")
        console.print()
    for key, desc in items:
        console.print(f"  [cyan]{key:>2}[/cyan]  {desc}")
    console.print()


def ask_choice(
    prompt: str = "Choose",
    *,
    valid: list[str] | None = None,
    default: str | None = None,
) -> str:
    """Prompt user for a menu choice. Returns stripped lowercase input.

    If ``valid`` is provided, re-prompts until a valid choice is given.
    """
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f"  {prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]cancelled[/yellow]")
            sys.exit(130)
        if not raw and default:
            raw = default
        choice = raw.lower()
        if valid is None or choice in valid:
            return choice
        console.print(f"  [red]invalid choice:[/red] {raw!r}")


def ask_input(prompt: str, *, default: str = "", secret: bool = False) -> str:
    """Simple text input with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass
            raw = getpass.getpass(f"  {prompt}{suffix}: ")
        else:
            raw = input(f"  {prompt}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]cancelled[/yellow]")
        sys.exit(130)
    return raw.strip() or default


def ask_confirm(prompt: str, *, default: bool = False) -> bool:
    """Yes/no confirmation. Returns bool."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]cancelled[/yellow]")
        return False
    if not raw:
        return default
    return raw in ("y", "yes")


# ── Status output ─────────────────────────────────────────────────────────

def success(msg: str) -> None:
    console.print(f"  [green]{msg}[/green]")


def warning(msg: str) -> None:
    console.print(f"  [yellow]{msg}[/yellow]")


def error(msg: str) -> None:
    console.print(f"  [red]{msg}[/red]")


def info(msg: str) -> None:
    console.print(f"  [dim]{msg}[/dim]")


def heading(msg: str) -> None:
    console.print(f"\n[bold]{msg}[/bold]")


# ── Tables ────────────────────────────────────────────────────────────────

def stats_table(
    data: dict[str, str | int],
    *,
    title: str = "Stats",
) -> None:
    """Print a key-value stats table."""
    table = Table(title=title, show_header=False, box=box.SIMPLE)
    table.add_column("key", style="cyan", min_width=20)
    table.add_column("value", style="bold")
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(table)


def summary_table(
    data: dict[str, int],
    *,
    title: str = "Summary",
) -> None:
    """Print an operation summary table (succeeded/failed/etc)."""
    table = Table(title=title, show_header=False, box=box.ROUNDED)
    table.add_column("metric", style="bold")
    table.add_column("count", justify="right")
    for k, v in data.items():
        style = "green" if "success" in k.lower() or "ok" in k.lower() else ""
        if "fail" in k.lower():
            style = "red"
        table.add_row(k, str(v), style=style)
    console.print(table)


# ── Misc ──────────────────────────────────────────────────────────────────

def divider() -> None:
    console.print("[dim]─" * 50 + "[/dim]")


def press_enter() -> None:
    """Wait for user to press Enter."""
    try:
        input("  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        pass
