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
from .deleter import (
    Credentials,
    DELETE_QUERY_ID,
    DeleteStats,
    bulk_delete,
)
from .filters import FilterOpts, apply_filter, classify, load_keep_ids, parse_created_at
from .parser import iter_tweets, read_jsonl, write_jsonl


COOKIES_PATH = Path(os.path.expanduser("~/.xtool/cookies.json"))
console = Console()


# ---------------------------------------------------------------------------
# subcommand: parse
# ---------------------------------------------------------------------------
def cmd_parse(args: argparse.Namespace) -> int:
    out = args.output or "tweets.jsonl"
    n = write_jsonl(iter_tweets(args.archive), out)
    console.print(f"[green]wrote[/green] {n} tweets -> {out}")
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
# subcommand: delete
# ---------------------------------------------------------------------------
def _load_credentials(args: argparse.Namespace) -> Credentials | None:
    if args.auth_token and args.ct0:
        return Credentials(args.auth_token, args.ct0)
    path = Path(args.cookies_file) if args.cookies_file else COOKIES_PATH
    if path.exists():
        return Credentials.from_file(path)
    return None


def _iter_ids(path: str) -> Iterable[str]:
    # Accept either a JSONL of tweets or a plain text file of ids.
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    tid = str(obj.get("id_str") or obj.get("id") or "")
                    if tid:
                        yield tid
                except ValueError:
                    continue
            else:
                yield line


def cmd_delete(args: argparse.Namespace) -> int:
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
        console.print("[yellow]nothing to do: 0 tweet ids[/yellow]")
        return 0

    console.print(
        f"[bold]Target:[/bold] {len(ids)} tweets  "
        f"[bold]Rate:[/bold] {args.rate}/s  "
        f"[bold]Dry-run:[/bold] {args.dry_run}  "
        f"[bold]Resume:[/bold] {args.resume}"
    )

    query_id = os.environ.get("XTOOL_DELETE_QUERY_ID", DELETE_QUERY_ID)

    stats: DeleteStats
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as bar:
        task = bar.add_task("deleting", total=len(ids))

        def on_progress(s, tid, outcome):
            bar.update(
                task,
                advance=1,
                description=(
                    f"del={s.deleted} gone={s.already_gone} "
                    f"fail={s.failed} skip={s.skipped}"
                ),
            )

        stats = bulk_delete(
            ids,
            creds,
            rate=args.rate,
            dry_run=args.dry_run,
            log_path=args.log,
            resume=args.resume,
            on_progress=on_progress,
            query_id=query_id,
        )

    console.print(
        "\n[bold green]done[/bold green]  "
        f"deleted={stats.deleted}  already_gone={stats.already_gone}  "
        f"failed={stats.failed}  skipped={stats.skipped}  "
        f"attempted={stats.attempted}"
    )
    return 0 if stats.failed == 0 else 1


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xtool",
        description="Bulk-delete tweets from your X archive on Termux/Linux.",
    )
    p.add_argument("--version", action="version", version=f"xtool {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # parse
    sp = sub.add_parser("parse", help="convert tweet.js archive to JSONL")
    sp.add_argument("archive", help="path to tweets.js / tweet.js")
    sp.add_argument("-o", "--output", help="output JSONL (default tweets.jsonl)")
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

    # delete
    sp = sub.add_parser("delete", help="delete every tweet id in the input file")
    sp.add_argument(
        "input", help="JSONL of tweets or plain-text file with one id per line"
    )
    sp.add_argument("--auth-token", help="X auth_token cookie")
    sp.add_argument("--ct0", help="X ct0 cookie (CSRF)")
    sp.add_argument("--cookies-file", help=f"override default {COOKIES_PATH}")
    sp.add_argument("--rate", type=float, default=1.0, help="requests/sec (default 1)")
    sp.add_argument("--dry-run", action="store_true", help="don't actually delete")
    sp.add_argument("--log", default="deleted.jsonl", help="progress log file")
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
    sp.set_defaults(func=cmd_delete)

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
