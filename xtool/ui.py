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
    """Print the app header banner.

    Includes a small attribution line under the subtitle so users who
    discover xtool from a fork or a screenshot can tell who maintains
    it. Kept dim / short so it doesn't compete with the title.
    """
    title = Text(f" {APP_TITLE} ", style="bold white on blue")
    subtitle = Text(f" {APP_SUBTITLE}  {_version()} ", style="dim")
    author = Text(" by: melynkhael ", style="dim")
    console.print()
    console.print(Panel(
        Text.assemble(title, "\n", subtitle, "\n", author),
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
        verified                   -> green
        partial w/ handle or twid  -> yellow (still useful information)
        partial w/ cookies only    -> yellow ("identity not verified")
        none                       -> dim ("not logged in")
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
    # partial branches
    if identity.handle:
        t.append(f"@{identity.handle}", style="bold yellow")
        t.append(" (identity not verified)", style="yellow")
    elif identity.user_id:
        # Spec: menu header when only the twid is known should read
        # "Account: user id <id> from twid" -- show the user_id
        # explicitly so the user knows we *do* have something concrete.
        t.append(f"user id {identity.user_id} from twid", style="yellow")
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
    from the menu-header one-liner.

    Four shapes, one per identity state the tool can reach:

    * no cookies saved            -> red "Not logged in." panel
    * auth_token + ct0 only       -> yellow "Cookies saved, but X
                                     identity verification failed"
                                     panel. Mentions that account
                                     safety checks are disabled and
                                     recommends dry-run first.
    * twid known, handle unknown  -> yellow "Cookies saved. User ID
                                     from twid: N. Handle not
                                     verified." panel. Suggests
                                     ``--expect-handle`` to upgrade.
    * verified                    -> green welcome panel with handle,
                                     user id, source, and cookies
                                     path.
    """
    from pathlib import Path
    import os

    cookies_path = Path(os.path.expanduser("~/.xtool/cookies.json"))

    # --- none ---------------------------------------------------------
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

    # --- verified -----------------------------------------------------
    if identity.status == "verified":
        body = Text()
        handle = identity.handle or "(unknown)"
        body.append(f"Logged in as @{handle}\n", style="bold green")
        if identity.user_id:
            body.append(f"User ID: {identity.user_id}\n", style="green")
        # Describe how we verified, so users understand whether we
        # went through REST, matched a handle via GraphQL, or relied
        # on a twid cookie match.
        source_descriptions = {
            "rest": "X REST whoami",
            "handle-match": "handle matched via GraphQL",
            "twid": "twid cookie",
        }
        source_human = source_descriptions.get(identity.source, identity.source)
        body.append(f"Verification: {source_human}\n", style="dim")
        body.append(f"Cookies saved to {cookies_path}", style="dim")
        panel = Panel(
            body,
            border_style="green",
            box=box.ROUNDED,
            expand=False,
            padding=(0, 2),
        )
        console.print(panel)
        return

    # --- partial ------------------------------------------------------
    body = Text()
    if identity.user_id:
        # Spec: twid-only partial should tell the user what we know and
        # nudge them toward --expect-handle so they can unlock
        # verified.
        body.append("Cookies saved.\n", style="bold yellow")
        body.append(
            f"User ID from twid: {identity.user_id}\n", style="yellow"
        )
        body.append("Handle not verified.\n", style="yellow")
        body.append(
            "Use --expect-handle to verify this cookie belongs to a "
            "specific account.",
            style="dim",
        )
    else:
        body.append(
            "Cookies saved, but X identity verification failed.\n",
            style="bold yellow",
        )
        body.append(
            "Account safety checks are disabled.\n",
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
    hide_default: bool = False,
) -> str:
    """Prompt user for a menu choice. Returns stripped lowercase input.

    If ``valid`` is provided, re-prompts until a valid choice is given.
    When ``hide_default`` is set, the ``[default]`` suffix is NOT shown
    even though blank input still maps to ``default``. Use this when
    the default exists for convenience but printing ``[0]`` would be
    confusing to the user (e.g. the main menu, where "0" means Exit).
    """
    suffix = "" if hide_default or not default else f" [{default}]"
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


def ask_secret(
    label: str,
    *,
    min_length: int = 10,
) -> tuple[str, Optional[str]]:
    """Ask for a secret value (cookie, token) with an explicit hidden-input UX.

    The prompt makes it clear that input is intentionally hidden (a
    recurring Termux confusion: users see nothing as they paste and
    think the paste didn't land). After reading, we *never* echo the
    value back; we print a short safe confirmation like::

        auth_token captured: 40 chars

    Returns ``(value, error)``. On success ``error`` is None and the
    caller can continue. On failure ``value`` is empty and ``error``
    carries a short, user-facing explanation suitable for printing
    as-is ("empty", "only whitespace", "too short"). Callers are
    expected to refuse to proceed whenever ``error`` is non-None.

    ``min_length`` is a defence-in-depth check: X's real auth_token is
    40 hex chars and ct0 is 32-160 chars, so anything under 10 is a
    typo, not a valid cookie.
    """
    import getpass

    try:
        raw = getpass.getpass(f"  {label} (hidden, paste then press Enter): ")
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]cancelled[/yellow]")
        return "", "cancelled"

    # Distinguish the three failure modes so error messages are useful.
    if raw == "":
        return "", "empty"
    if not raw.strip():
        return "", "only whitespace"
    value = raw.strip()
    if len(value) < min_length:
        return "", f"too short ({len(value)} chars; expected at least {min_length})"

    # Safe confirmation -- character count only, never the value.
    console.print(f"  [green]{label} captured:[/green] {len(value)} chars")
    return value, None


def ask_secret_optional(
    label: str,
    *,
    min_length: int = 3,
) -> tuple[Optional[str], Optional[str]]:
    """Variant of :func:`ask_secret` for optional secrets.

    Users can press Enter without typing anything to skip. The prompt
    makes the "optional, press Enter to skip" contract obvious, and
    skipping is confirmed with a visible ``"<label> skipped"`` line so
    the user doesn't wonder whether their empty input was eaten.

    Returns ``(value, error)``:
      * ``(None, None)`` when the user skipped (empty / whitespace
        input). Callers treat this as "no value provided".
      * ``(value, None)`` when a usable value was entered. Safe
        confirmation is printed (length only, never the value).
      * ``("", error)`` when a non-empty value was entered but looked
        too short to be real. Callers should refuse to save.
    """
    import getpass

    try:
        raw = getpass.getpass(
            f"  {label} (optional, paste if available, press Enter to skip): "
        )
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]cancelled[/yellow]")
        return None, "cancelled"

    # Whitespace-only is treated as skip, not error: it's almost always
    # an accidental space from a one-handed phone paste.
    if not raw or not raw.strip():
        console.print(f"  [dim]{label} skipped[/dim]")
        return None, None

    value = raw.strip()
    if len(value) < min_length:
        return "", f"too short ({len(value)} chars; expected at least {min_length})"

    console.print(f"  [green]{label} captured:[/green] {len(value)} chars")
    return value, None


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
