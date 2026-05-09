"""Safety checks and confirmation prompts for destructive operations."""

from __future__ import annotations

from .ui import console, ask_confirm, error, warning, info


def confirm_destructive(
    *,
    action_name: str,
    count: int,
    account: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Ask user to confirm a destructive action.

    Returns True if the user confirms (or dry_run is True).
    """
    if dry_run:
        info(f"DRY RUN: would {action_name} {count} items (no changes made)")
        return True

    console.print()
    who = f"@{account}" if account else "your account"
    console.print(
        f"  [bold red]This will {action_name} {count:,} items from {who}.[/bold red]"
    )
    console.print(
        "  [dim]Deleted content cannot be recovered. "
        "X profile counters may take hours to update.[/dim]"
    )
    console.print()
    return ask_confirm("Proceed?", default=False)


def confirm_typed(
    *,
    action_name: str,
    count: int,
    account: str | None = None,
) -> bool:
    """Require user to type 'yes' for high-risk bulk operations."""
    console.print()
    who = f"@{account}" if account else "your account"
    console.print(
        f"  [bold red]WARNING: This will {action_name} {count:,} items "
        f"from {who}.[/bold red]"
    )
    console.print(
        "  [bold]Deleted tweets CANNOT be recovered.[/bold]"
    )
    console.print()
    try:
        raw = input("  Type 'yes' to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]cancelled[/yellow]")
        return False
    if raw != "yes":
        warning("Aborted.")
        return False
    return True


def check_cookies_exist() -> bool:
    """Check if credentials file exists. Returns True if present."""
    from pathlib import Path
    import os
    path = Path(os.path.expanduser("~/.xtool/cookies.json"))
    if not path.exists():
        error("No saved cookies found.")
        console.print(
            "  Run [cyan]xtool login[/cyan] or use the menu to set up "
            "your X session cookies first."
        )
        return False
    return True


def check_archive_path(path: str) -> dict[str, str | None]:
    """Check an archive folder for known data files.

    Returns a dict with keys 'tweets', 'likes' pointing to file paths
    or None if not found.
    """
    from pathlib import Path

    root = Path(path).expanduser().resolve()
    result: dict[str, str | None] = {"tweets": None, "likes": None}

    # Common archive layouts:
    # <root>/data/tweets.js  or  <root>/data/tweet.js
    # <root>/data/like.js    or  <root>/data/likes.js
    # Or flat: <root>/tweets.js
    candidates_tweets = [
        root / "data" / "tweets.js",
        root / "data" / "tweet.js",
        root / "tweets.js",
        root / "tweet.js",
    ]
    candidates_likes = [
        root / "data" / "like.js",
        root / "data" / "likes.js",
        root / "like.js",
        root / "likes.js",
    ]

    for p in candidates_tweets:
        if p.exists():
            result["tweets"] = str(p)
            break

    for p in candidates_likes:
        if p.exists():
            result["likes"] = str(p)
            break

    return result
