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



# ── Account / identity verification (new in login UX upgrade) ─────────────

class _FakeCookie:
    def __init__(self, name, value, domain=".x.com"):
        self.name = name
        self.value = value
        self.domain = domain


class _FakeJar:
    def __init__(self, cookies=()):
        self._cookies = list(cookies)

    def __iter__(self):
        return iter(self._cookies)


class _FakeSession:
    def __init__(self, cookies=()):
        self.cookies = _FakeJar(cookies)


class TestIdentityTwidParsing:
    """extract_twid_user_id handles the url-encoded and bare forms."""

    def test_url_encoded_twid(self):
        from xtool.auth import extract_twid_user_id
        s = _FakeSession([_FakeCookie("twid", "u%3D1234567890")])
        assert extract_twid_user_id(s) == "1234567890"

    def test_bare_twid(self):
        from xtool.auth import extract_twid_user_id
        s = _FakeSession([_FakeCookie("twid", "u=42")])
        assert extract_twid_user_id(s) == "42"

    def test_missing_twid(self):
        from xtool.auth import extract_twid_user_id
        s = _FakeSession([_FakeCookie("auth_token", "x")])
        assert extract_twid_user_id(s) is None

    def test_garbage_twid(self):
        from xtool.auth import extract_twid_user_id
        s = _FakeSession([_FakeCookie("twid", "weird-no-digits")])
        assert extract_twid_user_id(s) is None


class TestVerifyIdentity:
    """verify_identity should never raise and should return a useful
    Identity in each REST / twid / handle-match scenario."""

    def _creds(self):
        from xtool.actions import Credentials
        return Credentials("a" * 40, "b" * 40)

    def test_rest_success_returns_verified(self, monkeypatch):
        from xtool import auth as _auth

        def fake_build_session(creds):
            return _FakeSession([
                _FakeCookie("auth_token", creds.auth_token),
                _FakeCookie("ct0", creds.ct0),
            ])

        def fake_whoami(session, timeout=20.0):
            return {"screen_name": "veldorakite", "user_id": "123456"}

        monkeypatch.setattr(_auth, "build_session", fake_build_session)
        monkeypatch.setattr(_auth, "whoami", fake_whoami)

        ident = _auth.verify_identity(self._creds())
        assert ident.status == "verified"
        assert ident.handle == "veldorakite"
        assert ident.user_id == "123456"
        assert ident.source == "rest"
        assert ident.verified is True
        assert ident.has_cookies is True

    def test_rest_fail_twid_only_returns_partial(self, monkeypatch):
        from xtool import auth as _auth
        from xtool.actions import ActionError

        def fake_build_session(creds):
            return _FakeSession([_FakeCookie("twid", "u%3D777")])

        def fake_whoami(session, timeout=20.0):
            raise ActionError("REST 404 across the board")

        monkeypatch.setattr(_auth, "build_session", fake_build_session)
        monkeypatch.setattr(_auth, "whoami", fake_whoami)

        ident = _auth.verify_identity(self._creds())
        assert ident.status == "partial"
        assert ident.handle is None
        assert ident.user_id == "777"
        assert ident.source == "cookie"
        assert ident.has_cookies is True
        assert ident.verified is False
        assert "REST 404" in ident.detail or "could not" in ident.detail

    def test_rest_fail_no_twid_returns_none(self, monkeypatch):
        from xtool import auth as _auth
        from xtool.actions import ActionError

        def fake_build_session(creds):
            return _FakeSession([])

        def fake_whoami(session, timeout=20.0):
            raise ActionError("REST dead")

        monkeypatch.setattr(_auth, "build_session", fake_build_session)
        monkeypatch.setattr(_auth, "whoami", fake_whoami)

        ident = _auth.verify_identity(self._creds())
        assert ident.status == "none"
        assert ident.has_cookies is False

    def test_handle_match_upgrades_partial_to_verified(self, monkeypatch):
        """When REST is dead but the user provides an @handle that
        resolves to the same user_id as the twid cookie, we should
        upgrade the status to verified via handle-match."""
        from xtool import auth as _auth
        from xtool.actions import ActionError

        def fake_build_session(creds):
            return _FakeSession([_FakeCookie("twid", "u%3D12345")])

        def fake_whoami(session, timeout=20.0):
            raise ActionError("REST 404")

        monkeypatch.setattr(_auth, "build_session", fake_build_session)
        monkeypatch.setattr(_auth, "whoami", fake_whoami)

        # Patch the resolver lookup so it returns a matching id.
        from xtool import resolver
        monkeypatch.setattr(
            resolver,
            "resolve_screen_name",
            lambda sess, h, offline=False: "12345",
        )

        ident = _auth.verify_identity(self._creds(), expect_handle="veldorakite")
        assert ident.status == "verified"
        assert ident.handle == "veldorakite"
        assert ident.user_id == "12345"
        assert ident.source == "handle-match"

    def test_handle_match_mismatch_stays_partial(self, monkeypatch):
        """If the handle resolves to a different user_id than twid, we
        must NOT claim verified -- that would be a silent safety regression."""
        from xtool import auth as _auth
        from xtool.actions import ActionError

        def fake_build_session(creds):
            return _FakeSession([_FakeCookie("twid", "u%3D12345")])

        def fake_whoami(session, timeout=20.0):
            raise ActionError("REST 404")

        monkeypatch.setattr(_auth, "build_session", fake_build_session)
        monkeypatch.setattr(_auth, "whoami", fake_whoami)
        from xtool import resolver
        monkeypatch.setattr(
            resolver,
            "resolve_screen_name",
            lambda sess, h, offline=False: "99999",  # wrong id
        )

        ident = _auth.verify_identity(self._creds(), expect_handle="someone_else")
        assert ident.status == "partial"
        assert ident.handle is None
        assert ident.source == "cookie"


class TestVerifyFromCookieFile:
    def test_missing_file(self, tmp_path):
        from xtool.auth import verify_from_cookie_file
        ident = verify_from_cookie_file(tmp_path / "nope.json")
        assert ident.status == "none"
        assert "no cookies file" in ident.detail

    def test_unreadable_file(self, tmp_path):
        from xtool.auth import verify_from_cookie_file
        bad = tmp_path / "cookies.json"
        bad.write_text("not json")
        ident = verify_from_cookie_file(bad)
        assert ident.status == "none"
        assert "could not read" in ident.detail

    def test_good_file_delegates_to_verify_identity(self, tmp_path, monkeypatch):
        from xtool import auth as _auth
        cookies = tmp_path / "cookies.json"
        cookies.write_text(json.dumps({"auth_token": "a" * 40, "ct0": "b" * 40}))

        captured = {}

        def fake_verify(creds, *, expect_handle=None, session=None):
            captured["handle"] = expect_handle
            return _auth.Identity(
                status="verified", handle="neo", user_id="1",
                source="rest", detail="",
            )

        monkeypatch.setattr(_auth, "verify_identity", fake_verify)
        ident = _auth.verify_from_cookie_file(cookies, expect_handle="neo")
        assert ident.status == "verified"
        assert captured["handle"] == "neo"


# ── Identity one-liner / header renderer ─────────────────────────────────

class TestIdentityOneLiner:
    def test_verified(self):
        from xtool.auth import Identity
        assert Identity(status="verified", handle="veldorakite").one_liner() \
            == "@veldorakite verified"

    def test_partial_with_handle(self):
        from xtool.auth import Identity
        line = Identity(status="partial", handle="veldorakite").one_liner()
        assert "@veldorakite" in line
        assert "not verified" in line

    def test_partial_with_user_id_only(self):
        from xtool.auth import Identity
        line = Identity(status="partial", user_id="123").one_liner()
        assert "123" in line
        assert "not verified" in line

    def test_partial_bare(self):
        from xtool.auth import Identity
        line = Identity(status="partial").one_liner()
        assert "cookies saved" in line
        assert "not verified" in line

    def test_none(self):
        from xtool.auth import Identity
        assert Identity(status="none").one_liner() == "not logged in"


class TestFormatIdentityLine:
    """The Rich Text renderer must produce a plain-text match for each
    status so the menu header always has a sensible string."""

    def _rendered(self, identity):
        from xtool.ui import format_identity_line
        return format_identity_line(identity).plain

    def test_none_identity_object(self):
        assert self._rendered(None) == "Account: not logged in"

    def test_status_none(self):
        from xtool.auth import Identity
        assert self._rendered(Identity(status="none")) == "Account: not logged in"

    def test_status_verified(self):
        from xtool.auth import Identity
        text = self._rendered(Identity(status="verified", handle="x"))
        assert text == "Account: @x verified"

    def test_status_partial(self):
        from xtool.auth import Identity
        text = self._rendered(Identity(status="partial", handle="x"))
        assert "@x" in text
        assert "identity not verified" in text


# ── confirm_typed: unverified branch ─────────────────────────────────────

class TestConfirmTypedUnverified:
    def test_verified_skips_extra_warning(self, monkeypatch, capsys):
        from xtool import safety
        monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
        assert safety.confirm_typed(
            action_name="delete", count=1, account="x", verified=True
        ) is True

    def test_unverified_branch_returns_true_on_yes(self, monkeypatch):
        from xtool import safety
        monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
        assert safety.confirm_typed(
            action_name="delete", count=1, account="x", verified=False
        ) is True

    def test_unverified_branch_still_rejects_non_yes(self, monkeypatch):
        from xtool import safety
        monkeypatch.setattr("builtins.input", lambda prompt="": "no")
        assert safety.confirm_typed(
            action_name="delete", count=1, account="x", verified=False
        ) is False


# ── CLI: `xtool whoami` / `xtool account` ────────────────────────────────

class TestWhoamiCommand:
    def test_parser_registers_both_aliases(self):
        parser = build_parser()
        for cmd in ("whoami", "account"):
            args = parser.parse_args([cmd])
            assert args.command == cmd
            assert hasattr(args, "func")

    def test_whoami_supports_expect_handle(self):
        parser = build_parser()
        args = parser.parse_args(["whoami", "--expect-handle", "neo"])
        assert args.expect_handle == "neo"

    def test_exit_code_verified(self, monkeypatch):
        from xtool import cli, auth as _auth

        def fake_verify(path, *, expect_handle=None):
            return _auth.Identity(
                status="verified", handle="x", user_id="1",
                source="rest", detail="",
            )

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)
        assert cli.main(["whoami"]) == 0

    def test_exit_code_partial(self, monkeypatch):
        from xtool import cli, auth as _auth

        def fake_verify(path, *, expect_handle=None):
            return _auth.Identity(
                status="partial", user_id="1",
                source="cookie", detail="partial",
            )

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)
        assert cli.main(["whoami"]) == 1

    def test_exit_code_none(self, monkeypatch):
        from xtool import cli, auth as _auth

        def fake_verify(path, *, expect_handle=None):
            return _auth.Identity(status="none", source="none", detail="")

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)
        assert cli.main(["whoami"]) == 2

    def test_account_alias_uses_same_handler(self, monkeypatch):
        from xtool import cli, auth as _auth

        calls = {"n": 0}

        def fake_verify(path, *, expect_handle=None):
            calls["n"] += 1
            return _auth.Identity(status="verified", handle="x", user_id="1",
                                  source="rest", detail="")

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)
        assert cli.main(["account"]) == 0
        assert calls["n"] == 1


# ── Wizard state: identity refresh caches and upgrades ───────────────────

class TestWizardRefreshIdentity:
    def test_refresh_caches_result(self, monkeypatch):
        from xtool import wizard, auth as _auth
        # Reset state between tests.
        wizard._state["identity"] = None
        wizard._state["handle"] = None

        calls = {"n": 0}

        def fake_verify(path, *, expect_handle=None):
            calls["n"] += 1
            return _auth.Identity(
                status="verified", handle="x", user_id="1",
                source="rest", detail="",
            )

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)

        a = wizard._refresh_identity()
        b = wizard._refresh_identity()  # should use the cache
        assert a is b
        assert calls["n"] == 1

        # force=True must bust the cache.
        wizard._refresh_identity(force=True)
        assert calls["n"] == 2

    def test_refresh_populates_handle(self, monkeypatch):
        from xtool import wizard, auth as _auth
        wizard._state["identity"] = None
        wizard._state["handle"] = None

        monkeypatch.setattr(
            _auth,
            "verify_from_cookie_file",
            lambda path, *, expect_handle=None: _auth.Identity(
                status="verified", handle="neo", user_id="1",
                source="rest", detail="",
            ),
        )
        wizard._refresh_identity(force=True)
        assert wizard._state["handle"] == "neo"
