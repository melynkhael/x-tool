"""Redaction helpers for logs, error messages, and debug dumps.

xtool writes a lot of JSONL under ``~/.xtool/logs/`` and in the
current working directory (``deleted.jsonl``, ``unretweeted.jsonl``,
``live-retweets.jsonl.debug.jsonl``, etc). Those files can end up
attached to bug reports, shared in screenshots, or sync'd to cloud
backups. Anything we persist to them must therefore be scrubbed of:

* ``auth_token``        (full account credential).
* ``ct0``               (CSRF credential; useless without auth_token
                         but still identifies a session).
* ``twid``              (user_id carrier).
* ``Cookie`` / ``authorization`` HTTP headers.
* ``Bearer <token>`` strings from the web bundle (not technically a
  per-user secret, but we redact them anyway so log consumers can't
  tell whether the tool was authenticated when a call failed).
* Raw numeric user IDs in contexts that are not the user's own
  ``--show-user-id`` request. These are X ``rest_id``/``user_id``
  values -- permanent account identifiers that map to a handle for
  anyone with basic API access. We treat any 15+ digit run as
  user-id-shaped.

The functions in this module operate on strings and dicts and NEVER
raise for unexpected shapes: a redactor that fails closed would take
the log file with it, and we would rather emit over-redacted junk
than nothing at all.

Contract
--------
* :func:`redact_text` returns a new string with replacements applied.
  The original is never mutated (strings are immutable anyway; this
  is the contract-level guarantee).
* :func:`redact_record` returns a new ``dict``. It walks nested
  dicts/lists recursively so JSON bodies are scrubbed end-to-end.
* Values are replaced with short placeholder tokens (``"<redacted:
  auth_token>"``, ``"<redacted:user_id>"``) so the shape of the log
  entry stays debuggable and the reviewer can tell *what* was
  redacted, just not *what it was*.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Placeholder tokens
# ---------------------------------------------------------------------------

_P_AUTH_TOKEN = "<redacted:auth_token>"
_P_CT0 = "<redacted:ct0>"
_P_TWID = "<redacted:twid>"
_P_COOKIE = "<redacted:cookie>"
_P_BEARER = "<redacted:bearer>"
_P_USER_ID = "<redacted:user_id>"
_P_GENERIC = "<redacted>"


# ---------------------------------------------------------------------------
# Sensitive keys: replaced whole-value when found as a JSON/dict key
# ---------------------------------------------------------------------------

# Keys whose values are full credentials. We match case-insensitively
# because HTTP header dicts routinely come in mixed casing ("Cookie",
# "Authorization", "Set-Cookie").
_CREDENTIAL_KEYS: dict[str, str] = {
    "auth_token": _P_AUTH_TOKEN,
    "ct0": _P_CT0,
    "twid": _P_TWID,
    "cookie": _P_COOKIE,
    "set-cookie": _P_COOKIE,
    "authorization": _P_BEARER,
    "x-csrf-token": _P_CT0,
}


# Keys whose values are numeric user IDs we do NOT want to persist to
# logs. These are ONLY redacted in log-record walks, never at the
# string level -- the UI layer is the sole gatekeeper for displaying
# user_id in the menu / whoami output.
_USER_ID_KEYS: frozenset[str] = frozenset(
    {
        "user_id",
        "userid",
        "rest_id",
        "id_str",  # risky: also used for tweet ids. We DON'T redact
        #          tweet ids -- they're the whole point of the log.
        #          Kept out of the set; left here as a reminder.
    }
    - {"id_str"}
)


# ---------------------------------------------------------------------------
# String-level patterns
# ---------------------------------------------------------------------------

# "auth_token=abc123" / "auth_token: abc123" / "auth_token":"abc123"
_RE_KV = re.compile(
    r'(?P<key>auth_token|ct0|twid)\s*(?P<sep>[=:])\s*'
    r'(?P<quote>"?)(?P<val>[^\s;,"}]+)(?P=quote)',
    re.IGNORECASE,
)

# "Cookie: foo=bar; auth_token=..." -- redact the whole header value.
_RE_COOKIE_HEADER = re.compile(
    r'(?P<key>cookie|set-cookie)\s*:\s*(?P<val>[^\r\n]+)',
    re.IGNORECASE,
)

# "Authorization: Bearer <token>" or "authorization":"Bearer ..."
_RE_BEARER = re.compile(
    r'Bearer\s+[A-Za-z0-9._\-%=+/]{10,}',
    re.IGNORECASE,
)

# Raw twid cookie shapes when they appear in free text without the
# "twid=" prefix (e.g. server error messages echo the cookie value).
_RE_TWID_VALUE = re.compile(r'u(?:%3D|=)\d{5,}')

# Numeric user IDs. X user IDs are 18-19 digits for post-2022 accounts
# and 9-10 digits for older ones. We use a 15+ threshold to avoid
# false positives on tweet ids (also 19 digits) and status codes --
# but tweet ids are indistinguishable from user ids by length alone,
# which is why we only redact these inside dict keys known to carry
# user ids, never in free text. This regex exists for explicit use
# by :func:`redact_user_ids_in_text` when callers opt in.
_RE_LONG_NUMBER = re.compile(r'\b\d{15,}\b')


def redact_text(s: str) -> str:
    """Return ``s`` with credential substrings replaced.

    Redacts (in order):

    1. ``auth_token=...`` / ``ct0=...`` / ``twid=...`` key-value pairs.
    2. ``Cookie: ...`` and ``Set-Cookie: ...`` header lines (whole
       value replaced).
    3. ``Bearer <token>`` authorization strings.
    4. Raw ``u=<digits>`` twid values in free text.

    Does NOT redact standalone long numbers; call
    :func:`redact_user_ids_in_text` for that.

    Binary / non-string inputs are coerced to ``str`` so a stray
    ``bytes`` object doesn't crash the redactor.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)

    def _kv_sub(m: re.Match[str]) -> str:
        key = m.group("key").lower()
        token = {
            "auth_token": _P_AUTH_TOKEN,
            "ct0": _P_CT0,
            "twid": _P_TWID,
        }.get(key, _P_GENERIC)
        quote = m.group("quote") or ""
        return f"{m.group('key')}{m.group('sep')}{quote}{token}{quote}"

    s = _RE_KV.sub(_kv_sub, s)

    def _header_sub(m: re.Match[str]) -> str:
        return f"{m.group('key')}: {_P_COOKIE}"

    s = _RE_COOKIE_HEADER.sub(_header_sub, s)
    s = _RE_BEARER.sub(_P_BEARER, s)
    s = _RE_TWID_VALUE.sub(_P_TWID, s)
    return s


def redact_user_ids_in_text(s: str) -> str:
    """Redact runs of 15+ digits from ``s``.

    Called only by paths that explicitly do not want to leak user ids
    (e.g. the ``whoami`` error-hint path, where the upstream error
    message used to interpolate the raw twid user_id). Tweet/retweet
    logs must NOT call this because it would destroy the tweet ids
    that are the whole point of the log.
    """
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return _RE_LONG_NUMBER.sub(_P_USER_ID, s)


def _redact_value_for_key(key: str, value: Any) -> Any:
    """Dispatch helper: redacts ``value`` based on ``key``."""
    kl = key.lower()
    if kl in _CREDENTIAL_KEYS:
        if value in (None, ""):
            return value
        return _CREDENTIAL_KEYS[kl]
    if kl in _USER_ID_KEYS:
        if value in (None, ""):
            return value
        return _P_USER_ID
    return redact_record(value)


def redact_record(obj: Any) -> Any:
    """Recursively walk ``obj`` (dict/list/str/…) redacting credentials.

    * Dicts are recreated with the same key order; values whose key
      matches a credential or user-id field are replaced.
    * Lists are mapped element-wise.
    * Strings are passed through :func:`redact_text`.
    * Other scalar types (int, float, bool, None) are returned
      unchanged -- they cannot carry a credential without also being
      represented as a string in the transport layer.

    The original ``obj`` is never mutated. Callers can use the result
    directly as the replacement log record.
    """
    if isinstance(obj, dict):
        return {k: _redact_value_for_key(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_record(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_record(v) for v in obj)
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


# ---------------------------------------------------------------------------
# Heuristic leak detection (used by `xtool doctor`)
# ---------------------------------------------------------------------------

# Doctor uses these to flag *likely* leaks in local files without
# ever printing the matched value. The patterns are intentionally
# conservative: false positives are fine (doctor surfaces "inspect
# this file"), false negatives are not.

_LEAK_SIGNALS = (
    re.compile(r"\bauth_token\b", re.IGNORECASE),
    re.compile(r'"auth_token"\s*:', re.IGNORECASE),
    re.compile(r'\bct0\s*[=:]', re.IGNORECASE),
    _RE_COOKIE_HEADER,
    _RE_BEARER,
    _RE_TWID_VALUE,
)


def looks_like_leak(sample: str) -> bool:
    """Return True when ``sample`` looks like it contains a credential.

    Used by :mod:`xtool.doctor` to flag files a user should review.
    We never print the match, only the filename and a count. Callers
    are expected to feed in a bounded read (e.g. the first N KB of a
    file) so this remains O(sample size) on large logs.
    """
    if not sample:
        return False
    for pat in _LEAK_SIGNALS:
        if pat.search(sample):
            return True
    return False


def sensitive_basenames() -> Iterable[str]:
    """Filenames doctor treats as sensitive-by-name when found inside
    a git checkout. The check is basename-only so nested paths like
    ``subdir/cookies.json`` still match.
    """
    return (
        "cookies.json",
        "identity.json",
        "query_ids.json",
    )
