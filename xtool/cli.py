"""Command-line entry point for xtool."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from dateutil import parser as dateparser
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import __version__
from .actions import (
    ActionError,
    ActionStats,
    Credentials,
    build_session,
    bulk_action,
    get_action,
    whoami,
)
from .discovery import (
    CACHE_PATH as DISCOVERY_CACHE_PATH,
    discover_with_sources,
)
from .filters import FilterOpts, apply_filter, classify, load_keep_ids, parse_created_at
from .parser import iter_likes, iter_tweets, read_jsonl, write_jsonl


COOKIES_PATH = Path(os.path.expanduser("~/.xtool/cookies.json"))
console = Console()

# Cap on --rate. X's real limits for DeleteTweet are roughly 1/sec over
# long windows. Anything above 2/sec is almost certain to trigger 429s
# and risks temporary account locks. We refuse to run faster without a
# user opt-in.
RATE_SAFETY_CEILING = 2.0


# ---------------------------------------------------------------------------
# subcommand: parse
# ---------------------------------------------------------------------------
def cmd_parse(args: argparse.Namespace) -> int:
    out = args.output or ("likes.jsonl" if args.likes else "tweets.jsonl")
    source = iter_likes(args.archive) if args.likes else iter_tweets(args.archive)
    n = write_jsonl(source, out)
    label = "likes" if args.likes else "tweets"
    console.print(f"[green]wrote[/green] {n} {label} -> {out}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: stats
# ---------------------------------------------------------------------------
def cmd_stats(args: argparse.Namespace) -> int:
    counts = {"tweet": 0, "reply": 0, "retweet": 0}
    total = 0
    oldest: datetime | None = None
    newest: datetime | None = None
    likes_total = 0
    rts_total = 0

    for t in read_jsonl(args.input):
        total += 1
        counts[classify(t)] += 1
        dt = parse_created_at(t)
        if dt:
            if oldest is None or dt < oldest:
                oldest = dt
            if newest is None or dt > newest:
                newest = dt
        try:
            likes_total += int(t.get("favorite_count") or 0)
            rts_total += int(t.get("retweet_count") or 0)
        except (TypeError, ValueError):
            pass

    table = Table(title=f"Archive stats: {args.input}", show_header=False)
    table.add_column("key", style="cyan")
    table.add_column("value", style="bold")
    table.add_row("total", str(total))
    table.add_row("original tweets", str(counts["tweet"]))
    table.add_row("replies", str(counts["reply"]))
    table.add_row("retweets", str(counts["retweet"]))
    if oldest and newest:
        table.add_row("oldest", oldest.isoformat())
        table.add_row("newest", newest.isoformat())
    table.add_row("total likes received", str(likes_total))
    table.add_row("total retweets received", str(rts_total))
    console.print(table)
    return 0


# ---------------------------------------------------------------------------
# subcommand: filter
# ---------------------------------------------------------------------------
def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = dateparser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def cmd_filter(args: argparse.Namespace) -> int:
    opts = FilterOpts(
        date_from=_parse_date(args.date_from),
        date_to=_parse_date(args.date_to),
        type=args.type,
        keyword=re.compile(args.keyword, re.IGNORECASE) if args.keyword else None,
        not_keyword=(
            re.compile(args.not_keyword, re.IGNORECASE) if args.not_keyword else None
        ),
        min_likes=args.min_likes,
        max_likes=args.max_likes,
        min_retweets=args.min_retweets,
        max_retweets=args.max_retweets,
        keep_ids=load_keep_ids(args.keep_ids),
    )
    out = args.output or "filtered.jsonl"
    n = write_jsonl(apply_filter(read_jsonl(args.input), opts), out)
    console.print(f"[green]kept[/green] {n} tweets -> {out}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: login
# ---------------------------------------------------------------------------
LOGIN_HELP = """\
[bold]How to grab your X session cookies[/bold]

  1. Open [cyan]https://x.com[/cyan] in a browser and log in.
  2. Open DevTools (F12).
     - Chrome/Edge: [yellow]Application -> Storage -> Cookies -> https://x.com[/yellow]
     - Firefox:     [yellow]Storage -> Cookies -> https://x.com[/yellow]
  3. Copy the values of [bold]auth_token[/bold] and [bold]ct0[/bold].

They will be saved to [cyan]~/.xtool/cookies.json[/cyan] with chmod 600.
"""


def cmd_login(args: argparse.Namespace) -> int:
    console.print(LOGIN_HELP)
    try:
        auth_token = input("auth_token: ").strip()
        ct0 = input("ct0: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[red]aborted[/red]")
        return 1
    if not auth_token or not ct0:
        console.print("[red]both values are required[/red]")
        return 1
    try:
        creds = Credentials(auth_token=auth_token, ct0=ct0)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        chmodded = creds.to_file(COOKIES_PATH)
        for w in caught:
            console.print(f"[yellow]warning:[/yellow] {w.message}")
    if chmodded:
        console.print(f"[green]saved[/green] -> {COOKIES_PATH} (chmod 600)")
    else:
        console.print(
            f"[yellow]saved[/yellow] -> {COOKIES_PATH} "
            "[yellow](could not chmod 600 - this path does not support "
            "POSIX permissions; move the file somewhere private)[/yellow]"
        )
    # Quick sanity check: can we authenticate?
    console.print("[dim]verifying cookies with X...[/dim]")
    session = build_session(creds)
    try:
        who = whoami(session)
    except ActionError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        console.print(
            "\n[yellow]Cookies were saved, but we could NOT verify your "
            "identity.[/yellow] You can still run bulk commands by adding "
            "[cyan]--skip-whoami[/cyan], but you lose the "
            "[cyan]--expect-account[/cyan] safety net. It's safer to refresh "
            "your cookies and rerun [cyan]xtool login[/cyan] first."
        )
        return 1
    console.print(f"[green]logged in as[/green] @{who['screen_name']}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: discover
# ---------------------------------------------------------------------------
def cmd_discover(args: argparse.Namespace) -> int:
    sources = discover_with_sources(refresh=args.refresh, offline=args.offline)
    table = Table(title="GraphQL query IDs", show_header=True, header_style="bold")
    table.add_column("operation", style="cyan")
    table.add_column("query_id", style="bold")
    table.add_column("source")
    for op in sorted(sources):
        qid, src = sources[op]
        colour = {"live": "green", "cache": "yellow", "fallback": "red"}.get(src, "")
        table.add_row(op, qid, f"[{colour}]{src}[/{colour}]" if colour else src)
    console.print(table)
    console.print(f"[dim]cache: {DISCOVERY_CACHE_PATH}[/dim]")
    # Hint if we're running blind.
    live_count = sum(1 for _q, s in sources.values() if s == "live")
    if live_count == 0 and not args.offline:
        console.print(
            "[yellow]no IDs came back live - check network access or "
            "rerun with --offline to use the bundled fallback table.[/yellow]"
        )
    return 0


# ---------------------------------------------------------------------------
# subcommand: delete / unretweet / unlike (shared code)
# ---------------------------------------------------------------------------
def _load_credentials(args: argparse.Namespace) -> Credentials | None:
    path = Path(args.cookies_file) if args.cookies_file else COOKIES_PATH
    try:
        if args.auth_token and args.ct0:
            return Credentials(args.auth_token, args.ct0)
        if path.exists():
            return Credentials.from_file(path)
    except ValueError as exc:
        console.print(f"[red]credentials error:[/red] {exc}")
        return None
    return None


def _iter_ids(path: str) -> Iterable[str]:
    """Accept either a JSONL of tweet/like objects or plain text ids."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    tid = str(
                        obj.get("id_str")
                        or obj.get("id")
                        or obj.get("tweetId")
                        or ""
                    )
                    if tid:
                        yield tid
                except ValueError:
                    continue
            else:
                yield line


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _run_bulk(args: argparse.Namespace, action_key: str, verb: str) -> int:
    creds = _load_credentials(args)
    if creds is None and not args.dry_run:
        console.print(
            "[red]no credentials found.[/red] Run [cyan]xtool login[/cyan] "
            "or pass [cyan]--auth-token[/cyan] and [cyan]--ct0[/cyan]."
        )
        return 2
    if creds is None:
        # Dry-run placeholder. Use 40-char values to avoid the
        # "suspiciously short" warning during dry runs.
        creds = Credentials(
            auth_token="dry-run-placeholder-auth-token-value-0000",
            ct0="dry-run-placeholder-ct0-csrf-token-value-0",
        )

    # Load ids up-front. De-dupe here too (bulk_action dedupes at the
    # attempt layer, but we want an accurate "target: N" banner).
    raw_ids = list(_iter_ids(args.input))
    seen: set[str] = set()
    ids: list[str] = []
    for tid in raw_ids:
        if tid in seen:
            continue
        seen.add(tid)
        ids.append(tid)
    dup_count = len(raw_ids) - len(ids)

    if not ids:
        console.print("[yellow]nothing to do: 0 ids[/yellow]")
        return 0

    action = get_action(action_key)
    qid_override = getattr(args, "query_id", None)
    query_id = qid_override or action.query_id(offline=args.offline)

    # ---- identity check ----------------------------------------------------
    screen_name: str | None = None
    if not args.dry_run and not args.skip_whoami:
        session = build_session(creds)
        try:
            who = whoami(session)
        except ActionError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2
        screen_name = who["screen_name"]
        if args.expect_account and args.expect_account.lstrip("@").lower() != screen_name.lower():
            console.print(
                f"[red]account mismatch:[/red] cookies belong to "
                f"@{screen_name} but --expect-account is "
                f"@{args.expect_account.lstrip('@')}. Refusing to run."
            )
            return 2
    elif not args.dry_run and args.skip_whoami:
        # User opted out of the identity check.
        if args.expect_account:
            console.print(
                "[red]--expect-account cannot be combined with "
                "--skip-whoami[/red] (that's the whole point of the "
                "check). Remove one or the other."
            )
            return 2
        console.print(
            "[yellow]warning:[/yellow] --skip-whoami: proceeding without "
            "verifying which account these cookies belong to."
        )

    # ---- rate-cap safety ---------------------------------------------------
    rate = args.rate
    if rate > RATE_SAFETY_CEILING and not args.i_know_what_im_doing:
        console.print(
            f"[red]refusing to run at {rate}/s.[/red] Rates above "
            f"{RATE_SAFETY_CEILING}/s are very likely to trigger 429s "
            "and short-term account locks. Re-run with "
            "[cyan]--i-know-what-im-doing[/cyan] to override, or lower "
            "[cyan]--rate[/cyan]."
        )
        return 2

    # ---- banner ------------------------------------------------------------
    who_line = (
        f"[bold]Account:[/bold] @{screen_name}  "
        if screen_name
        else (
            "[bold]Account:[/bold] [yellow](skipped whoami)[/yellow]  "
            if not args.dry_run
            else "[bold]Account:[/bold] (dry-run, cookies not verified)  "
        )
    )
    dup_line = f"  [dim](deduped {dup_count} duplicates)[/dim]" if dup_count else ""
    console.print(
        who_line
        + f"[bold]Action:[/bold] {action.name}  "
        + f"[bold]Target:[/bold] {len(ids)}{dup_line}  "
        + f"[bold]Rate:[/bold] {rate}/s  "
        + f"[bold]Dry-run:[/bold] {args.dry_run}  "
        + f"[bold]Resume:[/bold] {args.resume}  "
        + f"[bold]queryId:[/bold] {query_id}"
    )

    # ---- confirmation ------------------------------------------------------
    if not args.dry_run and not args.yes:
        est_mins = (len(ids) / max(rate, 0.01)) / 60.0
        who = f"@{screen_name}" if screen_name else "your account (identity not verified)"
        console.print(
            f"\n[bold red]This will run {action.name} on {len(ids)} "
            f"tweets from {who}.[/bold red]\n"
            f"Estimated duration: ~{est_mins:.1f} min at {rate}/s. "
            "Deleted tweets [bold]cannot be recovered[/bold]."
        )
        if not _confirm("Type 'yes' to proceed: "):
            console.print("[yellow]aborted[/yellow]")
            return 1

    # ---- run ---------------------------------------------------------------
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
            task = bar.add_task(verb, total=len(ids))

            def on_progress(s, tid, outcome):
                bar.update(
                    task,
                    advance=1,
                    description=(
                        f"ok={s.succeeded} gone={s.already_gone} "
                        f"fail={s.failed} skip={s.skipped}"
                    ),
                )

            stats = bulk_action(
                ids,
                creds,
                action,
                rate=rate,
                dry_run=args.dry_run,
                log_path=args.log,
                resume=args.resume,
                on_progress=on_progress,
                query_id=query_id,
            )
    except ActionError as exc:
        # auth_failed during the run -> abort cleanly.
        console.print(f"\n[red]bulk run aborted:[/red] {exc}")
        return 2

    console.print(
        "\n[bold green]done[/bold green]  "
        f"{action.past_tense}={stats.succeeded}  "
        f"{action.gone_tense}={stats.already_gone}  "
        f"failed={stats.failed}  skipped={stats.skipped}  "
        f"attempted={stats.attempted}"
    )

    # Surface the last failure reason so users don't have to grep the log.
    if stats.failed > 0:
        last_err = _last_log_error(args.log, _action_key_for(action_key))
        if last_err:
            console.print(
                f"[red]last failure:[/red] {last_err}\n"
                f"[dim]full log: {args.log}[/dim]"
            )
    return 0 if stats.failed == 0 else 1


def _action_key_for(action_key: str) -> str:
    # The log's 'action' field uses the table key, not the GraphQL name.
    return action_key


def _last_log_error(log_path: str, action_key: str) -> str | None:
    """Return the most recent 'error' field from a failed entry in the log."""
    try:
        with open(log_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("action") == action_key and rec.get("outcome") in ("failed", "auth_failed"):
            err = rec.get("error")
            if err:
                return str(err)[:500]
    return None


def cmd_delete(args: argparse.Namespace) -> int:
    return _run_bulk(args, "delete", "deleting")


def cmd_unretweet(args: argparse.Namespace) -> int:
    return _run_bulk(args, "unretweet", "unretweeting")


def cmd_unlike(args: argparse.Namespace) -> int:
    return _run_bulk(args, "unlike", "unliking")


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------
def _add_bulk_flags(sp: argparse.ArgumentParser, default_log: str) -> None:
    """Shared flags for delete / unretweet / unlike subcommands."""
    sp.add_argument(
        "input", help="JSONL of tweets/likes or plain-text file with one id per line"
    )
    sp.add_argument("--auth-token", help="X auth_token cookie")
    sp.add_argument("--ct0", help="X ct0 cookie (CSRF)")
    sp.add_argument("--cookies-file", help=f"override default {COOKIES_PATH}")
    sp.add_argument("--rate", type=float, default=1.0, help="requests/sec (default 1)")
    sp.add_argument("--dry-run", action="store_true", help="don't actually hit X")
    sp.add_argument("--log", default=default_log, help="progress log file")
    sp.add_argument(
        "--query-id",
        help="pin the GraphQL query id (overrides discovery and fallback)",
    )
    sp.add_argument(
        "--offline",
        action="store_true",
        help="don't fetch x.com to auto-discover query ids; use cache/fallback",
    )
    sp.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="skip the interactive confirmation prompt (still shows a banner)",
    )
    sp.add_argument(
        "--expect-account",
        metavar="SCREEN_NAME",
        help=(
            "abort if the authenticated account's screen_name doesn't "
            "match this (safety against running with the wrong cookies)"
        ),
    )
    sp.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help=(
            f"allow --rate above the {RATE_SAFETY_CEILING}/s safety ceiling"
        ),
    )
    sp.add_argument(
        "--skip-whoami",
        action="store_true",
        help=(
            "skip the account-identity check before running. Use ONLY "
            "when X has broken the REST endpoints we rely on; you lose "
            "the --expect-account safety net."
        ),
    )
    resume = sp.add_mutually_exclusive_group()
    resume.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="skip ids already in the log (default)",
    )
    resume.add_argument(
        "--no-resume", dest="resume", action="store_false", help="disable resume"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xtool",
        description="Bulk-delete tweets, undo retweets and unlike from your X archive.",
    )
    p.add_argument("--version", action="version", version=f"xtool {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # parse
    sp = sub.add_parser("parse", help="convert tweets.js / like.js archive to JSONL")
    sp.add_argument("archive", help="path to tweets.js, tweet.js or like.js")
    sp.add_argument("-o", "--output", help="output JSONL (auto-named if omitted)")
    sp.add_argument(
        "--likes",
        action="store_true",
        help="parse a like.js file instead of tweets.js",
    )
    sp.set_defaults(func=cmd_parse)

    # stats
    sp = sub.add_parser("stats", help="summarize a JSONL of tweets")
    sp.add_argument("input", help="JSONL of tweets")
    sp.set_defaults(func=cmd_stats)

    # filter
    sp = sub.add_parser("filter", help="filter a JSONL of tweets")
    sp.add_argument("input", help="JSONL of tweets")
    sp.add_argument("-o", "--output", help="output JSONL (default filtered.jsonl)")
    sp.add_argument("--from", dest="date_from", help="keep tweets on/after this date")
    sp.add_argument("--to", dest="date_to", help="keep tweets on/before this date")
    sp.add_argument(
        "--type",
        choices=["tweet", "retweet", "reply", "all"],
        default="all",
        help="filter by tweet type",
    )
    sp.add_argument("--keyword", help="keep tweets whose text matches this regex")
    sp.add_argument("--not-keyword", help="drop tweets whose text matches this regex")
    sp.add_argument("--min-likes", type=int)
    sp.add_argument("--max-likes", type=int)
    sp.add_argument("--min-retweets", type=int)
    sp.add_argument("--max-retweets", type=int)
    sp.add_argument("--keep-ids", help="file of tweet IDs (one per line) to exclude")
    sp.set_defaults(func=cmd_filter)

    # login
    sp = sub.add_parser("login", help="store X cookies in ~/.xtool/cookies.json")
    sp.set_defaults(func=cmd_login)

    # discover
    sp = sub.add_parser(
        "discover",
        help="auto-discover GraphQL query IDs from x.com's JS bundle",
    )
    sp.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the cache and fetch live",
    )
    sp.add_argument(
        "--offline",
        action="store_true",
        help="don't hit the network; show cache or fallback only",
    )
    sp.set_defaults(func=cmd_discover)

    # delete
    sp = sub.add_parser("delete", help="delete every tweet id in the input file")
    _add_bulk_flags(sp, default_log="deleted.jsonl")
    sp.set_defaults(func=cmd_delete)

    # unretweet
    sp = sub.add_parser(
        "unretweet",
        help="undo retweets for every source-tweet id in the input file",
    )
    _add_bulk_flags(sp, default_log="unretweeted.jsonl")
    sp.set_defaults(func=cmd_unretweet)

    # unlike
    sp = sub.add_parser(
        "unlike",
        help="remove your like from every tweet id in the input file",
    )
    _add_bulk_flags(sp, default_log="unliked.jsonl")
    sp.set_defaults(func=cmd_unlike)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        return 130
    except FileNotFoundError as exc:
        console.print(f"[red]file not found:[/red] {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - top-level guard
        console.print(f"[red]error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
