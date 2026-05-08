"""Tweet deletion via X's internal GraphQL endpoint.

We reuse the session cookies (`auth_token`, `ct0`) from a logged-in
browser, exactly like the X web client does. No paid API tier required.

Endpoint::

    POST https://x.com/i/api/graphql/VaenaVgh5q5ih7kvyVjgtg/DeleteTweet

Required headers:

* ``authorization``  - the web client's public Bearer token (it's
  hard-coded in x.com's JS bundle and changes rarely).
* ``x-csrf-token``   - the value of the ``ct0`` cookie.
* ``cookie``         - at minimum ``auth_token`` + ``ct0``.

Body (JSON)::

    {
      "variables": {"tweet_id": "<id>", "dark_request": false},
      "queryId":   "VaenaVgh5q5ih7kvyVjgtg"
    }

If the tweet is already gone we treat the call as a success so that
reruns are idempotent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import requests

# Public Bearer token shipped in x.com's JavaScript bundle. This is the
# same token used by every logged-in web session and is not a secret.
WEB_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL query id for DeleteTweet on the web client. Occasionally
# rotated by X; override with the XTOOL_DELETE_QUERY_ID env var if needed.
DELETE_QUERY_ID = "VaenaVgh5q5ih7kvyVjgtg"


class DeleteError(Exception):
    """Non-retryable deletion failure."""


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


def _build_session(creds: Credentials, query_id: str) -> requests.Session:
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
    s._query_id = query_id  # type: ignore[attr-defined]
    return s


def delete_tweet(session: requests.Session, tweet_id: str, timeout: float = 20.0) -> dict:
    """Delete a single tweet. Returns the decoded JSON response.

    Raises:
        RateLimited: on HTTP 429.
        DeleteError: on any other non-2xx response with an error body.
    """
    query_id: str = getattr(session, "_query_id", DELETE_QUERY_ID)
    url = f"https://x.com/i/api/graphql/{query_id}/DeleteTweet"
    payload = {
        "variables": {"tweet_id": str(tweet_id), "dark_request": False},
        "queryId": query_id,
    }
    resp = session.post(url, json=payload, timeout=timeout)
    if resp.status_code == 429:
        raise RateLimited(resp.headers.get("x-rate-limit-reset", ""))
    if resp.status_code == 404:
        # Already gone - treat as success.
        return {"data": {"delete_tweet": {"tweet_results": {}}}, "already_gone": True}
    if not resp.ok:
        raise DeleteError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise DeleteError(f"non-JSON response: {resp.text[:300]}") from exc
    if "errors" in body and body["errors"]:
        # X returns 200 + errors array for things like "tweet not found".
        msg = "; ".join(e.get("message", "?") for e in body["errors"])
        if "not found" in msg.lower() or "no status found" in msg.lower():
            body["already_gone"] = True
            return body
        raise DeleteError(msg)
    return body


@dataclass
class DeleteStats:
    attempted: int = 0
    deleted: int = 0
    already_gone: int = 0
    failed: int = 0
    skipped: int = 0


def bulk_delete(
    tweet_ids: Iterable[str],
    creds: Credentials,
    *,
    rate: float = 1.0,
    dry_run: bool = False,
    log_path: str | Path = "deleted.jsonl",
    resume: bool = True,
    on_progress=None,
    query_id: str = DELETE_QUERY_ID,
    max_retries: int = 5,
) -> DeleteStats:
    """Delete every id in `tweet_ids`.

    Args:
        rate: requests per second (0 = as fast as possible).
        dry_run: don't actually hit the network.
        log_path: append one JSON line per processed id, enabling resume.
        resume: if True, skip ids already present in the log.
        on_progress: optional callback ``f(stats, id, outcome)`` for UI.
    """
    log_path = Path(log_path)
    already: set[str] = set()
    if resume and log_path.exists():
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    already.add(str(json.loads(line)["id"]))
                except (ValueError, KeyError):
                    continue

    session = None if dry_run else _build_session(creds, query_id)
    stats = DeleteStats()
    interval = 1.0 / rate if rate > 0 else 0.0

    with log_path.open("a", encoding="utf-8") as log_fh:
        for tid in tweet_ids:
            tid = str(tid)
            if tid in already:
                stats.skipped += 1
                if on_progress:
                    on_progress(stats, tid, "skipped")
                continue

            stats.attempted += 1
            outcome = "dry-run"

            if dry_run:
                pass
            else:
                assert session is not None
                outcome = _attempt(session, tid, max_retries)
                if outcome == "deleted":
                    stats.deleted += 1
                elif outcome == "already_gone":
                    stats.already_gone += 1
                else:
                    stats.failed += 1

            log_fh.write(
                json.dumps({"id": tid, "outcome": outcome, "ts": time.time()})
                + "\n"
            )
            log_fh.flush()

            if on_progress:
                on_progress(stats, tid, outcome)

            if interval and not dry_run:
                time.sleep(interval)

    return stats


def _attempt(session: requests.Session, tid: str, max_retries: int) -> str:
    """Single-id attempt loop with exponential back-off on 429."""
    delay = 5.0
    for attempt in range(max_retries):
        try:
            body = delete_tweet(session, tid)
            return "already_gone" if body.get("already_gone") else "deleted"
        except RateLimited:
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
        except DeleteError:
            return "failed"
    return "failed"
