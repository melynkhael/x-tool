"""Auto-discovery of GraphQL query IDs from x.com's JS bundle.

Every X mutation used by the web client is referenced in the bundle with
a line that looks roughly like::

    {queryId:"VaenaVgh5q5ih7kvyVjgtg",operationName:"DeleteTweet",
     operationType:"mutation",metadata:{...}}

The pair ``(queryId, operationName)`` can appear in either order, so we
match both. Results are cached in ``~/.xtool/query_ids.json`` with a
configurable TTL so the network hit is at most once a week.

If the fetch fails we fall back to the built-in ``FALLBACK_QUERY_IDS``
table, which is accurate as of early 2025 but may drift. Users can
force a refresh with ``xtool discover --refresh``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Iterable

import requests


CACHE_PATH = Path(os.path.expanduser("~/.xtool/query_ids.json"))
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 1 week

# Last known-good IDs. Updated periodically. These are the source of
# truth when discovery fails or is disabled. Refreshed 2026-05 from
# x.com's live JS bundle.
FALLBACK_QUERY_IDS: dict[str, str] = {
    "DeleteTweet": "nxpZCY2K-I6QoFHAHeojFQ",
    "UnretweetTweet": "iQtK4dl5hBmXewYZuEOKVw",
    "DeleteRetweet": "ZyZigVsNiFO6v1dEks1eWg",
    "UnfavoriteTweet": "ZYKSe-w7KEslx3JhSIk5LA",
    "FavoriteTweet": "lI07N6Otwv1PhnEgXILM7A",
    "CreateTweet": "FtGeaqS11k1UG-kGv_YUVg",
    "CreateRetweet": "mbRO74GrOvSfRcJnlMapnQ",
}

# Operation names xtool actually uses. Only these must be resolvable.
REQUIRED_OPERATIONS: tuple[str, ...] = (
    "DeleteTweet",
    "DeleteRetweet",
    "UnfavoriteTweet",
)

# Match `queryId:"ABC",...operationName:"Foo"` and the reverse order.
# Within a small window to avoid mis-pairing two unrelated mutations.
_QID_FIRST = re.compile(
    r'queryId:"([A-Za-z0-9_-]{10,})"[^}]{0,300}?operationName:"([A-Za-z0-9_]+)"'
)
_OP_FIRST = re.compile(
    r'operationName:"([A-Za-z0-9_]+)"[^}]{0,300}?queryId:"([A-Za-z0-9_-]{10,})"'
)

# URL patterns for the main bundle. Twitter historically served it from
# abs.twimg.com; newer builds embed several chunks. We scan all of them.
_SCRIPT_SRC = re.compile(
    r'(https://abs\.twimg\.com/responsive-web/client-web(?:-[a-z]+)?/'
    r'[A-Za-z0-9_./-]+\.[0-9a-f]+[a-z]*\.js)'
)


def extract_query_ids(js_source: str) -> dict[str, str]:
    """Return {operation_name: query_id} found inside a JS blob."""
    out: dict[str, str] = {}
    for qid, op in _QID_FIRST.findall(js_source):
        out.setdefault(op, qid)
    for op, qid in _OP_FIRST.findall(js_source):
        out.setdefault(op, qid)
    return out


def _fetch(url: str, session: requests.Session, timeout: float = 20.0) -> str:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _discover_uncached(
    session: requests.Session | None = None,
    required: Iterable[str] = REQUIRED_OPERATIONS,
) -> dict[str, str]:
    """Fetch x.com, follow the main JS chunks, and aggregate query IDs."""
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "user-agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "accept-language": "en-US,en;q=0.9",
            }
        )

    # 1. Grab the x.com HTML and collect every JS chunk referenced.
    html = _fetch("https://x.com/", session)
    script_urls = list(dict.fromkeys(_SCRIPT_SRC.findall(html)))
    if not script_urls:
        # Some builds inline a manifest in a <link rel="preload">; just
        # try a couple of well-known chunk names as a fallback.
        script_urls = [
            "https://abs.twimg.com/responsive-web/client-web/main.bundle.js",
        ]

    # 2. Walk chunks until every required op is resolved.
    discovered: dict[str, str] = {}
    required_set = set(required)
    for url in script_urls:
        try:
            js = _fetch(url, session)
        except requests.RequestException:
            continue
        found = extract_query_ids(js)
        for op, qid in found.items():
            discovered.setdefault(op, qid)
        if required_set.issubset(discovered):
            break

    return discovered


def _load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_cache(payload: dict) -> None:
    """Persist the query-id cache with mode 0600 under a 0700 parent.

    The cache itself is not a credential -- these are public query ids
    from x.com's JS bundle -- but ``~/.xtool/query_ids.json`` lives
    next to ``cookies.json`` and we apply the same directory chmod to
    the whole tree. Using :func:`xtool._safe_io.safe_write_json` keeps
    every file under ``~/.xtool`` on the same "atomic, private, no
    symlink follow" path.
    """
    from ._safe_io import safe_write_json
    safe_write_json(CACHE_PATH, payload)


def discover_query_ids(
    *,
    refresh: bool = False,
    offline: bool = False,
    ttl: int = CACHE_TTL_SECONDS,
) -> dict[str, str]:
    """Return the effective ``{op_name: query_id}`` map.

    Order of precedence:
      1. Fresh cache (age <= ttl), unless ``refresh=True``.
      2. Live fetch from x.com, unless ``offline=True``.
      3. ``FALLBACK_QUERY_IDS``.

    The result is always a superset of ``FALLBACK_QUERY_IDS`` so callers
    can depend on every known op being present.
    """
    return {
        op: qid
        for op, (qid, _src) in _merged(
            refresh=refresh, offline=offline, ttl=ttl
        ).items()
    }


def discover_with_sources(
    *,
    refresh: bool = False,
    offline: bool = False,
    ttl: int = CACHE_TTL_SECONDS,
) -> dict[str, tuple[str, str]]:
    """Like :func:`discover_query_ids` but also tags each entry with its
    source: ``"live"``, ``"cache"`` or ``"fallback"``.

    The network is hit at most once per call, even when multiple callers
    invoke this function, because we write through to the on-disk cache.
    """
    return _merged(refresh=refresh, offline=offline, ttl=ttl)


def _merged(*, refresh: bool, offline: bool, ttl: int) -> dict[str, tuple[str, str]]:
    cache = _load_cache()
    now = time.time()
    fresh = (
        cache is not None
        and isinstance(cache.get("fetched_at"), (int, float))
        and (now - cache["fetched_at"]) < ttl
        and isinstance(cache.get("ids"), dict)
    )

    sources: dict[str, tuple[str, str]] = {
        op: (qid, "fallback") for op, qid in FALLBACK_QUERY_IDS.items()
    }

    if fresh and not refresh:
        for op, qid in cache["ids"].items():  # type: ignore[union-attr]
            sources[op] = (qid, "cache")
        return sources

    if offline:
        if cache and isinstance(cache.get("ids"), dict):
            for op, qid in cache["ids"].items():
                sources[op] = (qid, "cache")
        return sources

    try:
        discovered = _discover_uncached()
    except Exception:  # network, parse, DNS, TLS, anything
        discovered = {}

    if discovered:
        try:
            _save_cache({"fetched_at": now, "ids": discovered})
        except OSError:
            pass  # read-only filesystem (some Termux storage paths)
        for op, qid in discovered.items():
            sources[op] = (qid, "live")

    return sources


def get_query_id(operation: str, *, offline: bool = False) -> str:
    """Convenience: resolve a single operation name to its query id.

    Honors the ``XTOOL_<OPERATION>_QUERY_ID`` env var as the highest
    priority override (so users can pin a value without touching code).
    """
    env_key = f"XTOOL_{_camel_to_snake(operation).upper()}_QUERY_ID"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val
    ids = discover_query_ids(offline=offline)
    return ids.get(operation) or FALLBACK_QUERY_IDS[operation]


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
