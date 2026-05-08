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
import warnings
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
    """HTTP 429 - caller should back off.

    ``reset_epoch`` is the unix timestamp (seconds) reported by the
    ``x-rate-limit-reset`` header when present, else 0.
    """

    def __init__(self, reset_epoch: float = 0.0):
        super().__init__(f"rate limited; reset_epoch={reset_epoch}")
        self.reset_epoch = reset_epoch


@dataclass
class Credentials:
    auth_token: str
    ct0: str

    def __post_init__(self) -> None:
        # Validate shape early so bulk runs don't fail mid-flight.
        if not self.auth_token or not isinstance(self.auth_token, str):
            raise ValueError("auth_token is missing or not a string")
        if not self.ct0 or not isinstance(self.ct0, str):
            raise ValueError("ct0 is missing or not a string")
        # auth_token is a 40-char hex string in real sessions; ct0 is
        # typically 32-160 chars. We don't hard-enforce format to avoid
        # breaking when X changes encoding, but we do warn on suspicious
        # lengths so obvious mistakes (pasting a trimmed value) surface.
        if len(self.auth_token) < 20 or len(self.ct0) < 20:
            warnings.warn(
                "credential values look suspiciously short; double-check "
                "you copied the full cookie values",
                stacklevel=2,
            )

    @classmethod
    def from_file(cls, path: str | Path) -> "Credentials":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"cannot read credentials from {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"{path}: expected a JSON object with auth_token and ct0"
            )
        try:
            return cls(auth_token=data["auth_token"], ct0=data["ct0"])
        except KeyError as exc:
            raise ValueError(
                f"{path}: missing required key {exc.args[0]!r} "
                "(expected 'auth_token' and 'ct0')"
            ) from exc

    def to_file(self, path: str | Path) -> bool:
        """Persist credentials. Returns True if file permissions are 0600."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"auth_token": self.auth_token, "ct0": self.ct0}, indent=2),
            encoding="utf-8",
        )
        try:
            p.chmod(0o600)
        except OSError:
            # Some Termux shared-storage paths don't support chmod.
            return False
        return True


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
    # Set cookies for both x.com and twitter.com so redirects between
    # the two don't drop our auth.
    for domain in (".x.com", ".twitter.com"):
        s.cookies.set("auth_token", creds.auth_token, domain=domain)
        s.cookies.set("ct0", creds.ct0, domain=domain)
    return s


def whoami(session: requests.Session, timeout: float = 20.0) -> dict:
    """Return the authenticated account's identity.

    The X web client uses the legacy REST endpoint
    ``https://x.com/i/api/1.1/account/settings.json`` to resolve the
    logged-in user's screen_name (same ``/i/api/`` path used for every
    GraphQL mutation, just under the 1.1 tree). We hit that rather
    than a GraphQL query because REST doesn't need a rotating queryId
    or a ``features`` blob.

    Note: the host is ``x.com``, NOT ``api.x.com`` -- the latter only
    serves the GraphQL layer and returns HTTP 404 / code 34 for REST
    paths.

    Returns a dict with at minimum ``screen_name``. Raises
    :class:`ActionError` on HTTP errors so callers can show a clear
    "your cookies don't work" message.
    """
    # Primary path used by the current web client.
    endpoints = (
        "https://x.com/i/api/1.1/account/settings.json",
        # Fallback: legacy host still answers for authenticated sessions.
        "https://api.twitter.com/1.1/account/settings.json",
    )
    last_error: ActionError | None = None
    for url in endpoints:
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = ActionError(f"whoami: network error: {exc}")
            continue
        if resp.status_code in (401, 403):
            raise ActionError(
                "authentication failed (HTTP {}): your auth_token or ct0 "
                "cookie is invalid or expired. Log back into x.com in a "
                "browser and rerun 'xtool login'.".format(resp.status_code)
            )
        if resp.status_code == 404:
            # Endpoint moved - try the next candidate.
            last_error = ActionError(f"whoami HTTP 404 at {url}")
            continue
        if not resp.ok:
            last_error = ActionError(
                f"whoami HTTP {resp.status_code}: {resp.text[:200]}"
            )
            continue
        try:
            body = resp.json()
        except ValueError as exc:
            last_error = ActionError(
                f"whoami non-JSON response: {resp.text[:200]}"
            )
            continue
        screen_name = body.get("screen_name")
        if not screen_name:
            last_error = ActionError(
                "whoami response had no screen_name; the endpoint shape "
                "may have changed"
            )
            continue
        return {"screen_name": screen_name, "raw": body}
    assert last_error is not None
    raise last_error


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
        ActionError: on any other non-recoverable failure (including
            network errors - callers are expected to catch and retry
            those at their own cadence).
    """
    qid = query_id or action.query_id()
    url = f"https://x.com/i/api/graphql/{qid}/{action.name}"
    payload = {"variables": action.build_variables(tweet_id), "queryId": qid}
    try:
        resp = session.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise ActionError(f"network error: {exc}") from exc

    if resp.status_code == 429:
        try:
            reset = float(resp.headers.get("x-rate-limit-reset", "0") or 0)
        except (TypeError, ValueError):
            reset = 0.0
        raise RateLimited(reset_epoch=reset)
    if resp.status_code == 404:
        return {"already_gone": True}
    if resp.status_code in (401, 403):
        raise ActionError(
            f"HTTP {resp.status_code}: authentication rejected. "
            "Your auth_token/ct0 cookies are invalid or expired."
        )
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

    # Track in-memory to dedup within a single run (not just across runs).
    seen_this_run: set[str] = set()

    with log_path.open("a", encoding="utf-8") as log_fh:
        for tid in tweet_ids:
            tid = str(tid)
            if tid in seen_this_run:
                # Duplicate id inside the input file; processed once already.
                continue
            seen_this_run.add(tid)

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
                elif outcome == "auth_failed":
                    # Credentials are bad; aborting rather than burning
                    # through the list.
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
                    raise ActionError(
                        "authentication rejected by X; stopped bulk run. "
                        "Refresh your cookies with 'xtool login' and retry."
                    )
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
    """Single-id retry loop.

    * Rate limits: sleep until ``x-rate-limit-reset`` (clamped to [5s, 15m])
      if the header is present, otherwise exponential back-off.
    * Auth failures (401/403) bail out immediately to avoid burning the
      whole list with bad cookies.
    * Transient network/5xx errors are retried with a short back-off.
    """
    delay = 5.0
    for attempt in range(max_retries):
        try:
            body = perform_action(session, action, tid, query_id=qid)
            return action.gone_tense if body.get("already_gone") else action.past_tense
        except RateLimited as rl:
            if rl.reset_epoch:
                wait = max(5.0, min(rl.reset_epoch - time.time() + 1.0, 900.0))
            else:
                wait = delay
                delay = min(delay * 2, 120.0)
            time.sleep(wait)
        except ActionError as exc:
            msg = str(exc)
            # Auth failures: stop trying so we don't hammer with bad
            # cookies. Surface via 'failed' outcome; CLI will abort.
            if "authentication rejected" in msg:
                return "auth_failed"
            # Transient network/5xx: retry with a small back-off.
            if "network error" in msg or "HTTP 5" in msg:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            return "failed"
    return "failed"
