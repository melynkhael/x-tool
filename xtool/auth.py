"""Account identity verification for xtool.

X has been quietly deprecating the legacy 1.1 REST endpoints the web
client used to call on page load (``/account/settings.json``,
``/account/verify_credentials.json``). When those routes 404, xtool's
older whoami logic looked like cookies were bad even though the same
cookies worked for every GraphQL mutation we actually run.

This module makes identity verification multi-signal and order-aware
so ``xtool whoami`` gives users a useful, truthful status regardless
of which X surface is up:

1. **REST whoami** -- the fast happy path. When x.com's REST surface
   is healthy we get both ``screen_name`` and ``user_id`` in one call
   and we're done.

2. **twid cookie** -- once logged in, x.com sets a ``twid`` cookie
   that carries the numeric ``user_id``. xtool can also accept the
   value directly during ``xtool login`` (the third optional prompt)
   and inject it into the session jar before verification. This gives
   us a strong "you are definitely logged in, and here's which
   account" signal without depending on REST at all.

3. **GraphQL handle-match** -- when the caller knows the expected
   handle (either via ``--expect-handle`` or the wizard login prompt),
   we resolve it via ``UserByScreenName`` and compare the returned
   ``rest_id`` to the twid user_id. A match upgrades the status to
   ``verified`` because X itself confirmed that this handle belongs
   to the session's user_id. A mismatch is NOT verified -- that's
   the whole point of the check.

Returned shape
--------------
Every entry point returns an :class:`Identity` dataclass:

* ``status``  - ``"verified"`` | ``"partial"`` | ``"none"``.
* ``handle``  - the account's @screen_name, without the ``@``, when
  known (REST whoami returned it, or GraphQL handle-match confirmed
  it).
* ``user_id`` - numeric user id as a string, when known (REST whoami
  or twid cookie).
* ``source``  - short tag describing the strongest signal used:
  ``"rest"``, ``"handle-match"``, ``"twid"``, ``"cookie"``, ``"none"``.
* ``detail``  - human-readable diagnostic. Safe to show in the UI;
  callers get this verbatim in the partial banner to explain what
  the tool is able to prove.
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


@dataclass
class Identity:
    """Structured result of an identity check.

    Display contract
    ----------------
    The numeric ``user_id`` is an *internal* field. UI callers must
    never render it in default output -- it leaks the account's
    permanent identifier into screenshots, GitHub issues, etc. See
    :func:`xtool.ui.format_identity_line` for the opt-in
    (``show_user_id``) display path.

    ``last_verified_handle`` / ``recheck_failed`` are populated by
    :func:`verify_from_cookie_file` when the current network probe
    can't confirm the handle but we have a previously-verified handle
    on disk. This lets the menu render::

        Account: @veldorakite last verified, recheck failed

    instead of collapsing all network hiccups to the less useful
    "cookies saved, identity not verified" line.
    """

    status: str  # "verified" | "partial" | "none"
    handle: Optional[str] = None
    user_id: Optional[str] = None
    # "rest", "handle-match", "twid", "cookie", or "none".
    source: str = "none"
    detail: str = ""
    # Populated by verify_from_cookie_file when the live check is
    # degraded but the identity file says we have trusted it before.
    # These NEVER override ``status`` / ``handle`` -- they are
    # supplementary display hints.
    last_verified_handle: Optional[str] = None
    recheck_failed: bool = False

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def has_cookies(self) -> bool:
        return self.status in ("verified", "partial")

    def one_liner(self) -> str:
        """Compact single-line summary for the menu header.

        Plain text, no styling -- the UI layer wraps this in Rich
        markup so the same string can be reused in test assertions.

        The user ID is deliberately NEVER included here; the menu
        header is the highest-exposure surface (visible on every
        prompt) and we do not want a numeric account identifier
        showing up in every screenshot.
        """
        # Stale-verified state: we trusted a handle before, but the
        # current probe couldn't reconfirm it (network down, REST
        # rotated, etc.). Prefer this over the cookie/twid partial
        # shapes because the "remembered" handle is more useful than
        # the raw cookie state.
        if (
            self.status == "partial"
            and self.recheck_failed
            and self.last_verified_handle
        ):
            return (
                f"@{self.last_verified_handle} last verified, recheck failed"
            )

        if self.status == "verified" and self.handle:
            # Spec: the clean handle IS the verified indicator. The
            # word "verified" made the menu look cluttered and
            # technical; colour/emphasis carries the meaning.
            return f"@{self.handle}"

        if self.status == "partial":
            if self.handle:
                return f"@{self.handle} (not verified)"
            # twid present but no confirmed handle. We DO NOT show the
            # numeric user_id here any more -- it leaked the account's
            # permanent identifier into every screenshot.
            if self.user_id:
                return "twid found, handle not verified"
            return "cookies saved, identity not verified"
        return "not logged in"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# A raw numeric twid (user_id only, no "u=" prefix) is what X's mobile
# app occasionally stores; we accept that form too so power users can
# paste just the digits.
_NUMERIC_ONLY = re.compile(r"^\d+$")

# Within a cookie value we look for a "u=<digits>" pair. The value may
# arrive url-encoded (u%3D), unquoted, wrapped in double quotes, or
# preceded/followed by other key=value pairs -- all are tolerated.
_TWID_USER_ID = re.compile(r"u(?:%3D|=)(\d+)")


def parse_twid_user_id(raw: Optional[str]) -> Optional[str]:
    """Extract the numeric user_id from a user-supplied twid string.

    Accepts every form X (or a careless paste) can produce:

      * ``"u=1234567890"`` -- the canonical unescaped form.
      * ``'"u=1234567890"'`` -- wrapped in double quotes (DevTools
        occasionally copies cookies this way).
      * ``"u%3D1234567890"`` -- url-encoded.
      * ``"1234567890"`` -- bare numeric string, if the user pasted
        only the id portion.
      * Extra junk before or after is ignored, so values like
        ``"kdt=...; u=1234; sess=..."`` also work.

    Returns the numeric user_id as a string, or None when nothing
    recognisable is present. Never raises, never prints.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Strip enclosing quotes if present.
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    if not s:
        return None

    # Fast path: bare numeric id.
    if _NUMERIC_ONLY.match(s):
        return s

    # Otherwise look for the u=<digits> pattern anywhere in the value.
    m = _TWID_USER_ID.search(s)
    return m.group(1) if m else None


def normalize_handle(raw: Optional[str]) -> Optional[str]:
    """Return a canonical X screen_name from whatever the user typed.

    Strips leading ``@`` (any number of them, for paranoia), trims
    whitespace, and lowercases. Returns None for empty / whitespace
    input so callers can `if not normalize_handle(x):` cleanly.

    X screen_names are themselves case-insensitive; lowercasing here
    means handle comparisons elsewhere in the codebase don't have to
    spell that out every time.
    """
    if raw is None:
        return None
    s = str(raw).strip().lstrip("@").strip()
    return s.lower() or None


# ---------------------------------------------------------------------------
# Session signals
# ---------------------------------------------------------------------------

def extract_twid_user_id(session: requests.Session) -> Optional[str]:
    """Pull the numeric user id out of a session's ``twid`` cookie, if
    present. Returns None when absent or malformed; never raises.

    Delegates parsing to :func:`parse_twid_user_id` so the same rules
    apply whether the twid arrives via the cookie jar or via direct
    user input.
    """
    twid = ""
    for c in session.cookies:
        if c.name == "twid":
            twid = c.value or ""
            break
    return parse_twid_user_id(twid)


def _has_auth_cookies(session: requests.Session) -> bool:
    """Return True when the session jar has non-empty ``auth_token``
    *and* ``ct0`` cookies.

    This is a weaker signal than ``twid`` (which also carries the
    user_id), but it lets us distinguish "the user just pasted cookies
    that couldn't be verified" from "no cookies at all" -- without
    it, a freshly-built session would look identical to an empty one
    immediately after login.
    """
    have_auth = False
    have_ct0 = False
    for c in session.cookies:
        if c.name == "auth_token" and (c.value or "").strip():
            have_auth = True
        elif c.name == "ct0" and (c.value or "").strip():
            have_ct0 = True
    return have_auth and have_ct0


def _try_rest(session: requests.Session) -> tuple[Optional[dict], Optional[str]]:
    """Run REST whoami. Returns (result, error_detail)."""
    try:
        return whoami(session), None
    except ActionError as exc:
        return None, str(exc).split("\n", 1)[0]  # first line only for UI


def _try_handle_match(
    session: requests.Session,
    handle: str,
    twid_user_id: str,
) -> Optional[tuple[str, str]]:
    """Resolve ``handle`` via GraphQL and confirm it matches the twid
    user_id.

    Returns ``(resolved_user_id, "handle-match")`` ONLY when the ids
    match. A mismatch (or any error) returns None. We deliberately
    do NOT return the handle the user typed as "verified" just because
    they typed it -- the whole point of the match is that X itself has
    to say yes.
    """
    if not handle or not twid_user_id:
        return None
    # Lazy import -- keeps `xtool whoami` fast when no GraphQL call is
    # needed (e.g. REST whoami succeeded or no handle was supplied).
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
    """Best-effort identity check. Never raises.

    Decision order:

    1. REST whoami succeeds              -> ``verified`` (source ``rest``).
    2. twid cookie present AND
       expect_handle resolves to same id -> ``verified`` (``handle-match``).
    3. twid cookie present, no match     -> ``partial`` (``twid``).
    4. auth_token + ct0 in the jar,
       but no twid                       -> ``partial`` (``cookie``).
    5. no signal at all                  -> ``none``.

    ``expect_handle`` is normalized before use, so the caller can pass
    ``"@Veldorakite"`` or ``"VELDORAKITE"`` and handle-match will still
    work. The GraphQL path is the fallback that keeps the tool honest
    when X's REST identity endpoints are 404ing.
    """
    sess = session or build_session(creds)

    # --- 1. REST fast path ------------------------------------------------
    rest_result, rest_error = _try_rest(sess)
    if rest_result:
        return Identity(
            status="verified",
            handle=rest_result.get("screen_name"),
            user_id=rest_result.get("user_id"),
            source="rest",
            detail="identity confirmed via X REST endpoint",
        )

    # --- 2. twid + handle-match via GraphQL -------------------------------
    twid_user_id = extract_twid_user_id(sess)
    normalized_handle = normalize_handle(expect_handle)

    if normalized_handle and twid_user_id:
        match = _try_handle_match(sess, normalized_handle, twid_user_id)
        if match:
            resolved_id, src = match
            return Identity(
                status="verified",
                handle=normalized_handle,
                user_id=resolved_id,
                source=src,
                detail=(
                    "identity confirmed: GraphQL UserByScreenName resolved "
                    f"@{normalized_handle} to user_id {resolved_id}, which "
                    "matches the twid cookie."
                ),
            )

    # --- 3. twid only -----------------------------------------------------
    if twid_user_id:
        detail = (
            "cookies are valid and the twid cookie identifies the session "
            f"as user_id {twid_user_id}. "
        )
        if normalized_handle:
            # We had a handle but couldn't confirm it -- either
            # UserByScreenName failed, or the handle resolved to a
            # different id. Either way, don't claim verified.
            detail += (
                f"Could not confirm @{normalized_handle} via GraphQL; "
                "the handle may be wrong, protected, or the lookup failed."
            )
        else:
            detail += (
                "No handle was supplied; pass --expect-handle to confirm "
                "this cookie belongs to a specific @screen_name."
            )
        return Identity(
            status="partial",
            handle=None,
            user_id=twid_user_id,
            source="twid",
            detail=detail.strip(),
        )

    # --- 4. auth_token + ct0 only -----------------------------------------
    if _has_auth_cookies(sess):
        return Identity(
            status="partial",
            handle=None,
            user_id=None,
            source="cookie",
            detail=(
                "cookies are saved (auth_token + ct0 present) but X's "
                "identity endpoints could not be reached. "
                + (rest_error or "")
            ).strip(),
        )

    # --- 5. nothing at all ------------------------------------------------
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
    """Load cookies from disk and verify. Returns a ``status="none"``
    Identity on any load error, so callers don't need two exception
    paths.

    When ``expect_handle`` is None we fall back to whatever handle the
    user previously verified (via ``xtool whoami --expect-handle``);
    this is what lets plain ``xtool`` show ``Account: @handle`` after
    a previous verification without asking the user to retype their
    handle every time the menu opens.

    If the live probe ends up in a weaker state than a previously
    recorded verification, we annotate the returned Identity with
    ``last_verified_handle`` and ``recheck_failed=True`` so the
    caller can render the stale-verified state. We deliberately do
    NOT promote the status to ``verified`` in that case -- safety
    checks should still reflect what the tool can prove *right now*.
    """
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

    # Fall back to the persisted expected-handle so repeat launches
    # don't need --expect-handle. Import lazily to avoid a cycle.
    from . import identity_store  # local import: keeps module init cheap
    record = identity_store.load()
    handle_for_probe = expect_handle or record.expected_handle

    identity = verify_identity(creds, expect_handle=handle_for_probe)

    # If we have a recorded verification and this probe came back
    # weaker, stamp the identity with the stale-verified annotations
    # so the UI can render "@handle last verified, recheck failed".
    if (
        identity.status == "partial"
        and not identity.handle
        and record.last_verified_handle
    ):
        identity.last_verified_handle = record.last_verified_handle
        identity.recheck_failed = True
    return identity
