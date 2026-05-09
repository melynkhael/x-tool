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
    # Optional raw twid cookie value, e.g. "u=1234567890" or the
    # url-encoded "u%3D1234567890". Carried separately from auth_token
    # / ct0 so callers that never needed identity verification still
    # work untouched; callers that do need it can inject the cookie
    # into the session jar via build_session().
    twid: Optional[str] = None

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
        # Normalize twid to None when blank so downstream code can do a
        # simple `if creds.twid:` check without caring about whitespace.
        if self.twid is not None:
            twid = str(self.twid).strip()
            self.twid = twid or None

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
            return cls(
                auth_token=data["auth_token"],
                ct0=data["ct0"],
                # twid is optional: older cookies files don't have it.
                twid=data.get("twid"),
            )
        except KeyError as exc:
            raise ValueError(
                f"{path}: missing required key {exc.args[0]!r} "
                "(expected 'auth_token' and 'ct0')"
            ) from exc

    def to_file(self, path: str | Path) -> bool:
        """Persist credentials. Returns True if file permissions are 0600."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {"auth_token": self.auth_token, "ct0": self.ct0}
        if self.twid:
            payload["twid"] = self.twid
        p.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        try:
            p.chmod(0o600)
        except OSError:
            # Some Termux shared-storage paths don't support chmod.
            return False
        return True


def _delete_retweet_verify(body: dict) -> bool:
    """DeleteRetweet returns HTTP 200 with an EMPTY source_tweet_results
    when the passed id is a wrapper/repost status id instead of the
    actual source tweet id. The X server accepts the request but no
    unretweet actually occurs. Only a response with
    ``data.unretweet.source_tweet_results.result.rest_id`` represents
    a real success.
    """
    try:
        res = body["data"]["unretweet"]["source_tweet_results"]
    except (KeyError, TypeError):
        return False
    if not isinstance(res, dict) or not res:
        return False
    result = res.get("result")
    if not isinstance(result, dict):
        return False
    return bool(result.get("rest_id"))


@dataclass(frozen=True)
class Action:
    """Description of one GraphQL mutation xtool knows how to run."""

    name: str  # GraphQL operation name, e.g. "DeleteTweet"
    build_variables: Callable[[str], dict]
    past_tense: str  # "deleted" / "unretweeted" / "unliked"
    gone_tense: str  # "already_gone" / "not_retweeted" / "not_liked"
    # Substrings that mean "there is nothing to do for this id".
    gone_markers: tuple[str, ...] = ()
    # Optional verifier run on a successful HTTP 200 body. If it
    # returns False we downgrade the outcome to ``gone_tense`` (a
    # no-op, not a real mutation). Used for DeleteRetweet where X
    # returns 200 with an empty source_tweet_results when the id
    # passed is the archive wrapper id instead of the source tweet
    # id.
    verify_success: Optional[Callable[[dict], bool]] = None

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
        # Modern X web client (May 2026) uses DeleteRetweet, not the
        # older UnretweetTweet. UnretweetTweet still exists as a query
        # id in the discovery table for backcompat but is no longer in
        # the live schema and returns HTTP 422 GRAPHQL_VALIDATION_FAILED.
        name="DeleteRetweet",
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
        # X returns HTTP 200 + {"data":{"unretweet":{"source_tweet_results":{}}}}
        # when the id you passed is not a source/original tweet id
        # (e.g. the archive wrapper id). That's a no-op, not a success.
        verify_success=_delete_retweet_verify,
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
    # Set cookies. We previously set them on both .x.com and .twitter.com
    # so cross-host redirects would keep auth, but requests' cookiejar
    # then raises 'multiple cookies with name' when you prepare_request
    # for ANY host that matches both (or during redirect merging). We
    # only set them on .x.com now, plus .twitter.com, using per-host
    # paths that never overlap in a single request. In practice X no
    # longer 302s across hosts for authenticated API calls so this is
    # fine.
    s.cookies.set("auth_token", creds.auth_token, domain=".x.com", path="/")
    s.cookies.set("ct0", creds.ct0, domain=".x.com", path="/")
    # Legacy host -- requests' cookiejar keys (name, domain, path) so
    # this doesn't collide with the .x.com entries above. When we
    # request twitter.com / api.twitter.com these get sent; when we
    # request x.com only the .x.com copies do.
    s.cookies.set("auth_token", creds.auth_token, domain=".twitter.com", path="/")
    s.cookies.set("ct0", creds.ct0, domain=".twitter.com", path="/")
    # Optional twid cookie. When present, xtool.auth.verify_identity can
    # extract the numeric user_id from it and (if a handle is also
    # provided) confirm the two match via GraphQL -- which is the
    # identity path that still works after X deprecated the 1.1 REST
    # endpoints. Stored verbatim; extract_twid_user_id() tolerates
    # "u=1234", "u%3D1234", quoted variants, and raw numeric strings.
    if creds.twid:
        s.cookies.set("twid", creds.twid, domain=".x.com", path="/")
        s.cookies.set("twid", creds.twid, domain=".twitter.com", path="/")
    return s


# Endpoints tried by whoami() in order. The first that returns a JSON
# body with a non-empty screen_name wins.
_WHOAMI_ENDPOINTS: tuple[str, ...] = (
    "https://x.com/i/api/1.1/account/settings.json",
    "https://x.com/i/api/1.1/account/verify_credentials.json"
    "?include_email=false&skip_status=true",
    "https://twitter.com/i/api/1.1/account/settings.json",
    "https://twitter.com/i/api/1.1/account/verify_credentials.json",
    "https://api.twitter.com/1.1/account/settings.json",
    "https://api.twitter.com/1.1/account/verify_credentials.json"
    "?skip_status=true",
)


def whoami(session: requests.Session, timeout: float = 20.0) -> dict:
    """Return the authenticated account's identity.

    Walks a list of known REST endpoints (see ``_WHOAMI_ENDPOINTS``)
    until one returns a JSON body containing ``screen_name``.

    Uses ``requests.get`` directly with a *minimal* header set instead
    of ``session.get``, because the GraphQL session carries
    ``content-type: application/json`` and ``origin: https://x.com`` as
    defaults -- both of which some X edge configs reject on GET
    requests, returning HTTP 404 with error code 34 instead of the
    expected JSON.

    Returns a dict with ``screen_name`` plus (when available) ``user_id``
    and the raw response body. Raises :class:`ActionError` with a
    detailed, actionable message on failure.
    """
    # Pull ct0 from the cookie jar without tripping the 'multiple cookies
    # with name' error requests raises when both .x.com and .twitter.com
    # entries are present. We prefer the .x.com value since we're hitting
    # x.com first.
    ct0 = ""
    for c in session.cookies:
        if c.name == "ct0":
            ct0 = c.value or ""
            if c.domain.endswith("x.com"):
                break
    # Deliberately minimal -- no content-type, no origin.
    headers = {
        "authorization": f"Bearer {WEB_BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://x.com/",
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    errors: list[str] = []
    for url in _WHOAMI_ENDPOINTS:
        short = url.split("?", 1)[0]
        try:
            # Use session.get so the shared cookiejar is sent with the
            # right Host-scoping logic; override headers for this one
            # request to drop content-type / origin which confuse X's
            # REST edge. requests' prepare step merges these with
            # session.headers, so we null out the defaults we don't want.
            req = requests.Request("GET", url, headers=headers)
            prepped = session.prepare_request(req)
            # Strip any content-type inherited from the session.
            prepped.headers.pop("content-type", None)
            prepped.headers.pop("Content-Type", None)
            prepped.headers.pop("origin", None)
            prepped.headers.pop("Origin", None)
            resp = session.send(prepped, timeout=timeout, allow_redirects=False)
        except requests.RequestException as exc:
            errors.append(f"{short}: network error: {type(exc).__name__}: {exc}")
            continue

        # Real auth failures stop the whole cascade.
        if resp.status_code in (401, 403):
            snippet = resp.text[:200].replace("\n", " ").strip()
            raise ActionError(
                f"authentication failed (HTTP {resp.status_code}): "
                "your auth_token or ct0 cookie is invalid or expired. "
                "Log back into x.com in a browser and rerun 'xtool "
                f"login'. Server said: {snippet or '(empty body)'}"
            )

        if not resp.ok:
            snippet = resp.text[:160].replace("\n", " ").strip()
            errors.append(f"{short}: HTTP {resp.status_code}: {snippet or '(empty body)'}")
            continue

        try:
            body = resp.json()
        except ValueError:
            errors.append(f"{short}: non-JSON response")
            continue

        screen_name = body.get("screen_name")
        if screen_name:
            user_id = str(body.get("id_str") or body.get("id") or "") or None
            return {"screen_name": screen_name, "user_id": user_id, "raw": body}

        errors.append(f"{short}: JSON without screen_name: {str(body)[:120]}")

    # All endpoints failed. Extract whatever identity hint we can from
    # the cookies so the error message is useful.
    twid = ""
    for c in session.cookies:
        if c.name == "twid":
            twid = c.value or ""
            break
    user_id_hint = ""
    import re as _re
    m = _re.search(r"u(?:%3D|=)(\d+)", twid)
    if m:
        user_id_hint = f"\n  (twid cookie suggests user_id={m.group(1)} -- your auth seems present)"

    raise ActionError(
        "could not verify your identity with X. Tried "
        f"{len(_WHOAMI_ENDPOINTS)} REST endpoints, all failed:\n  "
        + "\n  ".join(errors)
        + user_id_hint
        + "\n\nLikely causes:\n"
        "  1. Cookies expired -- log back into x.com and rerun 'xtool login'.\n"
        "  2. X deprecated these endpoints -- open an issue at\n"
        "     https://github.com/melynkhael/x-tool/issues\n"
        "  3. Network blocks x.com (VPN, firewall, captive portal).\n"
        "\nEscape hatch: pass --skip-whoami to delete/unretweet/unlike\n"
        "to bypass the identity check (you lose --expect-account safety)."
    )


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
    # Some mutations (DeleteRetweet) return 200 with an empty result
    # object when they're effectively no-ops (e.g. wrong id). If the
    # action has a verifier, let it downgrade the outcome.
    if action.verify_success is not None and not action.verify_success(body):
        body["already_gone"] = True
    # Preserve the raw response for callers that want to inspect it
    # (e.g. to verify the mutation actually took effect).
    body["_raw_response"] = True
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
            detail: str | None = None

            if not dry_run:
                assert session is not None
                outcome, detail = _attempt(session, action, tid, qid, max_retries)
                if outcome == action.past_tense:
                    stats.succeeded += 1
                elif outcome == action.gone_tense:
                    stats.already_gone += 1
                elif outcome == "auth_failed":
                    # Credentials are bad; aborting rather than burning
                    # through the list.
                    stats.failed += 1
                    rec = {
                        "id": tid,
                        "action": _action_key(action),
                        "outcome": outcome,
                        "ts": time.time(),
                    }
                    if detail:
                        rec["error"] = detail
                    log_fh.write(json.dumps(rec) + "\n")
                    log_fh.flush()
                    if on_progress:
                        on_progress(stats, tid, outcome)
                    raise ActionError(
                        "authentication rejected by X; stopped bulk run. "
                        "Refresh your cookies with 'xtool login' and retry."
                    )
                else:
                    stats.failed += 1

            rec = {
                "id": tid,
                "action": _action_key(action),
                "outcome": outcome,
                "ts": time.time(),
            }
            if detail:
                if outcome in (action.past_tense, action.gone_tense, "dry-run"):
                    rec["response"] = detail
                else:
                    rec["error"] = detail
            log_fh.write(json.dumps(rec) + "\n")
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
) -> tuple[str, str | None]:
    """Single-id retry loop.

    Returns ``(outcome, detail)``. ``detail`` is None for success/gone,
    or a short string describing the last failure for bulk_action to
    record in the progress log.

    * Rate limits: sleep until ``x-rate-limit-reset`` (clamped to [5s, 15m])
      if the header is present, otherwise exponential back-off.
    * Auth failures (401/403) bail out immediately to avoid burning the
      whole list with bad cookies.
    * Transient network/5xx errors are retried with a short back-off.
    """
    delay = 5.0
    last_error: str | None = None
    for attempt in range(max_retries):
        try:
            body = perform_action(session, action, tid, query_id=qid)
            outcome = action.gone_tense if body.get("already_gone") else action.past_tense
            # Include a truncated response body in 'detail' for successful
            # calls too, so users can verify the mutation actually worked.
            resp_summary = None
            if body.get("_raw_response"):
                # Strip the internal marker and produce a compact summary.
                body.pop("_raw_response", None)
                resp_summary = json.dumps(body, ensure_ascii=False)[:500]
            return outcome, resp_summary
        except RateLimited as rl:
            last_error = f"rate limited (reset={rl.reset_epoch:.0f})"
            if rl.reset_epoch:
                wait = max(5.0, min(rl.reset_epoch - time.time() + 1.0, 900.0))
            else:
                wait = delay
                delay = min(delay * 2, 120.0)
            time.sleep(wait)
        except ActionError as exc:
            msg = str(exc)
            last_error = msg[:500]
            # Auth failures: stop trying so we don't hammer with bad
            # cookies. Surface via 'failed' outcome; CLI will abort.
            if "authentication rejected" in msg:
                return "auth_failed", last_error
            # Transient network/5xx: retry with a small back-off.
            if "network error" in msg or "HTTP 5" in msg:
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            return "failed", last_error
    return "failed", last_error or "exhausted retries"
