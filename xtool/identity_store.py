"""Safe, non-secret identity metadata persisted to ``~/.xtool/identity.json``.

Why this exists
---------------
After a successful verification (``xtool login`` with a handle, or
``xtool whoami --expect-handle veldorakite``) we want the next
``xtool`` invocation to display the account as ``@veldorakite``,
not as a raw numeric user_id. The cookies file cannot carry that
information safely -- it is the secret bag and we want to keep its
schema minimal -- so identity lives in its own file.

Privacy / security posture
--------------------------
* This file is NOT a secrets file. It never contains ``auth_token``,
  ``ct0``, or ``twid``. Loss of this file is annoying (the menu
  forgets which handle you're on) but not a credential leak.
* We still chmod 600 where the filesystem supports it, both because
  the file contains ``user_id`` (numeric id for the account) and on
  principle: anything xtool writes under ``~/.xtool/`` should be
  user-only readable.
* The ``user_id`` is stored so the menu can surface
  "last verified, recheck failed" without re-running a network
  lookup, but it is NEVER displayed by default. That gate lives in
  the UI layer.

Schema
------
::

    {
      "expected_handle":      "veldorakite",
      "last_verified_handle": "veldorakite",
      "last_verified_at":     "2026-05-09T17:34:02Z",
      "last_verified_user_id": "1816262302209085440",
      "last_verified_source":  "handle-match"
    }

Every field is optional; callers treat missing fields as "unknown"
rather than error. Extra fields written by a future version are
preserved on round-trip so we never destroy a key we don't recognise.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._safe_io import ensure_private_dir, safe_write_json


DEFAULT_PATH = Path(os.path.expanduser("~/.xtool/identity.json"))


@dataclass
class IdentityRecord:
    """In-memory mirror of the on-disk identity metadata.

    Every field is optional so callers can construct a record for a
    brand-new user (no fields populated) and merge it with whatever
    is currently on disk without having to special-case "first run".
    """

    expected_handle: Optional[str] = None
    last_verified_handle: Optional[str] = None
    last_verified_at: Optional[str] = None  # ISO 8601 UTC
    last_verified_user_id: Optional[str] = None
    last_verified_source: Optional[str] = None
    # Anything we didn't explicitly recognise, preserved so a newer
    # version's fields survive a round-trip through an older version.
    _extras: dict = field(default_factory=dict)

    # ----- serialization helpers ---------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict. Omits None fields so the
        on-disk shape stays compact and readable.
        """
        out = {}
        if self.expected_handle is not None:
            out["expected_handle"] = self.expected_handle
        if self.last_verified_handle is not None:
            out["last_verified_handle"] = self.last_verified_handle
        if self.last_verified_at is not None:
            out["last_verified_at"] = self.last_verified_at
        if self.last_verified_user_id is not None:
            out["last_verified_user_id"] = self.last_verified_user_id
        if self.last_verified_source is not None:
            out["last_verified_source"] = self.last_verified_source
        # Preserve unknown keys written by a future version of xtool.
        for k, v in self._extras.items():
            if k not in out:
                out[k] = v
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "IdentityRecord":
        known = {
            "expected_handle",
            "last_verified_handle",
            "last_verified_at",
            "last_verified_user_id",
            "last_verified_source",
        }
        extras = {k: v for k, v in data.items() if k not in known}
        return cls(
            expected_handle=data.get("expected_handle"),
            last_verified_handle=data.get("last_verified_handle"),
            last_verified_at=data.get("last_verified_at"),
            last_verified_user_id=data.get("last_verified_user_id"),
            last_verified_source=data.get("last_verified_source"),
            _extras=extras,
        )


def _iso_now() -> str:
    """Current UTC time as an ISO 8601 string with a trailing ``Z``.

    Chosen over ``datetime.isoformat()`` so the suffix is human-
    recognisable in screenshots ("2026-05-09T17:34:02Z"), and so we
    never emit a local-time string that would be ambiguous on a phone
    whose timezone the user can move around.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load(path: Optional[Path] = None) -> IdentityRecord:
    """Read the identity file and return an :class:`IdentityRecord`.

    Returns an empty record (all fields None) on any error -- missing
    file, permission denied, corrupt JSON, non-object JSON. Never
    raises. Callers should treat "empty record" and "no record" the
    same way.
    """
    p = Path(path) if path is not None else DEFAULT_PATH
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return IdentityRecord()
    if not isinstance(data, dict):
        return IdentityRecord()
    return IdentityRecord.from_dict(data)


def save(
    record: IdentityRecord,
    *,
    path: Optional[Path] = None,
) -> Path:
    """Persist ``record`` to disk.

    Uses :func:`xtool._safe_io.safe_write_json`, which:

    * Ensures the parent (``~/.xtool``) exists and is chmodded to
      ``0700``. The v0.2.4 version of this function left the directory
      at whatever ``mkdir`` produced with the process umask (often
      ``0755``), which meant any other user on the machine could list
      the filenames -- not a credential leak, but a correlation signal
      (``cookies.json exists`` = "this account is actively being
      cleaned up by xtool").
    * Writes the file atomically via a ``mkstemp`` + fsync + rename,
      with ``mode=0o600`` from the first byte. No chmod race.
    * Refuses to follow an attacker-placed symlink at ``path`` thanks
      to ``O_NOFOLLOW`` on the tempfile create; the final rename does
      not traverse symlinks at the destination either.

    Returns the path we wrote to. Propagates OSError to the caller
    (the CLI layer handles it with a printed warning) -- we would
    rather let the user know the write failed than silently carry on
    with an out-of-date state file.
    """
    p = Path(path) if path is not None else DEFAULT_PATH
    data = record.to_dict()
    safe_write_json(p, data)
    return p


def record_verified(
    *,
    handle: str,
    user_id: Optional[str] = None,
    source: Optional[str] = None,
    path: Optional[Path] = None,
) -> IdentityRecord:
    """Update the on-disk record after a successful verification.

    Merges with whatever is already on disk so unrelated fields
    (including unknown keys from a future version) are preserved.
    Returns the :class:`IdentityRecord` that was written, which is
    convenient for the caller to echo back.
    """
    current = load(path)
    current.expected_handle = handle
    current.last_verified_handle = handle
    current.last_verified_at = _iso_now()
    if user_id is not None:
        current.last_verified_user_id = user_id
    if source is not None:
        current.last_verified_source = source
    save(current, path=path)
    return current


def remember_expected_handle(
    handle: str,
    *,
    path: Optional[Path] = None,
) -> IdentityRecord:
    """Store the expected handle without marking it verified.

    Used by ``xtool login`` when the user typed a handle but the
    verification result came back partial -- we still want the next
    ``xtool whoami`` call to try the same handle automatically.
    """
    current = load(path)
    current.expected_handle = handle
    save(current, path=path)
    return current
