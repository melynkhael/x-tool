"""Interactive wizard / menu mode for xtool.

Provides a guided experience so users can clean up their X account
without memorizing CLI commands. Launched via ``xtool``, ``xtool menu``,
or ``xtool wizard``.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from . import __version__
from .ui import (
    console,
    print_banner,
    print_identity_banner,
    print_identity_status,
    print_menu,
    ask_choice,
    ask_input,
    ask_confirm,
    ask_secret,
    success,
    warning,
    error,
    info,
    heading,
    stats_table,
    summary_table,
    divider,
    press_enter,
)
from .safety import check_cookies_exist, check_archive_path, confirm_typed
from .logs import log_path_for, ensure_logs_dir
from . import auth


# ── State ─────────────────────────────────────────────────────────────────

COOKIES_PATH = Path(os.path.expanduser("~/.xtool/cookies.json"))

# Session state (persists while the menu is open)
_state: dict = {
    "tweets_file": None,
    "likes_file": None,
    "archive_path": None,
    "handle": None,
    "identity": None,  # xtool.auth.Identity | None
}


def _refresh_identity(*, force: bool = False) -> "auth.Identity | None":
    """Load cookies and probe the identity, caching the result in
    ``_state['identity']`` so the menu header can be redrawn every tick
    without hitting x.com on every keystroke.

    When no cookies exist the cached Identity is a ``status="none"``
    value, not ``None``, so the header always has something to render.
    """
    cached = _state.get("identity")
    if cached is not None and not force:
        return cached
    identity = auth.verify_from_cookie_file(
        COOKIES_PATH,
        expect_handle=_state.get("handle"),
    )
    _state["identity"] = identity
    if identity.handle and not _state.get("handle"):
        _state["handle"] = identity.handle
    return identity


# ── Main menu ─────────────────────────────────────────────────────────────

MENU_ITEMS = [
    ("1", "Login / update cookies"),
    ("2", "Load X archive"),
    ("3", "Show archive stats"),
    ("4", "Delete original tweets"),
    ("5", "Delete replies"),
    ("6", "Delete originals + replies"),
    ("7", "Remove reposts / retweets"),
    ("8", "Remove likes"),
    ("9", "Full cleanup (guided)"),
    ("t", "Troubleshooting"),
    ("0", "Exit"),
]


def run_menu() -> int:
    """Main interactive menu loop. Returns exit code."""
    print_banner()

    # Prime the identity cache on entry -- cheap when cookies are absent,
    # and having something to show in the header on the first iteration
    # is a big UX win.
    _refresh_identity(force=True)

    while True:
        print_identity_status(_state.get("identity"))
        console.print()
        print_menu(MENU_ITEMS, title="What would you like to do?")
        # Blank input is still treated as "Exit" (default="0"), but we
        # hide the "[0]" suffix because users found it confusing --
        # showing "[0]" next to "Choose" suggests 0 is just one of
        # many options rather than what happens on Enter.
        #
        # The prompt text itself stays intentionally terse: the menu
        # already lists each key (with "0  Exit" and "t  Troubleshooting"
        # spelled out), so repeating "(0-9, t)" in the prompt just
        # added noise for beginners.
        choice = ask_choice(
            "Choose option",
            valid=[k for k, _ in MENU_ITEMS],
            default="0",
            hide_default=True,
        )

        try:
            if choice == "1":
                _menu_login()
            elif choice == "2":
                _menu_load_archive()
            elif choice == "3":
                _menu_stats()
            elif choice == "4":
                _menu_delete(tweet_type="tweet")
            elif choice == "5":
                _menu_delete(tweet_type="reply")
            elif choice == "6":
                _menu_delete(tweet_type="tweet+reply")
            elif choice == "7":
                _menu_unretweet()
            elif choice == "8":
                _menu_unlike()
            elif choice == "9":
                _menu_full_cleanup()
            elif choice == "t":
                _menu_troubleshooting()
            elif choice == "0":
                console.print("\n[dim]Goodbye.[/dim]")
                return 0
        except KeyboardInterrupt:
            console.print("\n[yellow]interrupted[/yellow]")
            continue
        except Exception as exc:
            error(f"Unexpected error: {exc}")
            info("If this persists, try running with the CLI commands directly.")
            continue

        divider()


# ── 1. Login ──────────────────────────────────────────────────────────────

def _menu_login() -> None:
    heading("Login / Update Cookies")
    console.print()
    console.print("  To use X-Tool you need two cookies from your browser session:")
    console.print("  [bold]auth_token[/bold] and [bold]ct0[/bold]")
    console.print()
    console.print("  [dim]How to get them:[/dim]")
    console.print("   1. Open [cyan]https://x.com[/cyan] in your browser and log in.")
    console.print("   2. Open DevTools (F12 or Ctrl+Shift+I).")
    console.print("   3. Go to Application > Cookies > https://x.com")
    console.print("   4. Copy the values of [bold]auth_token[/bold] and [bold]ct0[/bold].")
    console.print()
    console.print(
        "  [dim]Note: the prompts below use hidden input -- nothing will "
        "appear as you paste. That's intentional; the cookie values are "
        "sensitive.[/dim]"
    )
    console.print()

    # Collect both secrets up front. Reject empty / whitespace / too-
    # short values here instead of saving a broken cookies.json the
    # user would only discover at the first bulk action.
    auth_token, at_err = ask_secret("auth_token", min_length=10)
    if at_err:
        error(f"auth_token is {at_err}. Cookies were not saved.")
        warning("Please paste the cookie value again.")
        return
    ct0, ct_err = ask_secret("ct0", min_length=10)
    if ct_err:
        error(f"ct0 is {ct_err}. Cookies were not saved.")
        warning("Please paste the cookie value again.")
        return

    from .actions import Credentials

    try:
        creds = Credentials(auth_token=auth_token, ct0=ct0)
    except ValueError as exc:
        error(str(exc))
        warning("Cookies were not saved. Please paste the cookie values again.")
        return

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        creds.to_file(COOKIES_PATH)
    success(f"Cookies saved to {COOKIES_PATH}")

    # Optional handle hint lets us upgrade "partial" to "verified" via
    # the handle-match fallback when the REST endpoints are dead. Keep
    # the prompt short so it renders on one line in narrow Termux
    # terminals.
    default_handle = _state.get("handle") or ""
    handle_prompt = "X handle without @ (optional)"
    if default_handle:
        # ask_input already prints "[default]" when a default is set;
        # no need to embed it in the prompt text.
        expect = ask_input(handle_prompt, default=default_handle)
    else:
        expect = ask_input(handle_prompt)
    expect_clean = expect.lstrip("@").strip() or None
    if expect_clean:
        _state["handle"] = expect_clean

    info("Verifying session with X...")
    identity = auth.verify_identity(creds, expect_handle=expect_clean)
    _state["identity"] = identity
    if identity.handle:
        _state["handle"] = identity.handle

    console.print()
    print_identity_banner(identity)


# ── 2. Load archive ──────────────────────────────────────────────────────

def _menu_load_archive() -> None:
    heading("Load X Archive")
    console.print()
    console.print("  Enter the path to your extracted X archive folder.")
    console.print("  [dim]This is the folder containing 'data/tweets.js' etc.[/dim]")
    console.print()

    default_path = _state.get("archive_path") or "~/x-archive"
    path = ask_input("Archive folder path", default=default_path)

    files = check_archive_path(path)
    _state["archive_path"] = path

    if files["tweets"]:
        _state["tweets_file"] = files["tweets"]
        success(f"Found tweets: {files['tweets']}")
    else:
        warning("tweets.js / tweet.js NOT found.")
        console.print(
            "  [dim]To get your archive: X Settings > Your Account > "
            "Download an archive of your data[/dim]"
        )

    if files["likes"]:
        _state["likes_file"] = files["likes"]
        success(f"Found likes: {files['likes']}")
    else:
        info("like.js not found (optional — needed only for unlike).")

    console.print()


# ── 3. Stats ──────────────────────────────────────────────────────────────

def _menu_stats() -> None:
    heading("Archive Stats")

    if not _state.get("tweets_file"):
        warning("No archive loaded. Use option 2 first.")
        return

    from .parser import iter_tweets, iter_likes
    from .filters import classify, parse_created_at

    counts = {"tweet": 0, "reply": 0, "retweet": 0}
    total = 0
    oldest: Optional[datetime] = None
    newest: Optional[datetime] = None

    for t in iter_tweets(_state["tweets_file"]):
        total += 1
        counts[classify(t)] += 1
        dt = parse_created_at(t)
        if dt:
            if oldest is None or dt < oldest:
                oldest = dt
            if newest is None or dt > newest:
                newest = dt

    likes_count = 0
    if _state.get("likes_file"):
        for _ in iter_likes(_state["likes_file"]):
            likes_count += 1

    data = {
        "Total tweets in archive": total,
        "Original tweets": counts["tweet"],
        "Replies": counts["reply"],
        "Retweets (archive)": counts["retweet"],
        "Likes (from like.js)": likes_count if _state.get("likes_file") else "n/a",
    }
    if oldest:
        data["Oldest tweet"] = oldest.strftime("%Y-%m-%d")
    if newest:
        data["Newest tweet"] = newest.strftime("%Y-%m-%d")

    console.print()
    stats_table(data, title="Your X Archive")
    console.print()


# ── 4/5/6. Delete tweets ─────────────────────────────────────────────────

def _menu_delete(tweet_type: str = "tweet") -> None:
    labels = {
        "tweet": "original tweets",
        "reply": "replies",
        "tweet+reply": "original tweets + replies",
    }
    heading(f"Delete {labels[tweet_type]}")

    if not check_cookies_exist():
        return
    if not _state.get("tweets_file"):
        warning("No archive loaded. Use option 2 first.")
        return

    from .parser import iter_tweets, write_jsonl
    from .filters import classify

    # Filter tweets by type
    info("Scanning archive...")
    ids: list[str] = []
    for t in iter_tweets(_state["tweets_file"]):
        c = classify(t)
        if tweet_type == "tweet+reply":
            if c in ("tweet", "reply"):
                tid = t.get("id_str") or t.get("id")
                if tid:
                    ids.append(str(tid))
        elif c == tweet_type:
            tid = t.get("id_str") or t.get("id")
            if tid:
                ids.append(str(tid))

    if not ids:
        warning(f"No {labels[tweet_type]} found in the archive.")
        return

    console.print(f"  Found [bold]{len(ids):,}[/bold] {labels[tweet_type]} to delete.")
    console.print()

    # Dry-run offer
    if ask_confirm("Run a dry-run first (recommended)?", default=True):
        info("Dry-run: no changes will be made.")
        _run_bulk_action("delete", ids, dry_run=True)
        console.print()
        if not ask_confirm("Now run for real?", default=False):
            info("Aborted.")
            return

    if not confirm_typed(
        action_name=f"delete {labels[tweet_type]}",
        count=len(ids),
        account=_state.get("handle"),
        verified=bool(_state.get("identity") and _state["identity"].verified),
    ):
        return

    _run_bulk_action("delete", ids, dry_run=False)


# ── 7. Unretweet ─────────────────────────────────────────────────────────

def _menu_unretweet() -> None:
    heading("Remove Reposts / Retweets")

    if not check_cookies_exist():
        return

    console.print()
    console.print(
        "  This uses the [bold]live timeline resolver[/bold] to find your "
        "active reposts and remove them."
    )
    console.print(
        "  [dim]Archive wrapper IDs don't work for unretweet — we need "
        "the real source tweet IDs from your live profile.[/dim]"
    )
    console.print()

    handle = _state.get("handle") or ask_input("Your X @handle (without @)")
    if not handle:
        error("Handle is required for repost resolution.")
        return
    handle = handle.lstrip("@")
    _state["handle"] = handle

    # With a handle in hand, give identity verification another shot;
    # the handle-match fallback can upgrade partial -> verified when
    # REST endpoints are down.
    _refresh_identity(force=True)

    from .actions import Credentials, build_session, ActionError
    from .resolver import resolve_screen_name, iter_live_retweets, ResolverError

    creds = Credentials.from_file(COOKIES_PATH)
    session = build_session(creds)

    # Resolve user ID
    info(f"Resolving @{handle}...")
    try:
        user_id = resolve_screen_name(session, handle, offline=False)
    except (ResolverError, ActionError) as exc:
        error(f"Could not resolve @{handle}: {exc}")
        return
    success(f"@{handle} = user_id {user_id}")

    # Walk timeline
    max_rounds = 3
    total_unretweeted = 0

    for round_num in range(1, max_rounds + 1):
        info(f"Round {round_num}: scanning live timeline for reposts...")
        retweets: list[dict] = []

        def on_page(stats):
            pass  # silent in wizard mode

        try:
            for rt in iter_live_retweets(
                session, user_id, max_tweets=10000, rate=1.0, on_page=on_page
            ):
                retweets.append(rt)
        except (ResolverError, ActionError) as exc:
            error(f"Resolver error: {exc}")
            break

        if not retweets:
            if round_num == 1:
                warning("No reposts found on your live timeline.")
                console.print(
                    "  [dim]If your profile still shows reposts, X may "
                    "be caching old data. Try again later.[/dim]"
                )
            else:
                success("No more reposts found. All clear!")
            break

        console.print(
            f"  Found [bold]{len(retweets)}[/bold] reposts to remove."
        )

        if round_num == 1:
            if not confirm_typed(
                action_name="unretweet reposts",
                count=len(retweets),
                account=handle,
                verified=bool(
                    _state.get("identity") and _state["identity"].verified
                ),
            ):
                return

        ids = [rt["id_str"] for rt in retweets]
        stats = _run_bulk_action("unretweet", ids, dry_run=False)
        if stats:
            total_unretweeted += stats.get("succeeded", 0)

        # Check if we should do another round
        if len(retweets) < 5:
            break
        if round_num < max_rounds:
            info("Checking for more reposts...")
            import time
            time.sleep(2)

    if total_unretweeted > 0:
        success(f"Total unretweeted: {total_unretweeted}")
        console.print(
            "  [dim]Note: X profile counters may take minutes/hours to update.[/dim]"
        )


# ── 8. Unlike ────────────────────────────────────────────────────────────

def _menu_unlike() -> None:
    heading("Remove Likes")

    if not check_cookies_exist():
        return

    if not _state.get("likes_file"):
        # Try to find it
        if _state.get("archive_path"):
            files = check_archive_path(_state["archive_path"])
            if files["likes"]:
                _state["likes_file"] = files["likes"]

    if not _state.get("likes_file"):
        warning("No like.js found. Load your archive first (option 2).")
        console.print(
            "  [dim]like.js is in your X archive under data/like.js[/dim]"
        )
        return

    from .parser import iter_likes

    info("Counting likes...")
    ids: list[str] = []
    for like in iter_likes(_state["likes_file"]):
        tid = like.get("id_str") or like.get("tweetId")
        if tid:
            ids.append(str(tid))

    if not ids:
        warning("No likes found in the archive.")
        return

    console.print(f"  Found [bold]{len(ids):,}[/bold] likes to remove.")
    console.print()

    if ask_confirm("Run a dry-run first?", default=True):
        _run_bulk_action("unlike", ids, dry_run=True)
        console.print()
        if not ask_confirm("Now run for real?", default=False):
            info("Aborted.")
            return

    if not confirm_typed(
        action_name="unlike tweets",
        count=len(ids),
        account=_state.get("handle"),
        verified=bool(_state.get("identity") and _state["identity"].verified),
    ):
        return

    _run_bulk_action("unlike", ids, dry_run=False)


# ── 9. Full cleanup ──────────────────────────────────────────────────────

def _menu_full_cleanup() -> None:
    heading("Full Cleanup (Guided)")
    console.print()
    console.print("  This will guide you through cleaning your entire account:")
    console.print("   1. Delete original tweets")
    console.print("   2. Delete replies")
    console.print("   3. Remove reposts")
    console.print("   4. Remove likes")
    console.print()

    if not check_cookies_exist():
        return
    if not _state.get("tweets_file"):
        warning("No archive loaded. Loading it now...")
        _menu_load_archive()
        if not _state.get("tweets_file"):
            return

    console.print()
    console.print("  [bold]Select what to clean:[/bold]")
    console.print()
    do_tweets = ask_confirm("Delete original tweets?", default=True)
    do_replies = ask_confirm("Delete replies?", default=True)
    do_reposts = ask_confirm("Remove reposts?", default=True)
    do_likes = ask_confirm("Remove likes?", default=True)
    console.print()

    if not any([do_tweets, do_replies, do_reposts, do_likes]):
        info("Nothing selected.")
        return

    # Show stats first
    _menu_stats()

    console.print()
    if not ask_confirm("Continue with the selected cleanup?", default=False):
        info("Aborted.")
        return

    # Execute in order
    if do_tweets:
        divider()
        _menu_delete(tweet_type="tweet")

    if do_replies:
        divider()
        _menu_delete(tweet_type="reply")

    if do_reposts:
        divider()
        _menu_unretweet()

    if do_likes:
        divider()
        _menu_unlike()

    divider()
    heading("Cleanup Complete")
    success("All selected operations finished.")
    console.print(
        "  [dim]X profile counters (tweet count, likes count) may take "
        "minutes or hours to reflect the changes.[/dim]"
    )


# ── Troubleshooting ──────────────────────────────────────────────────────

def _menu_troubleshooting() -> None:
    heading("Troubleshooting")
    console.print()

    issues = [
        ("Cookies expired", "Log back into x.com, copy fresh auth_token + ct0, run option 1."),
        ("'Rate limited' errors", "X limits ~1 request/sec. Lower --rate or wait 15 min and retry."),
        ("'Query ID stale' errors", "Run: xtool discover --refresh"),
        ("Reposts still showing", "X caches profile data. Wait 5-30 min and check again."),
        ("Archive file missing", "Download from: X Settings > Your Account > Download an archive."),
        ("Network/VPN issues", "Ensure you can reach x.com. Disable VPN if behind a captive portal."),
        ("Unlike shows 'not_liked'", "Normal — the tweet was already unliked or deleted by its author."),
        ("Delete cookies", f"Remove: {COOKIES_PATH}"),
    ]

    for title, fix in issues:
        console.print(f"  [bold cyan]{title}[/bold cyan]")
        console.print(f"    {fix}")
        console.print()

    console.print(
        "  [dim]For other issues: "
        "https://github.com/melynkhael/x-tool/issues[/dim]"
    )
    console.print()


# ── Bulk action runner (shared) ───────────────────────────────────────────

def _run_bulk_action(
    action_key: str,
    ids: list[str],
    *,
    dry_run: bool = False,
) -> dict[str, int] | None:
    """Run a bulk action with progress bar. Returns summary dict or None on error."""
    from .actions import (
        ActionError,
        ActionStats,
        Credentials,
        build_session,
        bulk_action,
        get_action,
    )

    if dry_run:
        creds = Credentials(
            auth_token="dry-run-placeholder-auth-token-value-0000",
            ct0="dry-run-placeholder-ct0-csrf-token-value-0",
        )
    else:
        try:
            creds = Credentials.from_file(COOKIES_PATH)
        except ValueError as exc:
            error(f"Credentials error: {exc}")
            return None

    action = get_action(action_key)
    log_file = log_path_for(action_key)

    try:
        qid = action.query_id(offline=False)
    except Exception:
        qid = action.query_id(offline=True)

    stats: ActionStats
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as bar:
            task = bar.add_task(
                f"{'(dry-run) ' if dry_run else ''}{action_key}",
                total=len(ids),
            )

            def on_progress(s, tid, outcome):
                bar.update(
                    task,
                    advance=1,
                    description=(
                        f"ok={s.succeeded} gone={s.already_gone} "
                        f"fail={s.failed}"
                    ),
                )

            stats = bulk_action(
                ids,
                creds,
                action,
                rate=1.0,
                dry_run=dry_run,
                log_path=str(log_file),
                resume=True,
                on_progress=on_progress,
                query_id=qid,
            )
    except ActionError as exc:
        error(f"Operation aborted: {exc}")
        return None

    result = {
        "succeeded": stats.succeeded,
        "already_gone": stats.already_gone,
        "failed": stats.failed,
        "skipped": stats.skipped,
    }

    console.print()
    summary_table(
        {
            f"{action.past_tense}": stats.succeeded,
            f"{action.gone_tense}": stats.already_gone,
            "failed": stats.failed,
            "skipped (resume)": stats.skipped,
        },
        title="Result",
    )
    info(f"Log: {log_file}")
    console.print()

    return result
