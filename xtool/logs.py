"""Centralized log management for xtool.

All operation logs are stored in ``~/.xtool/logs/`` with timestamped
filenames. This module provides helpers to create log paths, list
recent logs, and tighten the permissions on the log directory.

Privacy
-------
Log files can contain tweet ids, action outcomes, and (in older
versions) fragments of GraphQL response bodies and error messages.
Starting in v0.2.5:

* The ``~/.xtool/logs`` directory is chmodded to ``0700`` so other
  local users cannot even enumerate the filenames (which used to
  betray when xtool was last run).
* New log files created by :func:`log_path_for` are touched with
  mode ``0600``. Existing files are tightened to ``0600`` when
  listed. The append-mode writer in :mod:`xtool.actions` uses
  :func:`xtool._safe_io.safe_open_append` to keep the mode intact
  across appends.
* The redaction pass in :mod:`xtool._redact` happens one layer up,
  inside ``bulk_action``, so this module never has to know what the
  records contain.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ._safe_io import chmod_private_file, ensure_private_dir


LOGS_DIR = Path(os.path.expanduser("~/.xtool/logs"))


def ensure_logs_dir() -> Path:
    """Create the logs directory with mode 0700. Returns the path.

    Re-running this is cheap and idempotent: the directory is created
    if missing, and its mode is tightened to ``0700`` in either case.
    """
    return ensure_private_dir(LOGS_DIR)


def log_path_for(operation: str, *, suffix: str = ".jsonl") -> Path:
    """Generate a timestamped log file path for an operation and
    pre-create it with mode ``0600``.

    Example::

        ~/.xtool/logs/delete_20260509_143022.jsonl

    Pre-creating the file lets us guarantee the mode even on filesystems
    where POSIX ``open(..., O_CREAT, 0o600)`` is not honored (the
    explicit ``chmod`` call will clamp it). The append-mode writer in
    ``bulk_action`` opens the same path later via
    :func:`xtool._safe_io.safe_open_append` and refuses to follow a
    symlink at the path.
    """
    ensure_logs_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    p = LOGS_DIR / f"{operation}_{ts}{suffix}"
    # Touch with 0600 so the file exists and is private before any
    # caller starts writing to it. Use the same mkstemp-equivalent
    # flags as safe_open_append would: we do NOT use Path.touch() here
    # because its default mode is 0o666 masked by umask.
    if not p.exists():
        fd = os.open(
            p,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(fd)
    chmod_private_file(p)
    return p


def latest_log(operation: str | None = None) -> Path | None:
    """Return the most recent log file, optionally filtered by operation prefix."""
    if not LOGS_DIR.exists():
        return None
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if operation:
        logs = [p for p in logs if p.name.startswith(operation)]
    return logs[0] if logs else None


def list_logs(limit: int = 20) -> list[Path]:
    """Return recent log files sorted newest first.

    As a side effect, clamps the mode of every listed log to ``0600``.
    This is the cheapest place to self-heal permissions on older
    install trees that might have files written under a laxer umask.
    """
    if not LOGS_DIR.exists():
        return []
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in logs:
        chmod_private_file(p)
    return logs[:limit]


def log_summary(path: Path) -> dict[str, int]:
    """Read a log file and count outcomes."""
    import json
    counts: dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    outcome = rec.get("outcome", "unknown")
                    counts[outcome] = counts.get(outcome, 0) + 1
                except (ValueError, TypeError):
                    continue
    except OSError:
        pass
    return counts
