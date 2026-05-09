"""Centralized log management for xtool.

All operation logs are stored in ~/.xtool/logs/ with timestamped filenames.
This module provides helpers to create log paths, list recent logs, and
manage the log directory.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


LOGS_DIR = Path(os.path.expanduser("~/.xtool/logs"))


def ensure_logs_dir() -> Path:
    """Create the logs directory if it doesn't exist. Returns the path."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR


def log_path_for(operation: str, *, suffix: str = ".jsonl") -> Path:
    """Generate a timestamped log file path for an operation.

    Example: ~/.xtool/logs/delete_20260509_143022.jsonl
    """
    ensure_logs_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    return LOGS_DIR / f"{operation}_{ts}{suffix}"


def latest_log(operation: str | None = None) -> Path | None:
    """Return the most recent log file, optionally filtered by operation prefix."""
    if not LOGS_DIR.exists():
        return None
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if operation:
        logs = [p for p in logs if p.name.startswith(operation)]
    return logs[0] if logs else None


def list_logs(limit: int = 20) -> list[Path]:
    """Return recent log files sorted newest first."""
    if not LOGS_DIR.exists():
        return []
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
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
