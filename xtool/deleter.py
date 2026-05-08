"""Backwards-compatible facade over :mod:`xtool.actions`.

Earlier versions of xtool exposed ``delete_tweet``, ``bulk_delete`` and
``DELETE_QUERY_ID`` directly from this module. Everything now lives in
``xtool.actions`` so deletion / unretweet / unlike can share one path.
The symbols below are kept so external scripts and pre-existing imports
continue to work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

import requests

from .actions import (
    ACTIONS,
    ActionError,
    ActionStats,
    Credentials,
    RateLimited,
    build_session,
    bulk_action,
    perform_action,
)
from .discovery import FALLBACK_QUERY_IDS

# Legacy re-exports.
WEB_BEARER = __import__("xtool.actions", fromlist=["WEB_BEARER"]).WEB_BEARER
DeleteError = ActionError
DeleteStats = ActionStats
DELETE_QUERY_ID = FALLBACK_QUERY_IDS["DeleteTweet"]

_DELETE = ACTIONS["delete"]


def _build_session(creds: Credentials, query_id: str) -> requests.Session:
    """Legacy helper; kept for callers that reached into the private API."""
    session = build_session(creds)
    session._query_id = query_id  # type: ignore[attr-defined]
    return session


def delete_tweet(
    session: requests.Session,
    tweet_id: str,
    timeout: float = 20.0,
) -> dict:
    qid = getattr(session, "_query_id", None) or _DELETE.query_id()
    body = perform_action(session, _DELETE, tweet_id, query_id=qid, timeout=timeout)
    # Old callers expect ``already_gone`` to be a top-level flag; keep it.
    return body


def bulk_delete(
    tweet_ids: Iterable[str],
    creds: Credentials,
    *,
    rate: float = 1.0,
    dry_run: bool = False,
    log_path: str | Path = "deleted.jsonl",
    resume: bool = True,
    on_progress: Callable | None = None,
    query_id: str | None = None,
    max_retries: int = 5,
) -> ActionStats:
    """Delete every id in ``tweet_ids``. Thin wrapper around :func:`bulk_action`.

    The returned :class:`ActionStats` still exposes ``.deleted`` via the
    alias below so legacy format strings keep working.
    """
    stats = bulk_action(
        tweet_ids,
        creds,
        _DELETE,
        rate=rate,
        dry_run=dry_run,
        log_path=log_path,
        resume=resume,
        on_progress=on_progress,
        query_id=query_id,
        max_retries=max_retries,
    )
    return stats


# Legacy attribute name: stats.deleted -> stats.succeeded.
def _deleted_getter(self: ActionStats) -> int:  # noqa: D401
    return self.succeeded


def _deleted_setter(self: ActionStats, value: int) -> None:
    self.succeeded = value


ActionStats.deleted = property(_deleted_getter, _deleted_setter)  # type: ignore[attr-defined]


__all__ = [
    "WEB_BEARER",
    "DELETE_QUERY_ID",
    "Credentials",
    "DeleteError",
    "DeleteStats",
    "RateLimited",
    "bulk_delete",
    "delete_tweet",
]
