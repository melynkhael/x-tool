"""Tests for the v0.2.5 security / privacy audit.

One test class per audit finding listed in the v0.2.5 CHANGELOG.
The file is organised so a reviewer can jump from a CHANGELOG bullet
directly to the tests that cover it:

* Cookie file permission race            -> TestCookieFileWriteIsSafe
* ~/.xtool/ directory mode               -> TestXtoolDirectoryIsPrivate
* Sensitive file modes                   -> TestSensitiveFilesAre0600
* Log redaction                          -> TestLogRedaction
* whoami() error hint user-id leak       -> TestWhoamiErrorHintIsScrubbed
* Debug dump permissions + redaction     -> TestDebugDumpIsSafe
* Symlink / path traversal               -> TestSymlinkSafety
* Shell-history warning                  -> TestShellHistoryWarning
* `xtool doctor` command                 -> TestDoctorCommand
* .gitignore coverage                    -> TestGitignoreCoverage
* Version + changelog                    -> TestVersionBumpTo025

Every test either uses the real POSIX stat-mode surface or skips on
non-POSIX platforms -- we want this suite to stay green on a macOS
developer machine and inside a Termux environment.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# A representative numeric user id used as a canary. If any test
# output contains this exact string the assertion fails, same as in
# the privacy-polish suite.
_SENSITIVE_USER_ID = "1816262302209085440"

# Fake but plausible credential values. Using "AT" / "CT" prefixes so
# grep'ing the tree for real secrets never false-positives on these.
_FAKE_AUTH_TOKEN = "AT" + "a" * 38  # 40 chars, like the real thing
_FAKE_CT0 = "CT" + "b" * 38


requires_posix = pytest.mark.skipif(
    os.name != "posix", reason="POSIX-only check"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


@pytest.fixture
def isolated_xtool_home(tmp_path, monkeypatch):
    """Point every ``~/.xtool`` consumer at a temp directory.

    This patches the module-level path constants that otherwise
    resolve against the real user home. Tests that only want the
    safe_io helpers operate on ``tmp_path`` directly; tests that
    exercise the CLI / doctor / logs modules want them scoped to a
    sandbox.
    """
    home = tmp_path / "home"
    (home / ".xtool").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    # Patch well-known module constants that captured the path at
    # import time (os.path.expanduser was already evaluated).
    from xtool import cli as _cli
    from xtool import wizard as _wizard
    from xtool import logs as _logs
    from xtool import discovery as _discovery
    from xtool import identity_store as _ids
    from xtool import doctor as _doctor
    monkeypatch.setattr(
        _cli, "COOKIES_PATH", home / ".xtool" / "cookies.json"
    )
    monkeypatch.setattr(
        _wizard, "COOKIES_PATH", home / ".xtool" / "cookies.json"
    )
    monkeypatch.setattr(
        _logs, "LOGS_DIR", home / ".xtool" / "logs"
    )
    monkeypatch.setattr(
        _discovery, "CACHE_PATH", home / ".xtool" / "query_ids.json"
    )
    monkeypatch.setattr(
        _ids, "DEFAULT_PATH", home / ".xtool" / "identity.json"
    )
    # doctor.py reads paths via functions, so we patch os.path.expanduser
    # for that module's lookups too.
    monkeypatch.setattr(
        _doctor.os.path, "expanduser",
        lambda s: s.replace("~", str(home))
    )
    return home / ".xtool"


# ---------------------------------------------------------------------------
# Cookie file permission race
# ---------------------------------------------------------------------------

class TestCookieFileWriteIsSafe:
    """`Credentials.to_file()` must write cookies.json atomically with
    mode 0600 from the first byte. The v0.2.4 code first wrote under
    umask and then chmodded; the race window is closed in v0.2.5."""

    @requires_posix
    def test_new_file_is_0600(self, tmp_path):
        from xtool.actions import Credentials
        p = tmp_path / "sub" / "cookies.json"
        ok = Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        assert ok is True
        assert _mode(p) == 0o600

    @requires_posix
    def test_parent_directory_is_0700(self, tmp_path):
        from xtool.actions import Credentials
        p = tmp_path / "newdir" / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        assert _mode(p.parent) == 0o700

    @requires_posix
    def test_overwrite_existing_keeps_0600(self, tmp_path):
        from xtool.actions import Credentials
        p = tmp_path / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        # Loosen mode to simulate a pre-v0.2.5 install.
        os.chmod(p, 0o644)
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0, twid="u=123456789012345").to_file(p)
        assert _mode(p) == 0o600

    def test_write_is_atomic_no_tempfile_left_behind(self, tmp_path):
        """After to_file returns, no lingering .tmp sibling should be
        present. The mkstemp-based helper must clean up regardless of
        success path."""
        from xtool.actions import Credentials
        p = tmp_path / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        leftovers = [
            x for x in tmp_path.iterdir() if x.name.startswith("cookies.json.")
        ]
        assert leftovers == []


# ---------------------------------------------------------------------------
# ~/.xtool directory permissions
# ---------------------------------------------------------------------------

class TestXtoolDirectoryIsPrivate:
    """Every helper that writes under ``~/.xtool/`` should ensure the
    directory exists and is 0700."""

    @requires_posix
    def test_ensure_private_dir_creates_with_0700(self, tmp_path):
        from xtool._safe_io import ensure_private_dir
        d = tmp_path / "x"
        ensure_private_dir(d)
        assert _mode(d) == 0o700

    @requires_posix
    def test_ensure_private_dir_tightens_existing(self, tmp_path):
        from xtool._safe_io import ensure_private_dir
        d = tmp_path / "x"
        d.mkdir(mode=0o755)
        ensure_private_dir(d)
        assert _mode(d) == 0o700

    @requires_posix
    def test_identity_save_tightens_parent(self, tmp_path):
        """identity_store.save should 0700 its parent directory."""
        from xtool import identity_store
        parent = tmp_path / "xtool"
        parent.mkdir(mode=0o755)
        path = parent / "identity.json"
        r = identity_store.IdentityRecord(expected_handle="veldorakite")
        identity_store.save(r, path=path)
        assert _mode(parent) == 0o700

    @requires_posix
    def test_logs_dir_is_0700(self, tmp_path, monkeypatch):
        from xtool import logs as logs_mod
        d = tmp_path / "logs"
        monkeypatch.setattr(logs_mod, "LOGS_DIR", d)
        logs_mod.ensure_logs_dir()
        assert _mode(d) == 0o700


# ---------------------------------------------------------------------------
# Sensitive file modes
# ---------------------------------------------------------------------------

class TestSensitiveFilesAre0600:
    @requires_posix
    def test_identity_save_creates_0600(self, tmp_path):
        from xtool import identity_store
        p = tmp_path / "identity.json"
        identity_store.save(
            identity_store.IdentityRecord(expected_handle="v"), path=p
        )
        assert _mode(p) == 0o600

    @requires_posix
    def test_query_ids_cache_is_0600(self, tmp_path, monkeypatch):
        from xtool import discovery
        p = tmp_path / "query_ids.json"
        monkeypatch.setattr(discovery, "CACHE_PATH", p)
        discovery._save_cache({"fetched_at": 0.0, "ids": {"DeleteTweet": "x"}})
        assert _mode(p) == 0o600

    @requires_posix
    def test_log_path_for_creates_0600(self, tmp_path, monkeypatch):
        from xtool import logs as logs_mod
        monkeypatch.setattr(logs_mod, "LOGS_DIR", tmp_path / "logs")
        p = logs_mod.log_path_for("delete")
        assert p.exists()
        assert _mode(p) == 0o600

    @requires_posix
    def test_list_logs_clamps_existing(self, tmp_path, monkeypatch):
        """Upgrading from v0.2.4: old logs with laxer modes should be
        tightened on the first list_logs call."""
        from xtool import logs as logs_mod
        d = tmp_path / "logs"
        d.mkdir()
        monkeypatch.setattr(logs_mod, "LOGS_DIR", d)
        stale = d / "delete_20000101_000000.jsonl"
        stale.write_text("{}\n")
        os.chmod(stale, 0o644)
        logs_mod.list_logs()
        assert _mode(stale) == 0o600


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------

class TestLogRedaction:
    """bulk_action must not write credentials / user IDs into the log
    file. We exercise the redaction path directly and through a fake
    bulk run so any regression shows up at either layer."""

    def test_redact_text_scrubs_tokens(self):
        from xtool._redact import redact_text
        s = (
            "auth_token=" + _FAKE_AUTH_TOKEN
            + "; ct0=" + _FAKE_CT0
            + "; twid=u%3D" + _SENSITIVE_USER_ID
        )
        out = redact_text(s)
        assert _FAKE_AUTH_TOKEN not in out
        assert _FAKE_CT0 not in out
        assert _SENSITIVE_USER_ID not in out
        assert "<redacted:auth_token>" in out
        assert "<redacted:ct0>" in out
        assert "<redacted:twid>" in out

    def test_redact_text_scrubs_cookie_header(self):
        from xtool._redact import redact_text
        s = "Cookie: auth_token=" + _FAKE_AUTH_TOKEN + "; ct0=" + _FAKE_CT0
        out = redact_text(s)
        assert _FAKE_AUTH_TOKEN not in out
        assert _FAKE_CT0 not in out
        assert "<redacted:cookie>" in out

    def test_redact_text_scrubs_bearer(self):
        from xtool._redact import redact_text
        bearer = "AAAAAAAAAAAAAAAAAAAAAAA" + "x" * 40
        out = redact_text(f"authorization: Bearer {bearer}")
        assert bearer not in out
        assert "<redacted:bearer>" in out

    def test_redact_record_scrubs_user_id_fields(self):
        from xtool._redact import redact_record
        rec = {
            "id": "tweet123",                 # tweet id: MUST be kept
            "outcome": "deleted",
            "user_id": _SENSITIVE_USER_ID,    # user id: MUST be redacted
            "rest_id": _SENSITIVE_USER_ID,    # ditto
        }
        out = redact_record(rec)
        assert out["id"] == "tweet123"
        assert out["outcome"] == "deleted"
        assert out["user_id"] == "<redacted:user_id>"
        assert out["rest_id"] == "<redacted:user_id>"

    def test_bulk_action_log_does_not_contain_auth_token(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: even when a retry loop bubbles an error message
        that contains a cookie string, the log entry must be scrubbed."""
        from xtool import actions
        from xtool.actions import Credentials, get_action

        # Fake _attempt so we can force an error string containing a
        # credential. Returning ("failed", <string>) is what the real
        # retry loop does on non-auth errors.
        leaked = (
            "HTTP 500: upstream echoed Cookie: auth_token="
            + _FAKE_AUTH_TOKEN + "; ct0=" + _FAKE_CT0
        )
        monkeypatch.setattr(
            actions, "_attempt",
            lambda *a, **k: ("failed", leaked),
        )

        log = tmp_path / "deleted.jsonl"
        stats = actions.bulk_action(
            ["111", "222"],
            Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0),
            get_action("delete"),
            rate=0,
            log_path=log,
            resume=False,
            query_id="dummy",
        )
        assert stats.failed == 2
        contents = log.read_text(encoding="utf-8")
        assert _FAKE_AUTH_TOKEN not in contents
        assert _FAKE_CT0 not in contents
        # Redaction placeholder must be visible in the failure record.
        assert "<redacted:" in contents
        # Tweet ids (the whole point of the log) are preserved.
        assert "111" in contents and "222" in contents

    def test_bulk_action_log_does_not_contain_user_id(
        self, tmp_path, monkeypatch
    ):
        """A response body containing a rest_id field must not reach
        the log in plaintext."""
        from xtool import actions
        from xtool.actions import Credentials, get_action

        # Simulate perform_action returning a body that *looks* like a
        # real unretweet response, complete with rest_id.
        def fake_perform_action(session, action, tweet_id, *, query_id=None, timeout=20.0):
            return {
                "data": {
                    "unretweet": {
                        "source_tweet_results": {
                            "result": {"rest_id": _SENSITIVE_USER_ID},
                        }
                    }
                },
                "_raw_response": True,
            }

        monkeypatch.setattr(actions, "perform_action", fake_perform_action)

        log = tmp_path / "unretweeted.jsonl"
        stats = actions.bulk_action(
            ["42"],
            Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0),
            get_action("unretweet"),
            rate=0,
            log_path=log,
            resume=False,
            query_id="dummy",
        )
        contents = log.read_text(encoding="utf-8")
        assert _SENSITIVE_USER_ID not in contents
        assert "<redacted:user_id>" in contents


# ---------------------------------------------------------------------------
# whoami error hint must not leak user_id
# ---------------------------------------------------------------------------

class TestWhoamiErrorHintIsScrubbed:
    """The v0.2.4 whoami() error hint interpolated the numeric user_id
    from the twid cookie into the failure message. v0.2.5 should tell
    the user a twid cookie is present without leaking the id."""

    def test_whoami_error_does_not_interpolate_user_id(self, monkeypatch):
        from xtool.actions import ActionError, whoami, build_session, Credentials

        creds = Credentials(
            _FAKE_AUTH_TOKEN, _FAKE_CT0, twid=f"u%3D{_SENSITIVE_USER_ID}"
        )
        session = build_session(creds)

        # Force every REST endpoint to fail so we fall through to the
        # ActionError branch.
        class _StubResp:
            status_code = 500
            headers: dict = {}
            text = "server error"
            ok = False

            def json(self):
                raise ValueError("no body")

        class _FakeSession:
            cookies = session.cookies

            def prepare_request(self, req):
                class _P:
                    headers = {}

                    def pop(self, k, default=None):
                        return None

                return _P()

            def send(self, *a, **k):
                return _StubResp()

        fs = _FakeSession()
        with pytest.raises(ActionError) as exc_info:
            whoami(fs)
        msg = str(exc_info.value)
        # Absence of the raw id is the core assertion.
        assert _SENSITIVE_USER_ID not in msg
        # But we still tell the user a twid cookie was present, so they
        # know the problem isn't "no cookies".
        assert "twid" in msg.lower()


# ---------------------------------------------------------------------------
# Debug dump: mode + redaction
# ---------------------------------------------------------------------------

class TestDebugDumpIsSafe:
    @requires_posix
    def test_debug_dump_is_0600(self, tmp_path, monkeypatch):
        """iter_live_retweets with debug_path writes a 0600 file."""
        from types import SimpleNamespace
        from xtool import resolver

        def fake_gql_get(session, op, variables, features, field_toggles, offline):
            return {
                "data": {"user": {"result": {"timeline_v2": {"timeline": {
                    "instructions": [
                        {"type": "TimelineAddEntries", "entries": []},
                    ]
                }}}}}
            }

        monkeypatch.setattr(resolver, "_gql_get", fake_gql_get)
        dbg = tmp_path / "dump.jsonl"
        list(resolver.iter_live_retweets(
            session=SimpleNamespace(cookies=[]),
            user_id="99",
            rate=0,
            offline=True,
            debug_path=dbg,
        ))
        assert dbg.exists()
        assert _mode(dbg) == 0o600

    def test_debug_dump_redacts_payload(self, tmp_path, monkeypatch):
        """When the dump fires it must not contain a raw rest_id / user_id."""
        from types import SimpleNamespace
        from xtool import resolver

        # One entry with an obvious user-id shape in the payload.
        leaky_payload = [
            {
                "type": "TimelineAddEntries",
                "entries": [
                    {
                        "entryId": "tweet-1",
                        "content": {
                            "entryType": "TimelineTimelineItem",
                            "itemContent": {
                                "itemType": "TimelineTweet",
                                "tweet_results": {
                                    "result": {
                                        "rest_id": _SENSITIVE_USER_ID,
                                        "legacy": {
                                            "user_id": _SENSITIVE_USER_ID,
                                            "id_str": "555555555555",
                                            "full_text": "hi",
                                        },
                                    }
                                },
                            },
                        },
                    },
                    {"entryId": "cursor", "content": {
                        "entryType": "TimelineTimelineCursor",
                        "cursorType": "Bottom", "value": "CUR_END",
                    }},
                ],
            }
        ]

        calls = {"n": 0}

        def fake_gql_get(session, op, variables, features, field_toggles, offline):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"data": {"user": {"result": {"timeline_v2":
                    {"timeline": {"instructions": leaky_payload}}}}}}
            return {"data": {"user": {"result": {"timeline_v2":
                {"timeline": {"instructions":
                    [{"type": "TimelineAddEntries", "entries": []}]}}}}}}

        monkeypatch.setattr(resolver, "_gql_get", fake_gql_get)

        dbg = tmp_path / "dump.jsonl"
        list(resolver.iter_live_retweets(
            session=SimpleNamespace(cookies=[]),
            user_id="99",
            rate=0,
            offline=True,
            debug_path=dbg,
        ))
        # Dump must exist and must not contain the user_id in cleartext.
        contents = dbg.read_text(encoding="utf-8")
        assert _SENSITIVE_USER_ID not in contents
        assert "<redacted:user_id>" in contents


# ---------------------------------------------------------------------------
# Symlink / path traversal
# ---------------------------------------------------------------------------

class TestSymlinkSafety:
    """Writing a sensitive file over an attacker-placed symlink must
    not follow the link. We cannot easily verify O_NOFOLLOW on every
    platform, but we can verify the end state: after the write, the
    target file is a regular file, and the victim path pointed at by
    the symlink was not clobbered."""

    @requires_posix
    def test_cookies_write_does_not_follow_symlink(self, tmp_path):
        from xtool.actions import Credentials
        victim = tmp_path / "victim.txt"
        victim.write_text("IMPORTANT\n")
        cookies = tmp_path / "cookies.json"
        os.symlink(victim, cookies)

        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(cookies)

        # Victim must be untouched.
        assert victim.read_text() == "IMPORTANT\n"
        # cookies is now a regular file (replaced) and 0600.
        assert cookies.is_file() and not cookies.is_symlink()
        assert _mode(cookies) == 0o600

    @requires_posix
    def test_identity_write_does_not_follow_symlink(self, tmp_path):
        from xtool import identity_store
        victim = tmp_path / "victim.txt"
        victim.write_text("IMPORTANT\n")
        ident = tmp_path / "identity.json"
        os.symlink(victim, ident)

        identity_store.save(
            identity_store.IdentityRecord(expected_handle="v"), path=ident
        )
        assert victim.read_text() == "IMPORTANT\n"
        assert ident.is_file() and not ident.is_symlink()

    @requires_posix
    def test_safe_open_append_refuses_symlink(self, tmp_path):
        from xtool._safe_io import safe_open_append
        victim = tmp_path / "victim.txt"
        victim.write_text("IMPORTANT\n")
        log = tmp_path / "log.jsonl"
        os.symlink(victim, log)
        with pytest.raises(OSError):
            safe_open_append(log)
        assert victim.read_text() == "IMPORTANT\n"


# ---------------------------------------------------------------------------
# Shell-history warning
# ---------------------------------------------------------------------------

class TestShellHistoryWarning:
    """Passing --auth-token / --ct0 on the command line must print a
    yellow warning about shell history. Missing either flag must NOT
    print it (no false positives for the default `xtool login` path)."""

    def _build_args(self, auth_token=None, ct0=None, cookies_file=None):
        return argparse.Namespace(
            auth_token=auth_token,
            ct0=ct0,
            cookies_file=cookies_file,
        )

    def test_warning_prints_when_auth_token_passed(self, capsys, tmp_path):
        from xtool import cli
        args = self._build_args(auth_token=_FAKE_AUTH_TOKEN, ct0=_FAKE_CT0)
        cli._load_credentials(args)
        out = capsys.readouterr().out
        assert "shell history" in out.lower() or "process listing" in out.lower()
        # And the warning never echoes the actual value.
        assert _FAKE_AUTH_TOKEN not in out
        assert _FAKE_CT0 not in out

    def test_no_warning_when_flags_absent(self, capsys, tmp_path, monkeypatch):
        from xtool import cli
        # Make sure the default cookies path doesn't exist.
        monkeypatch.setattr(cli, "COOKIES_PATH", tmp_path / "nope.json")
        args = self._build_args()
        cli._load_credentials(args)
        out = capsys.readouterr().out
        assert "shell history" not in out.lower()


# ---------------------------------------------------------------------------
# xtool doctor
# ---------------------------------------------------------------------------

class TestDoctorCommand:
    def test_parser_registers_doctor(self):
        from xtool.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        assert args.command == "doctor"
        assert args.fix is False
        args = parser.parse_args(["doctor", "--fix"])
        assert args.fix is True

    def test_doctor_never_prints_secret_values(
        self, isolated_xtool_home, capsys, monkeypatch
    ):
        """Plant cookies with a real-looking credential and assert
        the doctor output never echoes it back."""
        from xtool import cli
        from xtool.actions import Credentials

        p = isolated_xtool_home / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0, twid=f"u={_SENSITIVE_USER_ID}").to_file(p)

        rc = cli.main(["doctor"])
        out = capsys.readouterr().out
        # Exit code may be 0 or 1 depending on other findings; both
        # are acceptable for this test. The critical assertion is
        # that NO secret values appear in the doctor output.
        assert rc in (0, 1)
        assert _FAKE_AUTH_TOKEN not in out
        assert _FAKE_CT0 not in out
        assert _SENSITIVE_USER_ID not in out

    @requires_posix
    def test_doctor_flags_bad_cookie_mode(
        self, isolated_xtool_home, capsys
    ):
        from xtool.actions import Credentials
        from xtool.doctor import run_checks, SEVERITY_CRITICAL

        p = isolated_xtool_home / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        # Deliberately loosen the mode.
        os.chmod(p, 0o644)

        report = run_checks()
        findings = [
            f for f in report.findings
            if f.check == "cookies-mode" and f.severity == SEVERITY_CRITICAL
        ]
        assert findings, (
            "doctor should flag cookies.json 0o644 as critical; got: "
            + ", ".join(f"{f.check}:{f.severity}" for f in report.findings)
        )

    @requires_posix
    def test_doctor_fix_tightens_permissions(self, isolated_xtool_home):
        from xtool.actions import Credentials
        from xtool.doctor import run_doctor

        p = isolated_xtool_home / "cookies.json"
        Credentials(_FAKE_AUTH_TOKEN, _FAKE_CT0).to_file(p)
        os.chmod(p, 0o644)
        # Also loosen the directory.
        os.chmod(isolated_xtool_home, 0o755)

        # Call run_doctor directly to exercise the --fix branch.
        args = argparse.Namespace(fix=True)
        rc = run_doctor(args)
        assert _mode(p) == 0o600
        assert _mode(isolated_xtool_home) == 0o700
        # After fix, the directory/cookies criticals are gone. Other
        # criticals (e.g. git-tracked files if the test runs inside
        # a repo with tracked .jsonl files) may still remain; we
        # assert only on the issues the fix was supposed to clear.
        # rc in (0, 1) covers both outcomes.
        assert rc in (0, 1)

    @requires_posix
    def test_doctor_detects_symlink_as_critical(
        self, isolated_xtool_home
    ):
        from xtool.doctor import run_checks, SEVERITY_CRITICAL
        victim = isolated_xtool_home / "victim.txt"
        victim.write_text("x\n")
        cookies = isolated_xtool_home / "cookies.json"
        os.symlink(victim, cookies)
        report = run_checks()
        hits = [
            f for f in report.findings
            if f.check == "cookies-mode" and f.severity == SEVERITY_CRITICAL
        ]
        assert any("symlink" in f.message.lower() for f in hits)

    def test_doctor_flags_credentials_in_identity_file(
        self, isolated_xtool_home
    ):
        """identity.json is never supposed to contain credentials.
        Doctor must flag them critical if they somehow appear."""
        from xtool.doctor import run_checks, SEVERITY_CRITICAL
        p = isolated_xtool_home / "identity.json"
        p.write_text(json.dumps({
            "expected_handle": "veldorakite",
            "auth_token": _FAKE_AUTH_TOKEN,  # attacker / bug
        }))
        os.chmod(p, 0o600)
        report = run_checks()
        hits = [
            f for f in report.findings
            if f.check == "identity-content" and f.severity == SEVERITY_CRITICAL
        ]
        assert hits, "identity-content finding should fire on credential key"


# ---------------------------------------------------------------------------
# .gitignore coverage
# ---------------------------------------------------------------------------

class TestGitignoreCoverage:
    """Make sure the project's .gitignore lists every private filename
    the audit calls out, so users who keep state inside the repo
    directory do not accidentally stage secrets."""

    @pytest.fixture
    def gitignore(self):
        return (
            Path(__file__).resolve().parent.parent / ".gitignore"
        ).read_text(encoding="utf-8")

    @pytest.mark.parametrize("pattern", [
        "cookies.json",
        "identity.json",
        "query_ids.json",
        "*.debug.jsonl",
        "*.err",
        ".tmp/",
    ])
    def test_pattern_present(self, gitignore, pattern):
        assert pattern in gitignore, (
            f".gitignore is missing {pattern!r}; users could accidentally "
            "commit a sensitive file. See CHANGELOG v0.2.5."
        )


# ---------------------------------------------------------------------------
# Version / changelog
# ---------------------------------------------------------------------------

class TestVersionBumpTo025:
    def test_version_is_025(self):
        from xtool import __version__
        assert __version__ == "0.2.5"

    def test_pyproject_version_is_025(self):
        pyproject = (
            Path(__file__).resolve().parent.parent / "pyproject.toml"
        ).read_text(encoding="utf-8")
        assert 'version = "0.2.5"' in pyproject

    def test_changelog_has_025_section(self):
        changelog = (
            Path(__file__).resolve().parent.parent / "CHANGELOG.md"
        ).read_text(encoding="utf-8")
        assert "[0.2.5]" in changelog
        lc = changelog.lower()
        # The audit headline terms must be referenced so reviewers can
        # trace the code changes back to the changelog.
        assert "redact" in lc
        assert "doctor" in lc
        assert "chmod" in lc or "0o600" in lc or "0600" in lc

    def test_readme_banner_is_025(self):
        readme = (
            Path(__file__).resolve().parent.parent / "README.md"
        ).read_text(encoding="utf-8")
        assert "v0.2.5" in readme
