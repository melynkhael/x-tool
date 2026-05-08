"""Generic GraphQL mutation runner for X/Twitter web client.

xtool uses this same wiring to delete tweets, undo retweets, and undo
likes. Each supported operation is described once in ``ACTIONS`` and
every bulk-* subcommand goes through :func:`bulk_action`.

The authentication flow is identical to the web client:
* ``authorization`` - hard-coded public Bearer token from the JS bundle.
* ``x-csrf-token``  - value of the ``ct0`` cookie.
* ``cookie``        - at minimum ``auth_token`` + ``ct0``.

Endpoint shape::

    POST https://x.com/i/api/graphql/<queryId>/<OperationName>
    { "variables": {...}, "queryId": "<queryId>" }

Any "already gone" style error (tweet missing, retweet already undone,
like already removed) is treated as a successful no-op so reruns are
idempotent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

from .discovery import FALLBACK_QUERY_IDS, get_query_id


# Public Bearer token shipped in x.com's JavaScript bundle. Not a secret
# - every logged-in web session uses it.
WEB_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


class ActionError(Exception):
    """Non-retryable failure from a GraphQL mutation."""


class RateLimited(Exception):
    """HTTP 429 - caller should back off."""


@dataclass
class Credentials:
    auth_token: str
    ct0: str

    @classmethod
    def from_file(cls, path: str | Path) -> "Credentials":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(auth_token=data["auth_token"], ct0=data["ct0"])

    def to_file(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"auth_token": self.auth_token, "ct0": self.ct0}, indent=2),
            encoding="utf-8",
        )
        try:
            p.chmod(0o600)
        except OSError:
            pass


@dataclass(frozen=True)
class Action:
    """Description of one GraphQL mutation xtool knows how to run."""

    name: str  # GraphQL operation name, e.g. "DeleteTweet"
    build_variables: Callable[[str], dict]
    past_tense: str  # "deleted" / "unretweeted" / "unliked"
    gone_tense: str  # "already_gone" / "not_retweeted" / "not_liked"
    # Substrings that mean "there is nothing to do for this id".
    gone_markers: tuple[str, ...] = ()

    def query_id(self, *, offline: bool = False) -> str:
        return get_query_id(self.name, offline=offline)


# Built-in action table. Add entries here to support new mutations.
ACTIONS: dict[str, Action] = {
    "delete": Action(
        name="DeleteTweet",
        build_variables=lambda tid: {"tweet_id": str(tid), "dark_request": False},
        past_tense="deleted",
        gone_tense="already_gone",
        gone_markers=("not found", "no status found"),
    ),
    "unretweet": Action(
        name="UnretweetTweet",
        build_variables=lambda tid: {
            "source_tweet_id": str(tid),
            "dark_request": False,
        },
        past_tense="unretweeted",
        gone_tense="not_retweeted",
        gone_markers=(
            "not found",
            "no status found",
            "has not been retweeted",
            "sorry, you are not allowed",
        ),
    ),
    "unlike": Action(
        name="UnfavoriteTweet",
        build_variables=lambda tid: {"tweet_id": str(tid)},
        past_tense="unliked",
        gone_tense="not_liked",
        gone_markers=(
            "not found",
            "no status found",
            "has not been favorited",
        ),
    ),
}


def get_action(key: str) -> Action:
    try:
        return ACTIONS[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown action {key!r}; known: {sorted(ACTIONS)}"
        ) from exc


def build_session(creds: Credentials) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": creds.ct0,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "content-type": "application/json",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "origin": "https://x.com",
            "referer": "https://x.com/",
            "user-agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }
    )
    s.cookies.set("auth_token", creds.auth_token, domain=".x.com")
    s.cookies.set("ct0", creds.ct0, domain=".x.com")
    return s


def perform_action(
    session: requests.Session,
    action: Action,
    tweet_id: str,
    *,
    query_id: str | None = None,
    timeout: float = 20.0,
) -> dict:
    """Run one GraphQL mutation for one id. Returns the decoded body.

    Raises:
        RateLimited: on HTTP 429.
        ActionError: on any other non-recoverable failure.
    """
    qid = query_id or action.query_id()
    url = f"https://x.com/i/api/graphql/{qid}/{action.name}"
    payload = {"variables": action.build_variables(tweet_id), "queryId": qid}
    resp = session.post(url, json=payload, timeout=timeout)

    if resp.status_code == 429:
        raise RateLimited(resp.headers.get("x-rate-limit-reset", ""))
    if resp.status_code == 404:
        return {"already_gone": True}
    if not resp.ok:
        raise ActionError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise ActionError(f"non-JSON response: {resp.text[:300]}") from exc

    if body.get("errors"):
        msg = "; ".join(e.get("message", "?") for e in body["errors"]).lower()
        if any(marker in msg for marker in action.gone_markers):
            body["already_gone"] = True
            return body
        raise ActionError(msg)
    return body


@dataclass
class ActionStats:
    attempted: int = 0
    succeeded: int = 0
    already_gone: int = 0
    failed: int = 0
    skipped: int = 0


# Backwards-compatible alias (PR #1 referenced DeleteStats).
DeleteStats = ActionStats


def bulk_action(
    tweet_ids: Iterable[str],
    creds: Credentials,
    action: Action,
    *,
    rate: float = 1.0,
    dry_run: bool = False,
    log_path: str | Path = "deleted.jsonl",
    resume: bool = True,
    on_progress: Optional[Callable[[ActionStats, str, str], None]] = None,
    query_id: str | None = None,
    max_retries: int = 5,
) -> ActionStats:
    """Run ``action`` on every id in ``tweet_ids`` with rate limiting.

    The log file is shared across actions but keyed by
    ``{"id": ..., "action": ..., "outcome": ...}`` so the same tweet can
    be, say, unretweeted and later deleted without the second call being
    treated as a resume-skip.
    """
    log_path = Path(log_path)
    already: set[tuple[str, str]] = set()
    if resume and log_path.exists():
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    already.add((str(rec["id"]), rec.get("action", "delete")))
                except (ValueError, KeyError):
                    continue

    session = None if dry_run else build_session(creds)
    stats = ActionStats()
    interval = 1.0 / rate if rate > 0 else 0.0
    qid = query_id or action.query_id()

    with log_path.open("a", encoding="utf-8") as log_fh:
        for tid in tweet_ids:
            tid = str(tid)
            key = (tid, _action_key(action))
            if key in already:
                stats.skipped += 1
                if on_progress:
                    on_progress(stats, tid, "skipped")
                continue

            stats.attempted += 1
            outcome = "dry-run"

            if not dry_run:
                assert session is not None
                outcome = _attempt(session, action, tid, qid, max_retries)
                if outcome == action.past_tense:
                    stats.succeeded += 1
                elif outcome == action.gone_tense:
                    stats.already_gone += 1
                else:
                    stats.failed += 1

            log_fh.write(
                json.dumps(
                    {
                        "id": tid,
                        "action": _action_key(action),
                        "outcome": outcome,
                        "ts": time.time(),
                    }
                )
                + "\n"
            )
            log_fh.flush()

            if on_progress:
                on_progress(stats, tid, outcome)

            if interval and not dry_run:
                time.sleep(interval)

    return stats


def _action_key(action: Action) -> str:
    for key, val in ACTIONS.items():
        if val is action:
            return key
    return action.name


def _attempt(
    session: requests.Session,
    action: Action,
    tid: str,
    qid: str,
    max_retries: int,
) -> str:
    delay = 5.0
    for _ in range(max_retries):
        try:
            body = perform_action(session, action, tid, query_id=qid)
            return action.gone_tense if body.get("already_gone") else action.past_tense
        except RateLimited:
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
        except ActionError:
            return "failed"
    return "failed"
