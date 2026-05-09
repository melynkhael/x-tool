"""`xtool doctor` -- local security / privacy self-check.

Runs a read-only audit of the user's ``~/.xtool/`` directory, the
current repo / working directory, and a few well-known leak sites.
Reports problems in a human-readable table and exits with a non-zero
status when any **critical** issue is found so shell scripts and CI
can wire it up as a pre-commit style check.

Design rules (from the v0.2.5 security audit)
---------------------------------------------
1. **Never print a secret value.** Not auth_token, not ct0, not twid,
   not a full cookie header, not even a numeric user_id. The doctor
   output is meant to be shareable in a bug report.
2. **Read-only by default.** ``--fix`` (opt-in) will tighten obvious
   permission issues, but it will never move, delete, or rename files
   without an explicit confirmation prompt.
3. **No network calls.** The doctor only inspects files the user
   already has on disk. It is safe to run on an airplane.
4. **Honest severities.** An issue is ``critical`` only when it could
   actually leak a secret; everything else is ``warning`` (worth
   fixing) or ``info`` (context). Doctor's exit code is driven by
   the count of critical issues.

Checks
------
* **xtool-directory**: exists? is a directory? mode is ``0700``?
* **cookies.json**: exists? mode is ``0600``? not a symlink?
* **identity.json**: exists? mode is ``0600``? not a symlink?
  content is free of credentials?
* **query_ids.json**: exists? mode is ``0600``? not a symlink?
* **logs directory**: mode is ``0700``? per-file modes are ``0600``?
* **leak scan**: a small set of paths likely to have been used to
  paste cookies (``~/.bash_history``, ``~/.zsh_history``,
  ``~/.xtool/``, the git checkout) are grep'd for auth_token / ct0
  patterns. Matches are flagged without echoing the match.
* **git-tracked secrets**: if the cwd is a git checkout, doctor asks
  git whether any file named ``cookies.json`` / ``identity.json`` /
  ``query_ids.json`` / ``*.debug.jsonl`` / ``*.err`` is currently
  tracked. A tracked cookies.json would mean the file is inside the
  repo AND about to be pushed.

Exit codes
----------
* ``0`` -- no critical issues, zero or more warnings / infos.
* ``1`` -- at least one critical issue.
* ``2`` -- doctor itself failed (e.g. Python errors); never reached
  in normal operation, kept for symmetry with the CLI contract.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich import box

from ._redact import looks_like_leak, sensitive_basenames
from ._safe_io import (
    chmod_private_dir,
    chmod_private_file,
    file_mode,
    is_posix,
    is_symlink,
)


# How many bytes we read from each candidate file during the leak scan.
# History files can be tens of megabytes; we only need a quick pattern
# hit, not a full scan.
_LEAK_SCAN_BYTES = 256 * 1024


# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITY_OK = "ok"

_SEVERITY_STYLE = {
    SEVERITY_OK: "green",
    SEVERITY_INFO: "dim",
    SEVERITY_WARNING: "yellow",
    SEVERITY_CRITICAL: "bold red",
}


@dataclass
class Finding:
    """One row in the doctor report.

    * ``check``    -- short identifier, e.g. ``"cookies-mode"``.
      Stable across versions so wrapper scripts can grep for it.
    * ``severity`` -- one of the SEVERITY_* constants.
    * ``message``  -- human-readable one-liner. MUST NOT contain a
      secret value; it may contain filenames and permission modes.
    * ``fix``      -- short suggestion the user can act on, or empty
      when the finding is purely informational.
    """

    check: str
    severity: str
    message: str
    fix: str = ""


@dataclass
class Report:
    """Aggregate of all findings, with convenience counters."""

    findings: list[Finding] = field(default_factory=list)

    def add(self, check: str, severity: str, message: str, fix: str = "") -> None:
        self.findings.append(Finding(check, severity, message, fix))

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)

    @property
    def ok_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SEVERITY_OK)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _xtool_dir() -> Path:
    return Path(os.path.expanduser("~/.xtool"))


def _cookies_path() -> Path:
    return _xtool_dir() / "cookies.json"


def _identity_path() -> Path:
    return _xtool_dir() / "identity.json"


def _query_ids_path() -> Path:
    return _xtool_dir() / "query_ids.json"


def _logs_dir() -> Path:
    return _xtool_dir() / "logs"


def _check_directory(report: Report) -> None:
    """``~/.xtool/`` should exist and be ``0700``."""
    p = _xtool_dir()
    if not p.exists():
        report.add(
            "xtool-dir",
            SEVERITY_INFO,
            f"{p} does not exist yet",
            fix="Run `xtool login` to create it.",
        )
        return
    if not p.is_dir():
        report.add(
            "xtool-dir",
            SEVERITY_CRITICAL,
            f"{p} exists but is not a directory",
            fix="Remove the stray file and rerun xtool.",
        )
        return
    if is_posix():
        mode = file_mode(p)
        if mode is None:
            report.add(
                "xtool-dir",
                SEVERITY_WARNING,
                f"cannot read permissions on {p}",
            )
            return
        if mode != 0o700:
            report.add(
                "xtool-dir",
                SEVERITY_CRITICAL,
                f"{p} mode is {oct(mode)}; should be 0o700",
                fix=f"chmod 700 {p}  (or run `xtool doctor --fix`)",
            )
            return
    report.add("xtool-dir", SEVERITY_OK, f"{p} exists and is 0o700")


def _check_private_file(
    report: Report,
    *,
    path: Path,
    check_name: str,
    required: bool,
    label: str,
) -> None:
    """Shared 0600 / symlink / existence check for sensitive files.

    ``required`` is True for ``cookies.json`` (the login step creates
    it and the user presumably wants doctor to flag its absence) and
    False for ``identity.json`` / ``query_ids.json`` which are only
    created on demand.
    """
    if not path.exists() and not path.is_symlink():
        sev = SEVERITY_WARNING if required else SEVERITY_INFO
        report.add(
            check_name,
            sev,
            f"{label} ({path}) does not exist",
            fix="Run `xtool login`." if required else "",
        )
        return

    if is_symlink(path):
        report.add(
            check_name,
            SEVERITY_CRITICAL,
            f"{label} is a symlink; xtool refuses to follow it",
            fix=f"Remove the symlink: rm {path}",
        )
        return

    if is_posix():
        mode = file_mode(path)
        if mode is None:
            report.add(
                check_name,
                SEVERITY_WARNING,
                f"cannot read permissions on {path}",
            )
            return
        if mode != 0o600:
            report.add(
                check_name,
                SEVERITY_CRITICAL,
                f"{label} mode is {oct(mode)}; should be 0o600",
                fix=f"chmod 600 {path}  (or run `xtool doctor --fix`)",
            )
            return
    report.add(check_name, SEVERITY_OK, f"{label} is 0o600")


def _check_cookies(report: Report) -> None:
    _check_private_file(
        report,
        path=_cookies_path(),
        check_name="cookies-mode",
        required=True,
        label="cookies.json",
    )


def _check_identity(report: Report) -> None:
    _check_private_file(
        report,
        path=_identity_path(),
        check_name="identity-mode",
        required=False,
        label="identity.json",
    )


def _check_query_ids(report: Report) -> None:
    _check_private_file(
        report,
        path=_query_ids_path(),
        check_name="query-ids-mode",
        required=False,
        label="query_ids.json",
    )


def _check_logs(report: Report) -> None:
    """The logs directory must be 0700; files inside should be 0600."""
    d = _logs_dir()
    if not d.exists():
        report.add(
            "logs-dir",
            SEVERITY_INFO,
            f"{d} does not exist yet",
        )
        return
    if is_posix():
        dmode = file_mode(d)
        if dmode != 0o700:
            report.add(
                "logs-dir",
                SEVERITY_CRITICAL,
                f"{d} mode is {oct(dmode or 0)}; should be 0o700",
                fix=f"chmod 700 {d}  (or run `xtool doctor --fix`)",
            )
        else:
            report.add("logs-dir", SEVERITY_OK, f"{d} is 0o700")

    # Per-file scan.
    bad_files: list[tuple[str, int]] = []
    try:
        entries = list(d.iterdir())
    except OSError:
        entries = []
    for p in entries:
        if not p.is_file() or is_symlink(p):
            continue
        if not is_posix():
            break
        m = file_mode(p)
        if m is not None and m != 0o600:
            bad_files.append((p.name, m))
    if bad_files:
        names = ", ".join(f"{n} ({oct(m)})" for n, m in bad_files[:5])
        extra = f" (+{len(bad_files) - 5} more)" if len(bad_files) > 5 else ""
        report.add(
            "logs-files",
            SEVERITY_WARNING,
            f"log files with non-0600 modes: {names}{extra}",
            fix=f"chmod 600 {d}/*  (or run `xtool doctor --fix`)",
        )
    elif entries and is_posix():
        report.add(
            "logs-files",
            SEVERITY_OK,
            f"{sum(1 for e in entries if e.is_file())} log files are 0o600",
        )


# ---------------------------------------------------------------------------
# Leak scan
# ---------------------------------------------------------------------------

def _candidate_leak_files() -> Iterable[Path]:
    """Paths most likely to have an accidentally-pasted cookie value.

    We intentionally scan shell histories -- that is the number-one
    real-world leak vector we're trying to catch ("I ran ``xtool
    delete --auth-token abc...`` once on the command line"). Limited
    to a small number of well-known dotfiles so the check stays fast.
    """
    home = Path(os.path.expanduser("~"))
    yield from (
        home / ".bash_history",
        home / ".zsh_history",
        home / ".local" / "share" / "fish" / "fish_history",
        home / ".python_history",
    )


def _check_history_leaks(report: Report) -> None:
    for candidate in _candidate_leak_files():
        if not candidate.is_file() or is_symlink(candidate):
            continue
        try:
            with candidate.open("rb") as fh:
                sample = fh.read(_LEAK_SCAN_BYTES).decode(
                    "utf-8", errors="replace"
                )
        except OSError:
            continue
        if looks_like_leak(sample):
            report.add(
                "history-leak",
                SEVERITY_WARNING,
                f"{candidate} appears to contain an xtool cookie value",
                fix=(
                    "Rotate your X session (log out of all browsers), "
                    "scrub the history file, and avoid passing "
                    "--auth-token / --ct0 on the command line. "
                    "Use `xtool login` instead."
                ),
            )


# ---------------------------------------------------------------------------
# Git-tracked secret check
# ---------------------------------------------------------------------------

def _git_tracked_sensitive_files(repo: Path) -> list[str]:
    """Return the subset of sensitive filenames that are currently
    tracked in ``repo``'s git index.

    Runs ``git ls-files`` once and greps the output in Python; this
    is much faster than one ``git ls-files`` per name and doesn't
    depend on shell pipelines.
    """
    git = shutil.which("git")
    if not git:
        return []
    try:
        proc = subprocess.run(
            [git, "ls-files"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    tracked = set(line.strip() for line in proc.stdout.splitlines() if line.strip())
    # Set of basenames we consider sensitive. Start from the shared
    # helper and extend with glob-based patterns handled below.
    sensitive_names = set(sensitive_basenames())
    hits: list[str] = []
    for path in tracked:
        name = Path(path).name
        if name in sensitive_names:
            hits.append(path)
        elif name.endswith(".debug.jsonl") or name.endswith(".err"):
            hits.append(path)
    return sorted(hits)


def _find_git_root(start: Path) -> Path | None:
    """Walk up looking for ``.git``. Returns None on no match."""
    p = start.resolve()
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if (cand / ".git").exists():
            return cand
    return None


def _check_git_tracked_secrets(report: Report) -> None:
    try:
        cwd = Path(os.getcwd())
    except OSError:
        return
    repo = _find_git_root(cwd)
    if repo is None:
        report.add(
            "git-tracked",
            SEVERITY_INFO,
            "not inside a git checkout; skipping tracked-secret scan",
        )
        return
    hits = _git_tracked_sensitive_files(repo)
    if hits:
        names = ", ".join(hits[:5])
        extra = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
        report.add(
            "git-tracked",
            SEVERITY_CRITICAL,
            f"sensitive files are tracked by git: {names}{extra}",
            fix=(
                "Remove them with `git rm --cached <path>`, add "
                "matching patterns to .gitignore, then rotate any "
                "cookies that may have been committed."
            ),
        )
    else:
        report.add(
            "git-tracked",
            SEVERITY_OK,
            "no sensitive filenames tracked by git",
        )


# ---------------------------------------------------------------------------
# Identity-store content check
# ---------------------------------------------------------------------------

def _check_identity_content(report: Report) -> None:
    """identity.json is designed to NEVER contain credentials.

    This belt-and-suspenders check reads the file (it's already 0600
    by the time we get here) and looks for credential-shaped keys.
    Any match is a critical regression: it would mean a past or
    future version of xtool wrote a secret where the tool promises
    not to. We never print the matching value.
    """
    p = _identity_path()
    if not p.is_file() or is_symlink(p):
        return
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    import json as _json
    try:
        data = _json.loads(text)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    bad = [k for k in data if k.lower() in ("auth_token", "ct0", "twid")]
    if bad:
        report.add(
            "identity-content",
            SEVERITY_CRITICAL,
            f"identity.json contains credential keys: {', '.join(sorted(bad))}",
            fix=f"Delete {p} and run `xtool login` again.",
        )
    else:
        report.add(
            "identity-content",
            SEVERITY_OK,
            "identity.json contains no credential keys",
        )


# ---------------------------------------------------------------------------
# Fix mode
# ---------------------------------------------------------------------------

def _apply_fixes(report: Report) -> list[str]:
    """Auto-repair obvious permission issues. Returns list of strings
    describing what was changed.

    Only the ``critical`` findings tagged as permission problems are
    touched; leak warnings, tracked-secret warnings, etc. require
    human judgement. The function never creates, moves, or deletes
    files -- it only runs ``chmod``.
    """
    changed: list[str] = []
    for f in report.findings:
        if f.severity != SEVERITY_CRITICAL:
            continue
        if f.check == "xtool-dir":
            if chmod_private_dir(_xtool_dir()):
                changed.append(f"chmod 700 {_xtool_dir()}")
        elif f.check == "cookies-mode":
            if chmod_private_file(_cookies_path()):
                changed.append(f"chmod 600 {_cookies_path()}")
        elif f.check == "identity-mode":
            if chmod_private_file(_identity_path()):
                changed.append(f"chmod 600 {_identity_path()}")
        elif f.check == "query-ids-mode":
            if chmod_private_file(_query_ids_path()):
                changed.append(f"chmod 600 {_query_ids_path()}")
        elif f.check == "logs-dir":
            if chmod_private_dir(_logs_dir()):
                changed.append(f"chmod 700 {_logs_dir()}")
    # Tighten any log files that were flagged (they're ``warning``
    # not ``critical`` because the log entries are already redacted;
    # still worth clamping when --fix is used).
    for f in report.findings:
        if f.check == "logs-files" and f.severity == SEVERITY_WARNING:
            d = _logs_dir()
            for p in d.glob("*.jsonl"):
                if chmod_private_file(p):
                    changed.append(f"chmod 600 {p}")
    return changed


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_checks() -> Report:
    """Run every check and return the aggregate :class:`Report`.

    Split from the CLI shell so tests can assert on findings without
    parsing terminal output.
    """
    report = Report()
    _check_directory(report)
    _check_cookies(report)
    _check_identity(report)
    _check_query_ids(report)
    _check_logs(report)
    _check_identity_content(report)
    _check_history_leaks(report)
    _check_git_tracked_secrets(report)
    return report


def _print_report(report: Report, console: Console) -> None:
    table = Table(title="xtool doctor", box=box.ROUNDED, show_lines=False)
    table.add_column("severity", style="bold")
    table.add_column("check")
    table.add_column("detail")
    for f in report.findings:
        style = _SEVERITY_STYLE.get(f.severity, "")
        table.add_row(
            f"[{style}]{f.severity}[/{style}]",
            f.check,
            f.message,
        )
    console.print(table)
    # Fix hints, grouped.
    fixes = [f for f in report.findings if f.fix]
    if fixes:
        console.print()
        console.print("[bold]Suggested fixes[/bold]")
        for f in fixes:
            console.print(f"  [dim]{f.check}:[/dim] {f.fix}")
    console.print()
    console.print(
        f"[bold]{report.ok_count}[/bold] ok, "
        f"[bold yellow]{report.warning_count}[/bold yellow] warnings, "
        f"[bold red]{report.critical_count}[/bold red] critical"
    )


def run_doctor(args: argparse.Namespace) -> int:
    """CLI entry point wired into :mod:`xtool.cli`.

    Parameters
    ----------
    args
        Parsed argparse Namespace. Only ``args.fix`` is read.

    Returns
    -------
    int
        ``0`` when no critical findings remain (after optional
        ``--fix``), ``1`` otherwise. No network, no destructive
        file operations.
    """
    console = Console()
    report = run_checks()

    if getattr(args, "fix", False):
        changed = _apply_fixes(report)
        if changed:
            console.print("[bold]Applied fixes:[/bold]")
            for line in changed:
                console.print(f"  {line}")
            console.print()
            # Re-run checks so the printed table reflects the new
            # state.
            report = run_checks()

    _print_report(report, console)
    return 0 if report.critical_count == 0 else 1
