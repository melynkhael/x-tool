"""Tests for the v0.2.4 privacy / UX polish.

Pins down the rules:

* numeric X user_id MUST NOT appear in default output (menu header,
  login success panel, `xtool whoami` output).
* it MAY appear when the caller explicitly opts in via
  ``xtool whoami --show-user-id`` / ``xtool account --show-user-id``.
* the verified menu line is just ``Account: @handle`` (no trailing
  "verified" word).
* a handle verified in a previous run is persisted to
  ``~/.xtool/identity.json`` (NO credentials there) and re-used by
  plain ``xtool`` on startup.
* a stale verification with a failing recheck renders as
  "@handle last verified, recheck failed".
* destructive actions still warn for partial / stale states.

Every test isolates the identity-store path to a tmp directory via
monkeypatch so they don't pick up or pollute the developer's real
``~/.xtool/identity.json``.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest


# A "representative" numeric user id that looks realistic enough that
# an accidental leak into assertion output would be obvious.
_SENSITIVE_USER_ID = "1816262302209085440"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_identity_store(tmp_path, monkeypatch):
    """Point ``identity_store.DEFAULT_PATH`` at a tmp file.

    All tests in this module use this fixture so they never read or
    write the real ``~/.xtool/identity.json``. Returns the tmp path
    so tests can assert on file contents directly.
    """
    from xtool import identity_store
    p = tmp_path / "identity.json"
    monkeypatch.setattr(identity_store, "DEFAULT_PATH", p)
    return p


# ---------------------------------------------------------------------------
# Menu header: never shows user_id; no "verified" word
# ---------------------------------------------------------------------------

class TestMenuHeaderNeverShowsUserId:
    """format_identity_line is the menu header. It runs on every
    prompt and shows up in every screenshot, so the numeric user_id
    must NEVER appear in it -- not in the verified branch, not in
    the twid-only branch, not anywhere."""

    def _rendered(self, identity):
        from xtool.ui import format_identity_line
        return format_identity_line(identity).plain

    def test_verified_line_does_not_include_user_id(self):
        from xtool.auth import Identity
        line = self._rendered(Identity(
            status="verified",
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        ))
        assert _SENSITIVE_USER_ID not in line
        # And the clean handle-only shape is what we DO render.
        assert line == "Account: @veldorakite"

    def test_verified_line_does_not_include_the_word_verified(self):
        """Per v0.2.4 spec: the green styling carries the verified
        signal; the literal word "verified" made the menu look
        cluttered."""
        from xtool.auth import Identity
        line = self._rendered(Identity(
            status="verified", handle="veldorakite"
        ))
        assert "verified" not in line.lower()

    def test_twid_only_does_not_include_user_id(self):
        from xtool.auth import Identity
        line = self._rendered(Identity(
            status="partial",
            user_id=_SENSITIVE_USER_ID,
            source="twid",
        ))
        assert _SENSITIVE_USER_ID not in line
        assert "twid found, handle not verified" in line

    def test_twid_only_does_not_include_old_leaky_wording(self):
        """Guard against the v0.2.3 wording regression."""
        from xtool.auth import Identity
        line = self._rendered(Identity(
            status="partial",
            user_id=_SENSITIVE_USER_ID,
            source="twid",
        ))
        # The exact old shape was: "Account: user id <N> from twid".
        assert "user id " not in line

    def test_cookies_only_state(self):
        from xtool.auth import Identity
        line = self._rendered(Identity(status="partial", source="cookie"))
        assert line == "Account: cookies saved, identity not verified"

    def test_not_logged_in_state(self):
        from xtool.auth import Identity
        assert self._rendered(Identity(status="none")) == (
            "Account: not logged in"
        )

    def test_stale_verified_state(self):
        from xtool.auth import Identity
        line = self._rendered(Identity(
            status="partial",
            source="cookie",
            last_verified_handle="veldorakite",
            recheck_failed=True,
        ))
        assert line == (
            "Account: @veldorakite last verified, recheck failed"
        )
        assert _SENSITIVE_USER_ID not in line


# ---------------------------------------------------------------------------
# Login success panel: no user_id by default
# ---------------------------------------------------------------------------

class TestLoginSuccessPanelHidesUserId:
    """``xtool login`` (or the wizard login) finishes by calling
    print_identity_banner on the verified identity. The banner must
    not leak the raw user_id by default."""

    def test_verified_banner_omits_user_id_by_default(self, capsys):
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner
        print_identity_banner(Identity(
            status="verified",
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        ))
        out = capsys.readouterr().out
        assert _SENSITIVE_USER_ID not in out
        assert "User ID" not in out
        # But we DO still describe the verification source so users
        # know how the tool confirmed the account.
        assert "handle matched via GraphQL" in out
        assert "Logged in as @veldorakite" in out

    def test_verified_banner_shows_user_id_when_opted_in(self, capsys):
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner
        print_identity_banner(
            Identity(
                status="verified",
                handle="veldorakite",
                user_id=_SENSITIVE_USER_ID,
                source="handle-match",
            ),
            show_user_id=True,
        )
        out = capsys.readouterr().out
        assert f"User ID: {_SENSITIVE_USER_ID}" in out

    def test_twid_only_banner_omits_user_id_by_default(self, capsys):
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner
        print_identity_banner(Identity(
            status="partial",
            user_id=_SENSITIVE_USER_ID,
            source="twid",
        ))
        out = capsys.readouterr().out
        assert _SENSITIVE_USER_ID not in out
        # Spec wording for this state:
        assert "twid found, but handle not verified" in out
        assert "--expect-handle" in out

    def test_twid_only_banner_shows_user_id_when_opted_in(self, capsys):
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner
        print_identity_banner(
            Identity(
                status="partial",
                user_id=_SENSITIVE_USER_ID,
                source="twid",
            ),
            show_user_id=True,
        )
        out = capsys.readouterr().out
        assert _SENSITIVE_USER_ID in out

    def test_stale_verified_banner_mentions_handle_not_user_id(self, capsys):
        from xtool.auth import Identity
        from xtool.ui import print_identity_banner
        print_identity_banner(Identity(
            status="partial",
            source="cookie",
            user_id=_SENSITIVE_USER_ID,
            last_verified_handle="veldorakite",
            recheck_failed=True,
        ))
        out = capsys.readouterr().out
        assert "@veldorakite" in out
        assert "recheck failed" in out
        assert _SENSITIVE_USER_ID not in out


# ---------------------------------------------------------------------------
# CLI: xtool whoami --show-user-id
# ---------------------------------------------------------------------------

class TestWhoamiHidesUserIdByDefault:
    """End-to-end CLI: the default invocation never prints the user
    id; the ``--show-user-id`` flag makes it appear."""

    def _verified(self, handle="veldorakite"):
        from xtool.auth import Identity
        return Identity(
            status="verified",
            handle=handle,
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
            detail="",
        )

    def test_default_output_hides_user_id(
        self, monkeypatch, capsys, isolated_identity_store
    ):
        from xtool import cli, auth as _auth
        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: self._verified(),
        )
        rc = cli.main(["whoami"])
        assert rc == 0
        out = capsys.readouterr().out
        assert _SENSITIVE_USER_ID not in out
        assert "User ID" not in out
        # Still useful: we tell the user what handle we verified
        # and how.
        assert "@veldorakite" in out
        assert "handle matched via GraphQL" in out

    def test_show_user_id_flag_reveals_user_id(
        self, monkeypatch, capsys, isolated_identity_store
    ):
        from xtool import cli, auth as _auth
        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: self._verified(),
        )
        rc = cli.main(["whoami", "--show-user-id"])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"User ID: {_SENSITIVE_USER_ID}" in out

    def test_account_alias_also_supports_show_user_id(
        self, monkeypatch, capsys, isolated_identity_store
    ):
        from xtool import cli, auth as _auth
        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: self._verified(),
        )
        # --show-user-id is registered on BOTH whoami and account.
        assert cli.main(["account", "--show-user-id"]) == 0
        out = capsys.readouterr().out
        assert _SENSITIVE_USER_ID in out

    def test_parser_registers_show_user_id_flag(self):
        from xtool.cli import build_parser
        parser = build_parser()
        # Both aliases accept the flag; neither is set by default.
        for cmd in ("whoami", "account"):
            args = parser.parse_args([cmd])
            assert args.show_user_id is False, (
                f"{cmd} default should be show_user_id=False"
            )
            args = parser.parse_args([cmd, "--show-user-id"])
            assert args.show_user_id is True


# ---------------------------------------------------------------------------
# identity_store: persistence contract
# ---------------------------------------------------------------------------

class TestIdentityStorePersistence:
    """The identity file is the ONLY place xtool persists the
    verified handle outside of the cookies file. These tests pin
    down the shape, the chmod, and the no-secrets invariant."""

    def test_record_verified_writes_safe_fields(self, isolated_identity_store):
        from xtool import identity_store
        identity_store.record_verified(
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        )
        data = json.loads(isolated_identity_store.read_text(encoding="utf-8"))
        # Required fields.
        assert data["expected_handle"] == "veldorakite"
        assert data["last_verified_handle"] == "veldorakite"
        assert data["last_verified_user_id"] == _SENSITIVE_USER_ID
        assert data["last_verified_source"] == "handle-match"
        # Timestamp is an ISO 8601 UTC string.
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            data["last_verified_at"],
        ), data["last_verified_at"]

    def test_record_verified_never_persists_credentials(
        self, isolated_identity_store
    ):
        """Belt and suspenders: even if a future refactor tried to
        shove auth_token/ct0/twid through identity_store, the stored
        file must not contain them."""
        from xtool import identity_store
        identity_store.record_verified(
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        )
        text = isolated_identity_store.read_text(encoding="utf-8").lower()
        for bad in ("auth_token", "ct0", "twid"):
            assert bad not in text, (
                f"identity.json must not contain {bad!r}; got:\n{text}"
            )

    def test_file_is_chmod_600_on_posix(self, isolated_identity_store):
        import os, stat
        if os.name != "posix":
            pytest.skip("POSIX-only check")
        from xtool import identity_store
        identity_store.record_verified(
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="rest",
        )
        mode = stat.S_IMODE(isolated_identity_store.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_load_returns_empty_when_missing(self, isolated_identity_store):
        # File doesn't exist -> IdentityRecord with all fields None.
        from xtool import identity_store
        record = identity_store.load()
        assert record.expected_handle is None
        assert record.last_verified_handle is None
        assert record.last_verified_at is None

    def test_load_tolerates_corrupt_file(self, isolated_identity_store):
        """A corrupt file must not crash the tool. Return empty record."""
        isolated_identity_store.parent.mkdir(parents=True, exist_ok=True)
        isolated_identity_store.write_text("{not valid json", encoding="utf-8")
        from xtool import identity_store
        record = identity_store.load()
        assert record.expected_handle is None

    def test_preserves_unknown_keys_on_round_trip(
        self, isolated_identity_store
    ):
        """A field written by a future version of xtool should survive
        a load+save cycle -- we don't want to clobber data we didn't
        produce."""
        isolated_identity_store.parent.mkdir(parents=True, exist_ok=True)
        isolated_identity_store.write_text(
            json.dumps({
                "expected_handle": "veldorakite",
                "future_field": "keep me",
            }),
            encoding="utf-8",
        )
        from xtool import identity_store
        record = identity_store.load()
        identity_store.save(record)
        data = json.loads(isolated_identity_store.read_text(encoding="utf-8"))
        assert data["future_field"] == "keep me"


class TestWhoamiPersistsIdentityOnSuccess:
    """`xtool whoami --expect-handle X` that succeeds must write the
    handle to identity.json so the next `xtool` invocation can show
    it without re-asking."""

    def test_verified_whoami_writes_identity_file(
        self, monkeypatch, isolated_identity_store
    ):
        from xtool import cli, auth as _auth, identity_store
        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: _auth.Identity(
                status="verified",
                handle="veldorakite",
                user_id=_SENSITIVE_USER_ID,
                source="handle-match",
                detail="",
            ),
        )
        rc = cli.main(["whoami", "--expect-handle", "veldorakite"])
        assert rc == 0

        record = identity_store.load()
        assert record.last_verified_handle == "veldorakite"
        assert record.expected_handle == "veldorakite"
        assert record.last_verified_source == "handle-match"
        assert record.last_verified_user_id == _SENSITIVE_USER_ID
        assert record.last_verified_at is not None

    def test_partial_whoami_remembers_expected_handle_only(
        self, monkeypatch, isolated_identity_store
    ):
        """When verification is partial but the user supplied a
        handle, we should still persist it as the expected_handle
        so later retries have a default. We must NOT promote it to
        last_verified_handle -- that's reserved for successful
        verifications."""
        from xtool import cli, auth as _auth, identity_store
        monkeypatch.setattr(
            _auth, "verify_from_cookie_file",
            lambda path, *, expect_handle=None: _auth.Identity(
                status="partial",
                user_id=_SENSITIVE_USER_ID,
                source="twid",
                detail="REST dead",
            ),
        )
        rc = cli.main(["whoami", "--expect-handle", "veldorakite"])
        assert rc == 1  # partial -> 1

        record = identity_store.load()
        assert record.expected_handle == "veldorakite"
        # Not promoted to verified.
        assert record.last_verified_handle is None


# ---------------------------------------------------------------------------
# Menu startup uses saved verified handle
# ---------------------------------------------------------------------------

class TestMenuSeedsHandleFromIdentityStore:
    """After a successful ``xtool whoami --expect-handle X`` the next
    plain ``xtool`` must surface that handle, not fall back to a
    twid-only partial that would print the raw user_id."""

    def test_plain_xtool_seeds_handle_from_identity_file(
        self, monkeypatch, isolated_identity_store
    ):
        from xtool import wizard, auth as _auth, identity_store

        # Pre-populate the identity file (the "after a successful
        # whoami" world).
        identity_store.record_verified(
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        )

        # Reset wizard state -- simulate a fresh process.
        wizard._state["identity"] = None
        wizard._state["handle"] = None

        seen: dict = {}

        def fake_verify(path, *, expect_handle=None):
            # The wizard must pass our persisted handle down so the
            # handle-match path has something to work with.
            seen["expect_handle"] = expect_handle
            return _auth.Identity(
                status="verified",
                handle="veldorakite",
                user_id=_SENSITIVE_USER_ID,
                source="handle-match",
                detail="",
            )

        monkeypatch.setattr(_auth, "verify_from_cookie_file", fake_verify)
        wizard._refresh_identity(force=True)

        assert seen["expect_handle"] == "veldorakite"
        assert wizard._state["handle"] == "veldorakite"
        # And rendering the menu line produces the clean shape.
        from xtool.ui import format_identity_line
        rendered = format_identity_line(wizard._state["identity"]).plain
        assert rendered == "Account: @veldorakite"
        assert _SENSITIVE_USER_ID not in rendered

    def test_stale_verified_renders_recheck_failed(
        self, monkeypatch, isolated_identity_store
    ):
        """Previously-verified handle + current probe fails =>
        "@handle last verified, recheck failed" line."""
        from xtool import wizard, auth as _auth, identity_store

        identity_store.record_verified(
            handle="veldorakite",
            user_id=_SENSITIVE_USER_ID,
            source="handle-match",
        )
        wizard._state["identity"] = None
        wizard._state["handle"] = None

        # Real verify_from_cookie_file walks through this module, so
        # we stub the underlying verify_identity to return a weaker
        # result and trust verify_from_cookie_file to stamp the
        # stale-verified annotations on top.
        def fake_verify_identity(creds, *, expect_handle=None, session=None):
            return _auth.Identity(
                status="partial",
                source="cookie",
                detail="REST dead",
            )

        # Put a cookies file in place so verify_from_cookie_file
        # doesn't short-circuit on the missing-file branch.
        from xtool.actions import Credentials
        from pathlib import Path
        import tempfile, os

        cookies_path = isolated_identity_store.parent / "cookies.json"
        Credentials("a" * 40, "b" * 40).to_file(cookies_path)

        monkeypatch.setattr(
            "xtool.wizard.COOKIES_PATH", cookies_path
        )
        monkeypatch.setattr(_auth, "verify_identity", fake_verify_identity)

        wizard._refresh_identity(force=True)
        from xtool.ui import format_identity_line
        rendered = format_identity_line(wizard._state["identity"]).plain
        assert rendered == (
            "Account: @veldorakite last verified, recheck failed"
        )
        assert _SENSITIVE_USER_ID not in rendered


# ---------------------------------------------------------------------------
# Destructive action safety still fires on partial / stale
# ---------------------------------------------------------------------------

class TestDestructiveStillWarnsOnStaleIdentity:
    """Spec: even with a "last verified" banner, destructive actions
    must still surface the NOT-verified warning and require a typed
    'yes'. The stale-verified display is a UX nicety; it does NOT
    relax the safety check."""

    def test_stale_verified_requires_typed_yes(self, monkeypatch):
        from xtool import safety
        # Simulate an accidental Enter -- must not count as yes.
        monkeypatch.setattr("builtins.input", lambda prompt="": "")
        assert safety.confirm_typed(
            action_name="delete",
            count=10,
            account="veldorakite",
            verified=False,  # stale-verified is still unverified for safety
        ) is False

    def test_stale_verified_shows_unverified_warning(
        self, monkeypatch, capsys
    ):
        from xtool import safety
        monkeypatch.setattr("builtins.input", lambda prompt="": "no")
        safety.confirm_typed(
            action_name="delete",
            count=10,
            account="veldorakite",
            verified=False,
        )
        out = capsys.readouterr().out.replace("\n", " ")
        # Regardless of casing: the NOT-verified block must appear.
        low = out.lower()
        assert "identity is not verified" in low

    def test_verified_path_still_accepts_typed_yes(self, monkeypatch):
        from xtool import safety
        monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
        assert safety.confirm_typed(
            action_name="delete",
            count=10,
            account="veldorakite",
            verified=True,
        ) is True


# ---------------------------------------------------------------------------
# Version bump + changelog / README mention
# ---------------------------------------------------------------------------

class TestVersionBumpTo024:
    def test_version_is_024(self):
        from xtool import __version__
        assert __version__ == "0.2.4"

    def test_changelog_has_024_section(self):
        changelog = (
            Path(__file__).resolve().parent.parent / "CHANGELOG.md"
        ).read_text(encoding="utf-8")
        assert "[0.2.4]" in changelog
        # And it mentions the key privacy changes, not just a bump.
        lc = changelog.lower()
        assert "user id" in lc or "user_id" in lc
        assert "show-user-id" in lc or "show_user_id" in lc

    def test_readme_banner_example_is_024(self):
        readme = (
            Path(__file__).resolve().parent.parent / "README.md"
        ).read_text(encoding="utf-8")
        assert "v0.2.4" in readme
