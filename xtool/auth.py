"""Account identity verification for xtool.

X has been quietly deprecating the 1.1 REST endpoints the web client
used to call on page load (``/account/settings.json``,
``/account/verify_credentials.json``). When those routes 404, xtool's
older whoami logic looked like cookies were bad even though they were
fine for every GraphQL mutation we actually run. This module fixes that
by trying multiple signals in order and returning a structured result
so the UI can show a real status instead of a stack trace.

Verification order
------------------
1. **REST whoami** (:func:`xtool.actions.whoami`) - the legacy path.
   When x.com is healthy this is the only call we need and we come out
   with a confirmed ``screen_name`` + ``user_id``.

2. **twid cookie** - once you're logged in, x.com sets a ``twid`` cookie
   that encodes your numeric user_id (``u%3D<id>`` or ``u=<id>``). If it's
   present, we have strong evidence the cookies are real, just not a
   handle. We report a ``partial`` status -- enough to show the user_id
   and proceed with caution -- instead of claiming the cookies are bad.

3. **handle-match via GraphQL** - if the caller knows (or asked for) the
   expected handle, we resolve it via ``UserByScreenName``. If that
   ``rest_id`` matches the twid user_id, we upgrade the status back to
   ``verified`` -- cookies are valid *and* they belong to the handle the
   user claimed. This works even when the REST endpoints are all 404.

Returned shape
--------------
Every entry point returns an :class:`Identity` dataclass:

* ``status`` - "verified" | "partial" | "none"
* ``handle``, ``user_id`` - whatever we managed to resolve
* ``source``  - short tag describing *how* we got the handle
  ("rest", "handle-match", "cookie", "none")
* ``detail``  - diagnostic string the UI can show in the Troubleshooting
  menu if the user wants to know why verification fell back
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

from .actions import ActionError, Credentials, build_session, whoami


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

# ``twid`` cookie encodes the numeric user id as "u%3D<id>" (url-encoded)
# or "u=<id>" depending on where in the pipeline we pulled it from.
_TWID_USER_ID = re.compile(r"u(?:%3D|=)(\d+)")


@dataclass
class Identity:
    """Structured result of an identity check.

    Attributes:
        status:   one of ``verified``, ``partial``, ``none``.
        handle:   the account's @screen_name (without ``@``), if known.
        user_id:  numeric user id as a string, if known.
        source:   short tag describing how we resolved ``handle`` --
                  ``rest``, ``handle-match``, ``cookie``, or ``none``.
        detail:   human-readable diagnostic. Safe to show in UI.
    """

    status: str  # "verified" | "partial" | "none"
    handle: Optional[str] = None
    user_id: Optional[str] = None
    source: str = "none"
    detail: str = ""

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def has_cookies(self) -> bool:
        return self.status in ("verified", "partial")

    # Convenience for the menu header -- single line, no styling.
    def one_liner(self) -> str:
        if self.status == "verified" and self.handle:
            return f"@{self.handle} verified"
        if self.status == "partial":
            if self.handle:
                return f"@{self.handle} (not verified)"
            if self.user_id:
                return f"user_id {self.user_id} (identity not verified)"
            return "cookies saved, identity not verified"
        return "not logged in"


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def extract_twid_user_id(session: requests.Session) -> Optional[str]:
    """Pull the numeric user id out of the ``twid`` cookie, if present.

    Returns None if the cookie is missing or malformed. Never raises.
    """
    twid = ""
    for c in session.cookies:
        if c.name == "twid":
            twid = c.value or ""
            break
    if not twid:
        return None
    m = _TWID_USER_ID.search(twid)
    return m.group(1) if m else None


def _try_rest(session: requests.Session) -> tuple[Optional[dict], Optional[str]]:
    """Run REST whoami. Returns (result, error_detail)."""
    try:
        return whoami(session), None
    except ActionError as exc:
        return None, str(exc).split("\n", 1)[0]  # first line only


def _try_handle_match(
    session: requests.Session, handle: str, twid_user_id: Optional[str]
) -> Optional[tuple[str, str]]:
    """Resolve ``handle`` via GraphQL and confirm it matches twid.

    Returns ``(user_id, "handle-match")`` only when the resolved rest_id
    equals the numeric user_id encoded in the twid cookie. Anything
    less conclusive returns None -- we do NOT blindly trust a handle the
    user typed; that would defeat the whole safety check.
    """
    if not handle or not twid_user_id:
        return None
    # Import lazily so auth.py doesn't pull in the resolver module unless
    # a handle-match is actually attempted. Keeps `xtool whoami` fast.
    try:
        from .resolver import ResolverError, resolve_screen_name
    except ImportError:
        return None
    try:
        resolved = resolve_screen_name(session, handle)
    except (ResolverError, ActionError):
        return None
    if str(resolved) == str(twid_user_id):
        return str(resolved), "handle-match"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_identity(
    creds: Credentials,
    *,
    expect_handle: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> Identity:
    """Best-effort identity check.

    Args:
        creds: loaded :class:`~xtool.actions.Credentials`.
        expect_handle: when the caller knows (or the user claims) the
            account handle, we can upgrade a ``partial`` result to
            ``verified`` by confirming the handle resolves to the same
            user_id we see in the twid cookie.
        session: reuse an existing session if the caller already built
            one. A fresh session is created otherwise.

    Returns:
        An :class:`Identity`. Never raises -- callers get a structured
        ``status="none"`` on total failure instead of an exception.
    """
    sess = session or build_session(creds)

    rest_result, rest_error = _try_rest(sess)
    if rest_result:
        return Identity(
            status="verified",
            handle=rest_result.get("screen_name"),
            user_id=rest_result.get("user_id"),
            source="rest",
            detail="identity confirmed via X REST endpoint",
        )

    twid_user_id = extract_twid_user_id(sess)

    if expect_handle and twid_user_id:
        match = _try_handle_match(sess, expect_handle.lstrip("@"), twid_user_id)
        if match:
            resolved_id, src = match
            return Identity(
                status="verified",
                handle=expect_handle.lstrip("@"),
                user_id=resolved_id,
                source=src,
                detail=(
                    "identity confirmed by matching @handle -> user_id "
                    "against the twid session cookie"
                ),
            )

    if twid_user_id:
        return Identity(
            status="partial",
            handle=None,
            user_id=twid_user_id,
            source="cookie",
            detail=(
                "cookies are present (twid cookie carries a user_id) but "
                "X's identity endpoints could not be reached. "
                + (rest_error or "")
            ).strip(),
        )

    return Identity(
        status="none",
        source="none",
        detail=(
            rest_error
            or "no session cookies found; run `xtool login` to save them"
        ),
    )


def verify_from_cookie_file(
    cookies_path,
    *,
    expect_handle: Optional[str] = None,
) -> Identity:
    """Load cookies from disk and verify. Returns a "none" Identity on
    any load error so callers don't have to handle two exception paths."""
    from pathlib import Path

    p = Path(cookies_path)
    if not p.exists():
        return Identity(
            status="none",
            source="none",
            detail=f"no cookies file at {p}",
        )
    try:
        creds = Credentials.from_file(p)
    except ValueError as exc:
        return Identity(
            status="none",
            source="none",
            detail=f"could not read {p}: {exc}",
        )
    return verify_identity(creds, expect_handle=expect_handle)
