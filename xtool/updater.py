"""Self-update helper for X-Tool.

Provides a beginner-friendly ``xtool update`` command so users no
longer need to remember the two-step ``git pull`` + ``pip install -e .``
sequence -- which printed hundreds of lines of pip output that made
beginners think something was broken.

Design goals
------------
* Three short progress lines, not a wall of pip output.
* Real errors are still surfaced verbatim -- we never silently swallow
  a failed ``git pull`` or a ``pip`` build error. Beginners need those
  to ask for help.
* No shell plumbing, no ``shell=True``. We pass arg lists to
  :func:`subprocess.run` so spaces in paths can't turn into command
  injection.
* Works whether xtool was installed with ``pip install -e .`` (a git
  checkout) or ``pip install git+https://...`` (no working tree on
  disk). When no git checkout is found, we print a helpful message
  rather than failing with a cryptic ``git: not a repository`` error.

Return codes
------------
:func:`run_update` returns an integer exit code so both the menu and
the CLI subcommand can use it directly:

* ``0`` -- update succeeded (or already up to date).
* ``1`` -- update failed; the error was printed to the user.
* ``2`` -- prerequisites missing (no git checkout, no git binary,
  etc.); a hint was printed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import __version__


def _find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from ``start`` (or the package directory) looking for
    a ``.git`` directory. Returns the repo root or None.

    We check ``.git`` is present, rather than calling ``git
    rev-parse``, because that avoids spawning a subprocess during
    discovery and works correctly on Termux where ``git`` may not be
    on PATH even though a clone exists.
    """
    here = Path(start) if start else Path(__file__).resolve().parent
    for path in (here, *here.parents):
        if (path / ".git").exists():
            return path
    return None


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    capture: bool = True,
) -> tuple[int, str, str]:
    """Run ``cmd`` in ``cwd`` and return ``(returncode, stdout, stderr)``.

    We run with ``text=True`` so output is decoded as UTF-8, and we
    never use ``shell=True`` (arg list, not string) so the call is
    safe regardless of what ``cwd`` contains.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            capture_output=capture,
            text=True,
        )
    except FileNotFoundError as exc:
        # Binary missing (e.g. git not installed). Surface a readable
        # error instead of a raw traceback.
        return 127, "", f"command not found: {cmd[0]}: {exc}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _latest_commit_short(repo: Path) -> str:
    """Return the short hash of HEAD, or an empty string on failure."""
    rc, out, _err = _run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo
    )
    return out.strip() if rc == 0 else ""


def run_update(
    *,
    repo_path: Optional[Path] = None,
    printer=print,
) -> int:
    """Pull the latest code and reinstall the package.

    Parameters
    ----------
    repo_path
        Optional override for the repo root. When omitted we look
        upwards from this module's directory for a ``.git`` marker.
        Tests supply this to point at a throwaway clone.
    printer
        Callable used for user-facing output. Defaults to :func:`print`
        so the function is testable without monkeypatching stdout.

    Returns
    -------
    int
        See the module docstring for the exit-code table.
    """
    # --- preflight --------------------------------------------------------
    repo = repo_path if repo_path is not None else _find_repo_root()
    if repo is None:
        printer(
            "X-Tool was not installed from a git checkout, so `xtool "
            "update` cannot run."
        )
        printer(
            "Reinstall it with:"
        )
        printer(
            "  pip install --upgrade "
            "git+https://github.com/melynkhael/x-tool.git"
        )
        return 2

    if shutil.which("git") is None:
        printer("git is not installed or not on PATH.")
        printer("On Termux install it with: pkg install git")
        return 2

    # --- git pull ---------------------------------------------------------
    printer("Updating X-Tool...")
    printer("Pulling latest version...")
    rc, out, err = _run(
        ["git", "pull", "--ff-only", "--quiet", "origin", "main"],
        cwd=repo,
    )
    if rc != 0:
        # Surface the real error. Beginners need the actual message to
        # ask for help (merge conflict, detached HEAD, no network, ...).
        printer("git pull failed:")
        if out.strip():
            printer(out.rstrip())
        if err.strip():
            printer(err.rstrip())
        printer(
            "Fix the issue above and rerun `xtool update`, or run the "
            "install script manually:"
        )
        printer("  cd ~/x-tool && bash install.sh")
        return 1

    # --- pip install ------------------------------------------------------
    printer("Installing package...")
    rc, out, err = _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            ".",
            "--upgrade",
            "--disable-pip-version-check",
            "-q",
        ],
        cwd=repo,
    )
    if rc != 0:
        printer("pip install failed:")
        # With -q, pip still prints real errors to stderr; keep both
        # streams so users see everything that mattered.
        if out.strip():
            printer(out.rstrip())
        if err.strip():
            printer(err.rstrip())
        printer(
            "Fix the issue above and rerun `xtool update`, or run the "
            "install script manually:"
        )
        printer("  cd ~/x-tool && bash install.sh")
        return 1

    # --- done -------------------------------------------------------------
    printer("Done.")
    printer("")
    # Re-import __version__ in a fresh module to pick up the new value
    # from disk when possible. In the running process we still show
    # the version string that's currently loaded -- there's no way to
    # hot-reload a Python package -- but we annotate it so users know
    # to relaunch the CLI if the number didn't change as expected.
    commit = _latest_commit_short(repo)
    version_line = f"X-Tool v{_current_version_on_disk(repo) or __version__} is ready."
    printer(version_line)
    if commit:
        printer(f"Latest commit: {commit}")
    printer("Run `xtool` to open the menu.")
    return 0


def _current_version_on_disk(repo: Path) -> Optional[str]:
    """Best-effort: read the version string from the freshly-pulled
    package tree on disk so the "ready" line reflects what the next
    process will see, not what this process happens to have imported.

    Returns None on any failure -- the caller falls back to the
    in-memory ``__version__``.
    """
    init = repo / "xtool" / "__init__.py"
    try:
        text = init.read_text(encoding="utf-8")
    except OSError:
        return None
    import re
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else None
