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


def find_git_root(start: Path) -> Optional[Path]:
    """Walk upward from ``start`` looking for a ``.git`` marker.

    ``start`` may point at a file or a directory; in either case we
    begin the search at its containing directory. Returns the first
    ancestor whose direct child is a ``.git`` entry (file or
    directory, so submodules and worktrees both work), or ``None`` if
    no ``.git`` is found all the way up to the filesystem root.

    We intentionally check for the ``.git`` entry on disk rather than
    shelling out to ``git rev-parse --show-toplevel`` so this helper
    still works on Termux where ``git`` may not be on PATH even when
    a checkout is present, and so it never spawns a subprocess during
    repo discovery.
    """
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _looks_like_xtool_checkout(root: Path) -> bool:
    """Cheap sanity check: the candidate repo root must contain an
    ``xtool/__init__.py`` for it to plausibly be an X-Tool clone.

    This matters for the cwd-fallback branch of :func:`_find_repo_root`
    -- we never want ``xtool update`` to wander into an unrelated
    git repo the user happened to be standing in, try to ``git pull``
    it, and then ``pip install`` it as "xtool". The package-location
    branch does not need this guard because the file we start from
    is already our own ``updater.py``.
    """
    return (root / "xtool" / "__init__.py").is_file()


def _find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Locate the X-Tool git checkout we should update.

    Strategy:

    1. **Package-location first.** Walk up from this module's file
       (``updater.py``). When installed with ``pip install -e .``,
       this lands inside the real checkout. When installed with the
       non-editable ``pip install .`` the package lives in
       ``site-packages`` and this walk finds nothing -- that's fine,
       we fall through to step 2.
    2. **Current working directory.** Walk up from :func:`os.getcwd`.
       If the user ran ``xtool update`` from inside ``~/x-tool``
       (or any subdirectory), this finds the checkout. Gated by
       :func:`_looks_like_xtool_checkout` so we never try to update
       an unrelated repo the user happens to be standing in.

    When both candidates resolve, the package-location wins because
    that is "the one containing the installed package path" -- i.e.
    the repo the running code actually came from. The ``start``
    argument exists for tests: it pins the package-location walk to
    a specific directory so the test can control the outcome.
    """
    # --- 1. package-location walk ----------------------------------------
    origin = Path(start) if start else Path(__file__)
    pkg_root = find_git_root(origin)

    # --- 2. cwd walk (only if package-location didn't find anything) ----
    if pkg_root is None:
        try:
            cwd = Path(os.getcwd())
        except (FileNotFoundError, OSError):
            # getcwd() can legitimately fail if the caller's cwd was
            # deleted. Just skip the fallback in that case.
            return None
        cwd_root = find_git_root(cwd)
        if cwd_root is not None and _looks_like_xtool_checkout(cwd_root):
            return cwd_root
        return None

    return pkg_root


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
            "X-Tool cannot auto-update because this install is not "
            "linked to a local git repository."
        )
        printer("")
        printer("Recommended Termux install:")
        printer("  git clone https://github.com/melynkhael/x-tool.git ~/x-tool")
        printer("  cd ~/x-tool")
        printer("  bash install.sh --quiet")
        printer("")
        printer(
            "Then future updates are just `xtool update` (or "
            "`cd ~/x-tool && git pull && bash install.sh --quiet`)."
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
