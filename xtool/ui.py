"""Rich UI helpers for xtool's interactive mode.

Provides reusable components: banners, menus, prompts, status indicators,
and formatted output so the wizard and CLI share a consistent look.
"""

from __future__ import annotations

import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

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
