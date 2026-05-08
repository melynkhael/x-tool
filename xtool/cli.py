"""Command-line entry point for xtool."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
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
    ActionStats,
    Credentials,
    bulk_action,
    get_action,
)
from .discovery import (
    CACHE_PATH as DISCOVERY_CACHE_PATH,
    FALLBACK_QUERY_IDS,
    discover_query_ids,
)
from .filters import FilterOpts, apply_filter, classify, load_keep_ids, parse_created_at
from .parser import iter_likes, iter_tweets, read_jsonl, write_jsonl


COOKIES_PATH = Path(os.path.expanduser("~/.xtool/cookies.json"))
console = Console()


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
    Credentials(auth_token=auth_token, ct0=ct0).to_file(COOKIES_PATH)
    console.print(f"[green]saved[/green] -> {COOKIES_PATH}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: discover
# ---------------------------------------------------------------------------
def cmd_discover(args: argparse.Namespace) -> int:
    ids = discover_query_ids(refresh=args.refresh, offline=args.offline)
    table = Table(title="GraphQL query IDs", show_header=True, header_style="bold")
    table.add_column("operation", style="cyan")
    table.add_column("query_id", style="bold")
    table.add_column("source")
    for op in sorted(ids):
        qid = ids[op]
        source = (
            "live" if qid != FALLBACK_QUERY_IDS.get(op) else "fallback"
        )
        table.add_row(op, qid, source)
    console.print(table)
    console.print(f"[dim]cache: {DISCOVERY_CACHE_PATH}[/dim]")
    return 0


# ---------------------------------------------------------------------------
# subcommand: delete / unretweet / unlike (shared code)
# ---------------------------------------------------------------------------
def _load_credentials(args: argparse.Namespace) -> Credentials | None:
    if args.auth_token and args.ct0:
        return Credentials(args.auth_token, args.ct0)
    path = Path(args.cookies_file) if args.cookies_file else COOKIES_PATH
    if path.exists():
        return Credentials.from_file(path)
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


def _run_bulk(args: argparse.Namespace, action_key: str, verb: str) -> int:
    creds = _load_credentials(args)
    if creds is None and not args.dry_run:
        console.print(
            "[red]no credentials found.[/red] Run [cyan]xtool login[/cyan] "
            "or pass [cyan]--auth-token[/cyan] and [cyan]--ct0[/cyan]."
        )
        return 2
    if creds is None:
        creds = Credentials("dry", "dry")

    ids = list(_iter_ids(args.input))
    if not ids:
        console.print("[yellow]nothing to do: 0 ids[/yellow]")
        return 0

    action = get_action(action_key)
    qid_override = getattr(args, "query_id", None)
    query_id = qid_override or action.query_id(offline=args.offline)

    console.print(
        f"[bold]Action:[/bold] {action.name}  "
        f"[bold]Target:[/bold] {len(ids)}  "
        f"[bold]Rate:[/bold] {args.rate}/s  "
        f"[bold]Dry-run:[/bold] {args.dry_run}  "
        f"[bold]Resume:[/bold] {args.resume}  "
        f"[bold]queryId:[/bold] {query_id}"
    )

    stats: ActionStats
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
            rate=args.rate,
            dry_run=args.dry_run,
            log_path=args.log,
            resume=args.resume,
            on_progress=on_progress,
            query_id=query_id,
        )

    console.print(
        "\n[bold green]done[/bold green]  "
        f"{action.past_tense}={stats.succeeded}  "
        f"{action.gone_tense}={stats.already_gone}  "
        f"failed={stats.failed}  skipped={stats.skipped}  "
        f"attempted={stats.attempted}"
    )
    return 0 if stats.failed == 0 else 1


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
