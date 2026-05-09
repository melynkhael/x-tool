"""Private / safe filesystem helpers for xtool.

Every path xtool writes under ``~/.xtool/`` may contain data a local
attacker or a mis-configured backup tool could abuse:

* ``cookies.json``      - auth_token, ct0, twid (full credentials).
* ``identity.json``     - handle + numeric user_id.
* ``query_ids.json``    - harmless on its own but under the same dir.
* ``logs/*.jsonl``      - tweet ids and (pre-redaction) GraphQL bodies.
* ``*.debug.jsonl``     - raw timeline instructions, private data.

This module centralises three rules the rest of the code leans on:

1. **The xtool directory is 0700.** Nobody but the owning user should
   be able to list it.
2. **Every sensitive file is 0600** by the time its *first byte* is
   visible. We accomplish this by using :func:`os.open` with
   ``O_CREAT|O_EXCL`` (new files) or ``O_CREAT`` (append mode) and an
   explicit ``mode=0o600`` instead of relying on the process umask +
   a follow-up ``chmod``. A concurrent attacker cannot race a read
   between the create and the chmod because the create itself already
   produced the restricted mode.
3. **We do not follow symlinks** when writing sensitive files. An
   attacker-placed symlink at ``~/.xtool/cookies.json`` pointing at
   ``/etc/passwd`` or some other victim file must not cause xtool to
   overwrite that file. We pass ``O_NOFOLLOW`` so a symlinked target
   raises ``ELOOP`` / ``FileExistsError`` instead of silently being
   used.

On platforms where ``O_NOFOLLOW`` or POSIX modes are not available
(Windows, some FAT-mounted Termux paths) we degrade gracefully: the
file is still written, and :func:`chmod_private_file` returns ``False``
so callers can surface "could not chmod 600" warnings when the user
should know.

The helpers never print, never raise for the "nothing to do" cases
(file missing, already private, platform cannot chmod) and never
swallow real OS errors like ``PermissionError`` from the create step.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


# Bit flags reused across helpers. ``os.O_NOFOLLOW`` is not defined on
# Windows; fall back to 0 so the open call still succeeds there (on
# Windows the NTFS junction/reparse-point threat model is different and
# the equivalent protection lives in the Windows API, not POSIX flags).
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def is_posix() -> bool:
    """Return True on platforms that honor POSIX chmod semantics.

    Used by callers that want to skip permission assertions on
    Windows / FAT without pulling ``os.name`` checks all over the
    code base.
    """
    return os.name == "posix"


# ---------------------------------------------------------------------------
# Directory: 0700
# ---------------------------------------------------------------------------

def ensure_private_dir(path: str | os.PathLike) -> Path:
    """Create ``path`` (and any parents) and enforce mode 0700.

    * If the directory does not exist, it is created with mode 0700.
    * If it already exists, its mode is tightened down to 0700. We
      only ever *remove* group/world permission bits here; if a user
      has deliberately loosened the directory (for a backup tool,
      say) this helper will re-lock it. That is intentional -- the
      contract is "xtool's private directory is always 0700". The
      doctor command reports on this rather than silently normalising.

    Returns the resolved :class:`~pathlib.Path` so callers can chain
    further writes against it.

    Platform notes
    --------------
    * On Windows chmod is a no-op; we still create the directory and
      return normally.
    * If ``path`` exists and is *not* a directory (e.g. a regular file
      at ``~/.xtool``), :class:`NotADirectoryError` propagates from
      :func:`Path.mkdir`. Callers should treat that as a fatal config
      problem and ask the user to remove the stray file.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    if is_posix():
        try:
            os.chmod(p, 0o700)
        except OSError:
            # Some Termux shared-storage paths silently refuse chmod.
            # The caller (or doctor) will surface this.
            pass
    return p


def chmod_private_dir(path: str | os.PathLike) -> bool:
    """Tighten ``path`` to 0700. Returns ``True`` on success.

    Missing paths / non-POSIX platforms return ``False`` without
    raising so callers can use this as a best-effort tighten without
    wrapping it in try/except every time.
    """
    p = Path(path)
    if not p.exists() or not is_posix():
        return False
    try:
        os.chmod(p, 0o700)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# File: 0600 atomic writes
# ---------------------------------------------------------------------------

def chmod_private_file(path: str | os.PathLike) -> bool:
    """Tighten ``path`` to 0600. Returns ``True`` on success.

    Mirrors :func:`chmod_private_dir` but with the file mode. Used by
    callers that need to clamp a file they did not just create
    themselves (e.g. the doctor command's auto-repair path).
    """
    p = Path(path)
    if not p.exists() or not is_posix():
        return False
    try:
        os.chmod(p, 0o600)
    except OSError:
        return False
    return True


def _open_private_exclusive(path: Path) -> int:
    """Open ``path`` for exclusive creation with mode 0600 and no
    symlink follow. Returns the raw file descriptor.

    Raises :class:`FileExistsError` if the path already exists as
    *any* filesystem entry, including a symlink. This is how we
    ensure atomic replace never follows an attacker-placed symlink:
    the tempfile we write to is a brand-new path, and the final
    :func:`os.replace` is rename-based and does not traverse
    symlinks at the target.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW
    return os.open(path, flags, 0o600)


def safe_write_bytes(
    path: str | os.PathLike,
    data: bytes,
    *,
    ensure_parent_private: bool = True,
) -> Path:
    """Atomically write ``data`` to ``path`` with mode 0600.

    Guarantees, in order:

    1. The parent directory exists. When ``ensure_parent_private`` is
       ``True`` (the default) it is also chmodded to 0700.
    2. A sibling tempfile is created with mode 0600 via ``O_CREAT |
       O_EXCL | O_NOFOLLOW``. An attacker cannot race a symlink in
       place of this tempfile because exclusive-create fails if the
       name exists, and the name contains a random suffix we just
       generated.
    3. ``data`` is written and fsync'd.
    4. :func:`os.replace` renames the tempfile over ``path``. Rename
       is atomic on POSIX and does not follow symlinks at the
       destination: a symlink at ``path`` is replaced with the real
       file, not traversed.

    Returns the final :class:`~pathlib.Path`. On any failure the
    tempfile is unlinked before the exception propagates so we do
    not leave a 0600 turd next to ``path``.

    Windows fallback
    ----------------
    ``O_NOFOLLOW`` is absent on Windows; the call still succeeds but
    does not provide symlink protection. Callers that care about
    Windows security should rely on NTFS ACLs instead -- the xtool
    project targets Termux/Linux/macOS primarily.
    """
    p = Path(path)
    if ensure_parent_private:
        ensure_private_dir(p.parent)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)

    # NamedTemporaryFile picks a cryptographically random suffix and
    # respects ``dir=`` so the temp file lives alongside the final
    # path (a prerequisite for atomic os.replace on the same
    # filesystem).
    tmp_fd = None
    tmp_path: Path | None = None
    try:
        # mkstemp gives us the fd + name atomically, but the default
        # mode is 0600 only on some platforms; we chmod explicitly
        # below to be sure.
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=p.name + ".",
            suffix=".tmp",
            dir=str(p.parent),
        )
        tmp_path = Path(tmp_name)
        if is_posix():
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                # Non-fatal: rename still wins, doctor will flag.
                pass
        with os.fdopen(tmp_fd, "wb", closefd=True) as fh:
            tmp_fd = None  # fdopen took ownership
            fh.write(data)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # Some filesystems (procfs, tmpfs overlays on Termux)
                # don't implement fsync. That's fine; replace is still
                # atomic at the rename layer.
                pass
        os.replace(tmp_path, p)
        tmp_path = None  # replaced, no cleanup needed
        # Post-rename: make doubly sure the final file is 0600. On
        # Linux + ext4 the mode survives replace, but some FUSE
        # backends reset it.
        if is_posix():
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        return p
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def safe_write_text(
    path: str | os.PathLike,
    text: str,
    *,
    encoding: str = "utf-8",
    ensure_parent_private: bool = True,
) -> Path:
    """Text variant of :func:`safe_write_bytes`. Encodes UTF-8 by
    default because that is what every JSON / JSONL file in xtool
    uses.
    """
    return safe_write_bytes(
        path,
        text.encode(encoding),
        ensure_parent_private=ensure_parent_private,
    )


def safe_write_json(
    path: str | os.PathLike,
    payload: Any,
    *,
    indent: int = 2,
    sort_keys: bool = True,
    ensure_parent_private: bool = True,
) -> Path:
    """Dump ``payload`` as JSON via :func:`safe_write_text`.

    Convenience wrapper -- the three callers (cookies, identity,
    query_ids cache) all want the same JSON style so we keep the
    formatting consistent in one place.
    """
    body = json.dumps(payload, indent=indent, sort_keys=sort_keys) + "\n"
    return safe_write_text(
        path,
        body,
        ensure_parent_private=ensure_parent_private,
    )


# ---------------------------------------------------------------------------
# File: 0600 append-mode open (for logs)
# ---------------------------------------------------------------------------

def safe_open_append(
    path: str | os.PathLike,
    *,
    encoding: str = "utf-8",
    ensure_parent_private: bool = True,
):
    """Open ``path`` for append with mode 0600 and no symlink follow.

    Log files are opened in append mode for the lifetime of a bulk
    run; we cannot use the atomic-tempfile pattern there. Instead we
    call :func:`os.open` with ``O_CREAT | O_APPEND | O_NOFOLLOW`` and
    an explicit ``mode=0o600`` so a brand-new log file is already
    0600 the moment it exists. If the file already exists and was
    previously more permissive, we also chmod it down after opening.

    Returns a file object opened in text mode. The file is NOT a
    context manager courtesy; the caller is expected to use
    ``with`` / ``close()`` as usual.

    An attacker-placed symlink at ``path`` raises :class:`OSError`
    with ``errno.ELOOP`` (POSIX) instead of silently logging into
    the victim file.
    """
    p = Path(path)
    if ensure_parent_private:
        ensure_private_dir(p.parent)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_NOFOLLOW
    fd = os.open(p, flags, 0o600)
    # Tighten an existing file that may have been created with a
    # laxer mode on an older xtool version.
    if is_posix():
        try:
            os.fchmod(fd, 0o600)
        except (OSError, AttributeError):
            # fchmod missing on some platforms; fall back to path chmod.
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
    return os.fdopen(fd, "a", encoding=encoding)


# ---------------------------------------------------------------------------
# Read-side: inspection
# ---------------------------------------------------------------------------

def file_mode(path: str | os.PathLike) -> int | None:
    """Return the numeric permission bits of ``path`` (e.g. ``0o600``),
    or ``None`` when the file does not exist.

    Used by :mod:`xtool.doctor` to audit permissions without
    duplicating ``os.stat`` + masking logic all over the place.
    """
    p = Path(path)
    try:
        st = p.stat()
    except (FileNotFoundError, OSError):
        return None
    return stat.S_IMODE(st.st_mode)


def is_symlink(path: str | os.PathLike) -> bool:
    """Thin wrapper that never raises: returns False when the path is
    missing, to match the rest of this module's "best effort" style.
    """
    try:
        return Path(path).is_symlink()
    except OSError:
        return False
