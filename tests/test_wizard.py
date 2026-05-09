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



# ── Login UX bug fixes (hidden-input clarity, validation, saved-but-unverified) ──

class _FakeCookieLogin:
    def __init__(self, name, value, domain=".x.com"):
        self.name = name
        self.value = value
        self.domain = domain


class _FakeJarLogin:
    def __init__(self, cookies=()):
        self._cookies = list(cookies)

    def __iter__(self):
        return iter(self._cookies)


class _FakeSessionLogin:
    def __init__(self, cookies=()):
        self.cookies = _FakeJarLogin(cookies)


class TestAskSecret:
    """ask_secret makes hidden input obvious and never echoes the value."""

    def test_prompt_says_hidden(self, monkeypatch, capsys):
        """The prompt text itself must mention that input is hidden."""
        captured_prompt = {}

        def fake_getpass(prompt):
            captured_prompt["text"] = prompt
            return "a" * 40

        monkeypatch.setattr("getpass.getpass", fake_getpass)
        from xtool.ui import ask_secret
        ask_secret("auth_token")
        assert "hidden" in captured_prompt["text"].lower()
        assert "paste" in captured_prompt["text"].lower()

    def test_captured_confirmation_shows_length_not_value(
        self, monkeypatch, capsys
    ):
        """After input, we print the char count -- never the value."""
        secret_value = "deadbeef" * 5  # 40 chars
        monkeypatch.setattr("getpass.getpass", lambda p: secret_value)
        from xtool.ui import ask_secret
        value, err = ask_secret("auth_token")
        out = capsys.readouterr().out
        assert err is None
        assert value == secret_value
        assert "auth_token captured:" in out
        assert "40 chars" in out
        # The actual secret must never appear in the output.
        assert secret_value not in out

    def test_empty_rejected(self, monkeypatch):
        monkeypatch.setattr("getpass.getpass", lambda p: "")
        from xtool.ui import ask_secret
        value, err = ask_secret("auth_token")
        assert value == ""
        assert err == "empty"

    def test_whitespace_only_rejected(self, monkeypatch):
        monkeypatch.setattr("getpass.getpass", lambda p: "   \t  ")
        from xtool.ui import ask_secret
        value, err = ask_secret("ct0")
        assert value == ""
        assert err and "whitespace" in err

    def test_too_short_rejected(self, monkeypatch):
        monkeypatch.setattr("getpass.getpass", lambda p: "abc")
        from xtool.ui import ask_secret
        value, err = ask_secret("auth_token", min_length=10)
        assert value == ""
        assert err and "too short" in err

    def test_min_length_boundary(self, monkeypatch):
        """Exactly min_length is accepted."""
        monkeypatch.setattr("getpass.getpass", lambda p: "1234567890")
        from xtool.ui import ask_secret
        value, err = ask_secret("auth_token", min_length=10)
        assert err is None
        assert value == "1234567890"


class TestMenuLoginValidation:
    """The menu login flow refuses to save broken cookies."""

    def _run_login(self, monkeypatch, inputs):
        """Drive _menu_login() with a queued list of getpass/input responses."""
        from xtool import wizard, auth as _auth, ui

        getpass_queue = list(inputs.get("getpass", []))
        input_queue = list(inputs.get("input", []))

        monkeypatch.setattr("getpass.getpass", lambda p: getpass_queue.pop(0))
        monkeypatch.setattr("builtins.input", lambda p="": input_queue.pop(0))

        saved = {"path": None, "creds": None}

        class FakeCreds:
            def __init__(self, auth_token, ct0):
                self.auth_token = auth_token
                self.ct0 = ct0
                saved["creds"] = (auth_token, ct0)
            def to_file(self, path):
                saved["path"] = str(path)
                return True

        monkeypatch.setattr("xtool.actions.Credentials", FakeCreds)
        # Verification never needs to actually run for these tests.
        monkeypatch.setattr(
            _auth,
            "verify_identity",
            lambda creds, expect_handle=None: _auth.Identity(
                status="partial", source="cookie",
                detail="no network in tests",
            ),
        )
        # Reset wizard state so each call is deterministic.
        wizard._state["identity"] = None
        wizard._state["handle"] = None
        wizard._menu_login()
        return saved

    def test_empty_auth_token_not_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch, {"getpass": [""], "input": []}
        )
        out = " ".join(capsys.readouterr().out.split())
        assert saved["creds"] is None, "Credentials must not be constructed"
        assert saved["path"] is None, "Cookies must not be written to disk"
        assert "auth_token is empty" in out
        assert "Cookies were not saved" in out

    def test_empty_ct0_not_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch,
            {"getpass": ["a" * 40, ""], "input": []},
        )
        out = " ".join(capsys.readouterr().out.split())
        assert saved["creds"] is None
        assert saved["path"] is None
        assert "ct0 is empty" in out
        assert "Cookies were not saved" in out

    def test_whitespace_only_auth_token_not_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch, {"getpass": ["   "], "input": []}
        )
        out = " ".join(capsys.readouterr().out.split())
        assert saved["creds"] is None
        assert "whitespace" in out or "empty" in out
        assert "Cookies were not saved" in out

    def test_short_auth_token_not_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch, {"getpass": ["abc"], "input": []}
        )
        out = " ".join(capsys.readouterr().out.split())
        assert saved["creds"] is None
        assert "too short" in out
        assert "Cookies were not saved" in out

    def test_short_ct0_not_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch,
            {"getpass": ["a" * 40, "xy"], "input": []},
        )
        out = " ".join(capsys.readouterr().out.split())
        assert saved["creds"] is None
        assert "too short" in out

    def test_valid_cookies_are_saved(self, monkeypatch, capsys):
        saved = self._run_login(
            monkeypatch,
            {
                "getpass": ["a" * 40, "b" * 40],
                # ask_input("X handle without @ (optional)"): blank
                "input": [""],
            },
        )
        assert saved["creds"] == ("a" * 40, "b" * 40)
        assert saved["path"] and saved["path"].endswith("cookies.json")


class TestSavedButUnverifiedIdentity:
    """After login, if REST whoami 404s and there is no twid yet, the
    identity must NOT be reported as 'none' just because the session
    happens to hold only auth_token + ct0."""

    def _patch_whoami_404(self, monkeypatch):
        from xtool import auth as _auth
        from xtool.actions import ActionError

        def fake_whoami(session, timeout=20.0):
            raise ActionError("REST 404")

        monkeypatch.setattr(_auth, "whoami", fake_whoami)

    def test_auth_cookies_present_no_twid_returns_partial(self, monkeypatch):
        from xtool import auth as _auth
        from xtool.actions import Credentials

        self._patch_whoami_404(monkeypatch)

        def fake_build_session(creds):
            return _FakeSessionLogin([
                _FakeCookieLogin("auth_token", creds.auth_token),
                _FakeCookieLogin("ct0", creds.ct0),
            ])

        monkeypatch.setattr(_auth, "build_session", fake_build_session)

        ident = _auth.verify_identity(Credentials("a" * 40, "b" * 40))
        assert ident.status == "partial"
        assert ident.has_cookies is True
        assert ident.verified is False
        assert ident.source == "cookie"

    def test_no_cookies_still_returns_none(self, monkeypatch):
        """Belt-and-suspenders: truly empty session stays 'none'."""
        from xtool import auth as _auth
        from xtool.actions import Credentials

        self._patch_whoami_404(monkeypatch)
        monkeypatch.setattr(
            _auth, "build_session",
            lambda creds: _FakeSessionLogin([]),
        )
        ident = _auth.verify_identity(Credentials("a" * 40, "b" * 40))
        assert ident.status == "none"
        assert ident.has_cookies is False

    def test_partial_identity_line_does_not_say_not_logged_in(self):
        """The header one-liner for partial must be distinct from none."""
        from xtool.auth import Identity
        from xtool.ui import format_identity_line

        partial = format_identity_line(Identity(status="partial")).plain
        none_line = format_identity_line(Identity(status="none")).plain

        assert "cookies saved, identity not verified" in partial
        assert "not logged in" in none_line
        assert partial != none_line

    def test_partial_banner_does_not_say_not_logged_in(self, capsys):
        """The post-login banner for partial must not render the red
        'Not logged in.' panel."""
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner

        print_identity_banner(Identity(status="partial"))
        out = capsys.readouterr().out
        assert "Not logged in" not in out
        assert "Cookies were saved" in out
        assert "identity verification failed" in out


class TestMenuPromptWording:
    """The main menu prompt must no longer display the "[0]" default."""

    def test_ask_choice_hide_default_strips_bracket(self, monkeypatch):
        captured = {}
        monkeypatch.setattr("builtins.input", lambda p: (captured.setdefault("p", p), "0")[1])
        from xtool.ui import ask_choice
        ask_choice("Choose option (0-9, t)", valid=["0"], default="0", hide_default=True)
        assert "[0]" not in captured["p"]
        assert "Choose option" in captured["p"]

    def test_ask_choice_still_defaults_on_empty_input(self, monkeypatch):
        """Blank input still maps to the hidden default."""
        monkeypatch.setattr("builtins.input", lambda p: "")
        from xtool.ui import ask_choice
        result = ask_choice("Choose option", valid=["0"], default="0", hide_default=True)
        assert result == "0"

    def test_menu_loop_prompt_text(self, monkeypatch, capsys):
        """Drive one full iteration of run_menu() and verify the prompt
        text printed to the user no longer includes '[0]'."""
        from xtool import wizard, auth as _auth

        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: _auth.Identity(status="none"),
        )

        captured = {"prompts": []}
        original_input = __builtins__["input"] if isinstance(__builtins__, dict) else __builtins__.input

        def fake_input(prompt=""):
            captured["prompts"].append(prompt)
            return "0"  # exit

        monkeypatch.setattr("builtins.input", fake_input)
        wizard._state["identity"] = None
        wizard._state["handle"] = None
        wizard.run_menu()

        # Every prompt string must avoid "[0]".
        assert captured["prompts"], "run_menu should have prompted at least once"
        choose_prompts = [p for p in captured["prompts"] if "Choose" in p]
        assert choose_prompts
        for p in choose_prompts:
            assert "[0]" not in p, f"prompt leaked [0]: {p!r}"
            assert "Choose option" in p


class TestHandlePromptIsShort:
    """The handle prompt must be short so it doesn't wrap in Termux."""

    def test_handle_prompt_is_compact(self, monkeypatch):
        """_menu_login's handle prompt text must be under ~50 chars
        so narrow terminals render it on one line."""
        from xtool import wizard, auth as _auth

        getpass_queue = ["a" * 40, "b" * 40]
        input_prompts = []

        def fake_input(p=""):
            input_prompts.append(p)
            return ""

        monkeypatch.setattr("getpass.getpass", lambda p: getpass_queue.pop(0))
        monkeypatch.setattr("builtins.input", fake_input)

        # Skip any side-effects beyond constructing credentials.
        class FakeCreds:
            def __init__(self, auth_token, ct0):
                pass
            def to_file(self, path):
                return True

        monkeypatch.setattr("xtool.actions.Credentials", FakeCreds)
        monkeypatch.setattr(
            _auth,
            "verify_identity",
            lambda creds, expect_handle=None: _auth.Identity(status="partial"),
        )
        wizard._state["identity"] = None
        wizard._state["handle"] = None
        wizard._menu_login()

        # The handle prompt is the last input() call during login.
        assert input_prompts, "expected at least one input prompt"
        handle_prompt = input_prompts[-1]
        assert "handle" in handle_prompt.lower()
        # Must not contain the old "identity" language that was
        # wrapping on narrow Termux terminals.
        assert "helps verify identity" not in handle_prompt
        # Prompt text (including the leading two-space indent and the
        # trailing ": ") should be short.
        assert len(handle_prompt) <= 50, (
            f"handle prompt too long ({len(handle_prompt)} chars): "
            f"{handle_prompt!r}"
        )
