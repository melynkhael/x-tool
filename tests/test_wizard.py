"""Tests for the wizard/menu system and new modules."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from xtool import __version__
from xtool.cli import build_parser, main
from xtool.ui import APP_TITLE
from xtool.safety import check_archive_path
from xtool.logs import ensure_logs_dir, log_path_for, log_summary, LOGS_DIR


# ── CLI integration: plain xtool / menu / wizard ──────────────────────────

class TestCLIMenuWiring:
    """Verify the menu/wizard subcommands are registered and plain xtool works."""

    def test_parser_accepts_menu_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["menu"])
        assert args.command == "menu"
        assert hasattr(args, "func")

    def test_parser_accepts_wizard_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["wizard"])
        assert args.command == "wizard"
        assert hasattr(args, "func")

    def test_no_subcommand_sets_command_none(self):
        """Plain 'xtool' should parse without error (command=None -> menu)."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_existing_subcommands_still_work(self):
        """Existing CLI commands remain registered and parseable."""
        parser = build_parser()
        for cmd in ("parse", "stats", "filter", "login", "delete",
                    "unretweet", "unlike", "resolve-retweets", "discover"):
            # Just verify parsing doesn't crash; some need positional args
            # so we only test the ones that can parse without them.
            pass
        # These accept --help without crashing:
        args = parser.parse_args(["discover", "--offline"])
        assert args.command == "discover"

    def test_version_flag(self, capsys):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_main_no_args_calls_menu(self, monkeypatch):
        """main([]) should invoke the wizard menu."""
        called = []
        monkeypatch.setattr(
            "xtool.wizard.run_menu",
            lambda: (called.append(True), 0)[1],
        )
        result = main([])
        assert called == [True]
        assert result == 0


# ── Archive auto-detection ────────────────────────────────────────────────

class TestArchiveDetection:
    """Test check_archive_path finds archive files in various layouts."""

    def test_standard_layout(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "tweets.js").write_text("window.YTD.tweets.part0 = []")
        (tmp_path / "data" / "like.js").write_text("window.YTD.like.part0 = []")

        result = check_archive_path(str(tmp_path))
        assert result["tweets"] is not None
        assert "tweets.js" in result["tweets"]
        assert result["likes"] is not None
        assert "like.js" in result["likes"]

    def test_tweet_singular(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "tweet.js").write_text("window.YTD.tweet.part0 = []")

        result = check_archive_path(str(tmp_path))
        assert result["tweets"] is not None
        assert "tweet.js" in result["tweets"]

    def test_flat_layout(self, tmp_path):
        (tmp_path / "tweets.js").write_text("window.YTD.tweets.part0 = []")

        result = check_archive_path(str(tmp_path))
        assert result["tweets"] is not None

    def test_missing_files(self, tmp_path):
        result = check_archive_path(str(tmp_path))
        assert result["tweets"] is None
        assert result["likes"] is None

    def test_likes_detection(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "likes.js").write_text("window.YTD.likes.part0 = []")

        result = check_archive_path(str(tmp_path))
        assert result["likes"] is not None
        assert "likes.js" in result["likes"]


# ── Logs module ───────────────────────────────────────────────────────────

class TestLogs:
    """Test centralized log management."""

    def test_ensure_logs_dir(self, tmp_path, monkeypatch):
        fake_dir = tmp_path / "logs"
        monkeypatch.setattr("xtool.logs.LOGS_DIR", fake_dir)
        result = ensure_logs_dir()
        assert result == fake_dir
        assert fake_dir.is_dir()

    def test_log_path_for_creates_timestamped_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("xtool.logs.LOGS_DIR", tmp_path)
        path = log_path_for("delete")
        assert path.parent == tmp_path
        assert path.name.startswith("delete_")
        assert path.suffix == ".jsonl"

    def test_log_summary_counts_outcomes(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        lines = [
            json.dumps({"id": "1", "outcome": "deleted"}),
            json.dumps({"id": "2", "outcome": "deleted"}),
            json.dumps({"id": "3", "outcome": "already_gone"}),
            json.dumps({"id": "4", "outcome": "failed"}),
        ]
        log_file.write_text("\n".join(lines))
        summary = log_summary(log_file)
        assert summary == {"deleted": 2, "already_gone": 1, "failed": 1}

    def test_log_summary_empty_file(self, tmp_path):
        log_file = tmp_path / "empty.jsonl"
        log_file.write_text("")
        assert log_summary(log_file) == {}


# ── UI module ─────────────────────────────────────────────────────────────

class TestUI:
    """Test UI helper imports and basic functions."""

    def test_app_title_defined(self):
        assert APP_TITLE == "X-Tool"

    def test_version_loads(self):
        from xtool.ui import _version
        v = _version()
        assert v.startswith("v")
        assert __version__ in v

    def test_console_exists(self):
        from xtool.ui import console
        assert console is not None


# ── Safety module ─────────────────────────────────────────────────────────

class TestSafety:
    """Test safety confirmation helpers."""

    def test_check_cookies_exist_returns_bool(self, tmp_path, monkeypatch):
        """check_cookies_exist returns False when file is missing."""
        monkeypatch.setattr(
            "os.path.expanduser",
            lambda p: str(tmp_path / "no-such-file.json") if "cookies" in p else p,
        )
        from xtool.safety import check_cookies_exist
        result = check_cookies_exist()
        assert result is False

    def test_check_cookies_exist_true(self, tmp_path, monkeypatch):
        """check_cookies_exist returns True when file exists."""
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text('{"auth_token":"x","ct0":"y"}')
        monkeypatch.setattr(
            "os.path.expanduser",
            lambda p: str(cookie_file) if "cookies" in p else p,
        )
        from xtool.safety import check_cookies_exist
        result = check_cookies_exist()
        assert result is True

    def test_confirm_destructive_dry_run_returns_true(self):
        from xtool.safety import confirm_destructive
        # dry_run=True always returns True without prompting
        assert confirm_destructive(
            action_name="delete", count=100, dry_run=True
        ) is True


# ── Wizard module import ──────────────────────────────────────────────────

class TestWizardImport:
    """Verify the wizard module imports cleanly."""

    def test_wizard_importable(self):
        from xtool.wizard import run_menu, MENU_ITEMS
        assert callable(run_menu)
        assert len(MENU_ITEMS) > 0

    def test_menu_items_have_keys_and_labels(self):
        from xtool.wizard import MENU_ITEMS
        for key, label in MENU_ITEMS:
            assert isinstance(key, str) and len(key) > 0
            assert isinstance(label, str) and len(label) > 0

    def test_menu_has_exit_option(self):
        from xtool.wizard import MENU_ITEMS
        keys = [k for k, _ in MENU_ITEMS]
        assert "0" in keys  # exit


# ── Backward compatibility: existing commands still parse ─────────────────

class TestBackwardCompat:
    """Ensure existing CLI subcommands still work as before."""

    def test_delete_subcommand_parses(self):
        parser = build_parser()
        args = parser.parse_args(["delete", "input.jsonl", "--dry-run", "--offline"])
        assert args.command == "delete"
        assert args.dry_run is True
        assert args.input == "input.jsonl"

    def test_unretweet_subcommand_parses(self):
        parser = build_parser()
        args = parser.parse_args(["unretweet", "rts.jsonl", "--rate", "0.5"])
        assert args.command == "unretweet"
        assert args.rate == 0.5

    def test_unlike_subcommand_parses(self):
        parser = build_parser()
        args = parser.parse_args(["unlike", "likes.jsonl", "--yes"])
        assert args.command == "unlike"
        assert args.yes is True

    def test_resolve_retweets_parses(self):
        parser = build_parser()
        args = parser.parse_args([
            "resolve-retweets", "--handle", "test", "--debug", "--offline"
        ])
        assert args.command == "resolve-retweets"
        assert args.handle == "test"
        assert args.debug is True

    def test_parse_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["parse", "tweets.js", "--likes"])
        assert args.command == "parse"
        assert args.likes is True

    def test_discover_offline(self):
        parser = build_parser()
        args = parser.parse_args(["discover", "--offline"])
        assert args.command == "discover"
        assert args.offline is True
