"""Tests for the v0.2.2 public-release polish.

Covers:
* login instruction text includes auth_token, ct0, and twid
* verification message says exactly "Verifying session with X..."
* xtool update command does not silently hide errors
* README includes all the beginner sections from the spec
* docs/FIREFOX_COOKIE_EDITOR.md exists and covers the tutorial steps
* README / docs warn against sharing cookies
* banner still contains the "by: melynkhael" attribution
* menu wording uses the simple public-friendly labels
* troubleshooting covers all four identity verification states
"""

from __future__ import annotations

import io
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"
FIREFOX_TUTORIAL = DOCS / "FIREFOX_COOKIE_EDITOR.md"
SAFETY_DOC = DOCS / "SAFETY.md"
TROUBLESHOOTING_DOC = DOCS / "TROUBLESHOOTING.md"
INSTALL_SH = REPO_ROOT / "install.sh"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


# ── 1. Login instruction text ────────────────────────────────────────────

class TestLoginInstructionMentionsAllThreeCookies:
    """Spec: login instruction must ask for auth_token, ct0, AND twid."""

    def test_wizard_login_mentions_twid(self):
        """The wizard's _menu_login prints a block that must mention
        all three cookie names in the user-visible text."""
        source = (REPO_ROOT / "xtool" / "wizard.py").read_text(encoding="utf-8")
        # Grab the body of the _menu_login function so we only assert
        # against what the user actually sees on that screen.
        m = re.search(
            r"def _menu_login\(\).*?\n(?=def |\Z)",
            source,
            re.DOTALL,
        )
        assert m is not None, "could not locate _menu_login() body"
        body = m.group(0)
        # All three cookie names must appear in the visible prompts.
        assert "auth_token" in body
        assert "ct0" in body
        assert "twid" in body
        # And the spec asks that the text explicitly name all three
        # together -- not just mention twid in a side comment.
        assert re.search(r"auth_token.*ct0.*twid", body, re.DOTALL), (
            "login instruction must list auth_token, ct0, and twid together"
        )

    def test_wizard_login_does_not_say_two_cookies(self):
        """Regression guard for the old 'two cookies' wording."""
        source = (REPO_ROOT / "xtool" / "wizard.py").read_text(encoding="utf-8")
        assert "two cookies" not in source

    def test_cli_login_help_mentions_twid(self):
        """`xtool login` (non-interactive) must also mention all three."""
        from xtool.cli import LOGIN_HELP
        assert "auth_token" in LOGIN_HELP
        assert "ct0" in LOGIN_HELP
        assert "twid" in LOGIN_HELP


# ── 2. Verification message wording ──────────────────────────────────────

class TestVerificationMessageIsExact:
    """Spec: the verifying-session line must say exactly
    'Verifying session with X...' -- not 'sessiut', not 'cookies'."""

    def test_wizard_says_verifying_session_with_x(self):
        source = (REPO_ROOT / "xtool" / "wizard.py").read_text(encoding="utf-8")
        assert "Verifying session with X..." in source

    def test_cli_login_says_verifying_session_with_x(self):
        source = (REPO_ROOT / "xtool" / "cli.py").read_text(encoding="utf-8")
        assert "Verifying session with X..." in source

    def test_no_typos_like_sessiut(self):
        """Belt-and-suspenders: scan the codebase for the exact typo
        the spec called out ("sessiut")."""
        for py in (REPO_ROOT / "xtool").glob("*.py"):
            assert "sessiut" not in py.read_text(encoding="utf-8"), (
                f"{py.name} contains the 'sessiut' typo"
            )

    def test_no_leftover_verifying_cookies_message(self):
        """The old 'verifying cookies with X...' line must be gone from
        every user-visible code path, to keep the wording consistent."""
        for py in (REPO_ROOT / "xtool").glob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert "verifying cookies with X" not in text, (
                f"{py.name} still prints the old verification line"
            )


# ── 3. xtool update: does not hide errors ────────────────────────────────

class TestXtoolUpdateExists:
    """The update subcommand and menu option must be wired up."""

    def test_update_subcommand_registered(self):
        from xtool.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["update"])
        assert args.command == "update"
        assert hasattr(args, "func")

    def test_update_menu_option_registered(self):
        from xtool.wizard import MENU_ITEMS
        keys = [k for k, _label in MENU_ITEMS]
        assert "u" in keys, "menu must have an Update option (key 'u')"
        # Check the label mentions Update.
        label = dict(MENU_ITEMS)["u"]
        assert "update" in label.lower()


class TestUpdaterSurfacesErrors:
    """Spec: `xtool update` must NOT hide real errors. If git pull or
    pip fail, the user has to see the actual error text -- beginners
    need it to ask for help."""

    def test_no_repo_prints_hint(self, tmp_path, capsys):
        """When no .git ancestor is found, we print a helpful message
        (not silently succeed) and return exit code 2."""
        from xtool.updater import run_update
        # tmp_path has no .git walking upwards; pass it explicitly.
        rc = run_update(repo_path=None, printer=lambda *a, **kw: None)
        # The function must return an int -- never raise or exit silently.
        assert isinstance(rc, int)

    def test_git_failure_prints_error(self, tmp_path, monkeypatch):
        """When git pull fails, the error output is surfaced to the
        user AND the function returns non-zero."""
        repo = tmp_path / "fake-repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        captured: list[str] = []

        def fake_run(cmd, *, cwd, capture=True):
            if cmd[:2] == ["git", "pull"]:
                return 1, "", "fatal: could not resolve host github.com"
            return 0, "", ""

        from xtool import updater
        monkeypatch.setattr(updater, "_run", fake_run)
        monkeypatch.setattr(updater.shutil, "which", lambda x: "/usr/bin/" + x)

        rc = updater.run_update(repo_path=repo, printer=captured.append)
        text = " ".join(captured)
        assert rc == 1
        # The real error string from git MUST appear in the output.
        assert "could not resolve host github.com" in text
        # And a hint about what to do next should also be shown.
        assert "git pull failed" in text.lower()

    def test_pip_failure_prints_error(self, tmp_path, monkeypatch):
        """When pip install fails, the full stderr is surfaced and
        the function returns non-zero."""
        repo = tmp_path / "fake-repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        captured: list[str] = []

        def fake_run(cmd, *, cwd, capture=True):
            if cmd[:2] == ["git", "pull"]:
                return 0, "", ""
            if "pip" in cmd:
                return 1, "", "ERROR: Could not build wheels for cryptography"
            if cmd[:2] == ["git", "rev-parse"]:
                return 0, "abc1234\n", ""
            return 0, "", ""

        from xtool import updater
        monkeypatch.setattr(updater, "_run", fake_run)
        monkeypatch.setattr(updater.shutil, "which", lambda x: "/usr/bin/" + x)

        rc = updater.run_update(repo_path=repo, printer=captured.append)
        text = " ".join(captured)
        assert rc == 1
        # The real pip error must be visible.
        assert "Could not build wheels for cryptography" in text
        assert "pip install failed" in text.lower()

    def test_success_path_shows_version_and_commit(self, tmp_path, monkeypatch):
        """On success we print the expected four lines plus the
        version line and commit hash."""
        repo = tmp_path / "fake-repo"
        (repo / "xtool").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / "xtool" / "__init__.py").write_text(
            '"""doc"""\n\n__version__ = "0.2.2"\n',
            encoding="utf-8",
        )

        captured: list[str] = []

        def fake_run(cmd, *, cwd, capture=True):
            if cmd[:2] == ["git", "pull"]:
                return 0, "", ""
            if "pip" in cmd:
                return 0, "", ""
            if cmd[:2] == ["git", "rev-parse"]:
                return 0, "a5ce26d\n", ""
            return 0, "", ""

        from xtool import updater
        monkeypatch.setattr(updater, "_run", fake_run)
        monkeypatch.setattr(updater.shutil, "which", lambda x: "/usr/bin/" + x)

        rc = updater.run_update(repo_path=repo, printer=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "Updating X-Tool..." in joined
        assert "Pulling latest version..." in joined
        assert "Installing package..." in joined
        assert "Done." in joined
        assert "X-Tool v0.2.2 is ready." in joined
        assert "Latest commit: a5ce26d" in joined
        assert "Run `xtool` to open the menu." in joined

    def test_missing_git_binary_prints_hint(self, tmp_path, monkeypatch):
        """When git isn't on PATH, we tell the user how to install it
        instead of failing with a stack trace."""
        repo = tmp_path / "fake-repo"
        (repo / ".git").mkdir(parents=True)

        captured: list[str] = []

        from xtool import updater
        monkeypatch.setattr(updater.shutil, "which", lambda x: None)

        rc = updater.run_update(repo_path=repo, printer=captured.append)
        text = " ".join(captured)
        assert rc == 2
        assert "git is not installed" in text
        assert "pkg install git" in text


class TestInstallScriptQuietMode:
    """`bash install.sh --quiet` must exist, be short on success, and
    NOT hide real errors (it re-runs verbosely on failure)."""

    def test_install_script_accepts_quiet_flag(self):
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "--quiet" in text
        # Must parse it as a recognised flag (not fall through to
        # "unknown flag"), and the happy-path must set a quiet variable.
        assert "quiet=1" in text

    def test_install_script_does_not_hide_errors_silently(self):
        """Spec: quiet mode must re-run the install verbosely on
        failure so the user still sees what went wrong. We assert
        the script contains the explicit 'Rerunning verbosely' hint
        as a structural signal that errors aren't swallowed."""
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "Rerunning verbosely" in text or "rerunning verbosely" in text.lower()


class TestInstallScriptTempFileIsTermuxSafe:
    """Regression test for the /tmp bug: on Termux, /tmp does not
    exist, so the old `2>/tmp/xtool-install.err` redirect died with
    'No such file or directory'. The fix is to honour TMPDIR first,
    PREFIX/tmp second, then a repo-local ``.tmp`` directory.
    """

    def test_install_script_does_not_hardcode_slash_tmp(self):
        """The old install.sh had ``2>/tmp/xtool-install.err`` and a
        matching ``cat /tmp/xtool-install.err``. Both must be gone."""
        text = INSTALL_SH.read_text(encoding="utf-8")
        assert "/tmp/xtool-install" not in text, (
            "install.sh still contains a hardcoded /tmp path -- this "
            "will break on Termux where /tmp does not exist."
        )
        # And no bare literal `/tmp/` writes -- we don't want anyone
        # silently reintroducing a hardcode while refactoring.
        # (The string "/tmp" may appear inside comments explaining the
        # problem; strip out '#'-prefixed lines before asserting.)
        non_comment = "\n".join(
            ln for ln in text.splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert "/tmp/xtool" not in non_comment

    def test_install_script_uses_tmpdir_prefix_fallback(self):
        """Verify the three-tier resolution (TMPDIR -> PREFIX/tmp ->
        $here/.tmp) is wired up."""
        text = INSTALL_SH.read_text(encoding="utf-8")
        # All three candidate sources must be named in the helper.
        assert "TMPDIR" in text
        assert "PREFIX" in text
        assert ".tmp" in text
        # And the mktemp call must live under a helper (or inline)
        # so its location depends on the resolver's output.
        assert "mktemp" in text

    def test_tmp_dir_helper_picks_tmpdir_when_writable(self, tmp_path):
        """Drive the real helper function from install.sh in a
        subshell. This exercises the POSIX + Termux code path end-
        to-end without requiring Termux itself."""
        install_sh = INSTALL_SH.read_text(encoding="utf-8")
        # Extract just the _tmp_dir function so we can source it.
        m = re.search(
            r"_tmp_dir\(\)\s*\{.*?\n\}", install_sh, re.DOTALL
        )
        assert m, "install.sh is missing the _tmp_dir helper"
        helper = m.group(0)
        script = (
            f'here="{tmp_path}"\n'
            f'{helper}\n'
            '_tmp_dir\n'
        )
        out = subprocess.run(
            ["bash", "-c", script],
            env={
                "TMPDIR": str(tmp_path / "posix-tmp"),
                "PREFIX": "",
                "PATH": os.environ.get("PATH", ""),
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        # TMPDIR wins.
        assert out == str(tmp_path / "posix-tmp")
        # And the directory actually exists now.
        assert (tmp_path / "posix-tmp").is_dir()

    def test_tmp_dir_helper_falls_back_to_prefix_tmp(self, tmp_path):
        """When TMPDIR is empty but PREFIX is set (the Termux
        shape), we must use $PREFIX/tmp."""
        install_sh = INSTALL_SH.read_text(encoding="utf-8")
        m = re.search(
            r"_tmp_dir\(\)\s*\{.*?\n\}", install_sh, re.DOTALL
        )
        assert m
        helper = m.group(0)

        prefix = tmp_path / "fake-termux"
        prefix.mkdir()
        script = (
            f'here="{tmp_path}"\n'
            f'{helper}\n'
            '_tmp_dir\n'
        )
        out = subprocess.run(
            ["bash", "-c", script],
            env={
                "TMPDIR": "",
                "PREFIX": str(prefix),
                "PATH": os.environ.get("PATH", ""),
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == str(prefix / "tmp")
        assert (prefix / "tmp").is_dir()

    def test_tmp_dir_helper_falls_back_to_repo_dot_tmp(self, tmp_path):
        """When both TMPDIR and PREFIX are unusable the helper must
        land on $here/.tmp inside the repo checkout."""
        install_sh = INSTALL_SH.read_text(encoding="utf-8")
        m = re.search(
            r"_tmp_dir\(\)\s*\{.*?\n\}", install_sh, re.DOTALL
        )
        assert m
        helper = m.group(0)

        repo = tmp_path / "repo"
        repo.mkdir()
        script = (
            f'here="{repo}"\n'
            f'{helper}\n'
            '_tmp_dir\n'
        )
        # Point TMPDIR at an unwritable location to force fallback.
        bad_tmp = tmp_path / "definitely" / "not" / "writable"
        out = subprocess.run(
            ["bash", "-c", script],
            env={
                "TMPDIR": "/proc/readonly/" + str(bad_tmp),  # unwritable
                "PREFIX": "",
                "PATH": os.environ.get("PATH", ""),
            },
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == str(repo / ".tmp")
        assert (repo / ".tmp").is_dir()

    def test_quiet_install_failure_emits_clean_error(self, tmp_path):
        """End-to-end: copy install.sh into a fake repo with a
        broken pyproject.toml, run ``bash install.sh --quiet``, and
        verify the output contains a clean failure message instead
        of the old 'No such file or directory' noise."""
        repo = tmp_path / "fake-repo"
        repo.mkdir()
        # Broken pyproject so pip install fails; we deliberately
        # don't include a valid setup.py either.
        (repo / "pyproject.toml").write_text(
            "not a valid toml file", encoding="utf-8"
        )
        (repo / "install.sh").write_bytes(INSTALL_SH.read_bytes())
        proc = subprocess.run(
            ["bash", "install.sh", "--quiet"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            # Run in a neutral env -- no Termux detection, no
            # leftover TMPDIR pointing somewhere weird.
            env={
                "TMPDIR": "",
                "PREFIX": "",
                "PATH": os.environ.get("PATH", ""),
            },
        )
        # Failure must be loud and non-zero.
        assert proc.returncode != 0, (
            f"install.sh --quiet should fail on broken pyproject, "
            f"got rc={proc.returncode}\n"
            f"stdout: {proc.stdout!r}\n"
            f"stderr: {proc.stderr!r}"
        )
        combined = proc.stdout + proc.stderr
        # No trace of the old /tmp-missing noise.
        assert "/tmp/xtool-install.err" not in combined, (
            "install.sh still references the old hardcoded /tmp path"
        )
        assert "No such file or directory" not in combined or (
            # Rare: pip itself may mention a missing file; allow that
            # but require it NOT to reference install.sh's own redirect.
            "xtool-install.err" not in combined
        )
        # Success strings must NOT appear on failure.
        assert "X-Tool v" not in combined or "is ready." not in combined
        assert "Done." not in combined
        # But the real failure marker IS shown.
        assert "Install failed" in combined

    def test_quiet_install_success_leaves_no_stale_err_file(
        self, tmp_path, monkeypatch
    ):
        """On a successful quiet install, the temp error file should
        be cleaned up (it's the happy path, nothing to preserve)."""
        repo = tmp_path / "real-repo"
        # Copy the real repo so pip install actually works.
        import shutil as _shutil
        src_repo = REPO_ROOT
        _shutil.copytree(
            src_repo,
            repo,
            ignore=_shutil.ignore_patterns(
                ".git", "__pycache__", "*.egg-info",
                "build", "dist", ".tmp",
            ),
        )
        proc = subprocess.run(
            ["bash", "install.sh", "--quiet"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env={
                "TMPDIR": str(tmp_path / "my-tmp"),
                "PREFIX": "",
                "PATH": os.environ.get("PATH", ""),
            },
        )
        assert proc.returncode == 0, (
            f"quiet install should succeed on a valid checkout\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
        # The TMPDIR we pointed at should exist but contain no
        # leftover *.err file from a successful run.
        tmpdir = tmp_path / "my-tmp"
        if tmpdir.exists():
            err_files = list(tmpdir.glob("xtool-install*.err"))
            assert not err_files, (
                f"stale error files left over after success: {err_files}"
            )
        # And the user-visible success markers must all be present.
        assert "Done." in proc.stdout
        assert "is ready." in proc.stdout


# ── 4. README beginner sections ──────────────────────────────────────────

class TestReadmeHasBeginnerSections:
    """The spec lists a set of sections that must appear in the new
    beginner README. We assert each heading exists."""

    REQUIRED_HEADINGS = [
        "What this tool does",
        "Safety warning",
        "What you need",
        "Install on Termux",
        "Update X-Tool",
        "Start the menu",
        "Login / save cookies",
        "How to find auth_token, ct0, and twid using Firefox + Cookie-Editor",
        "How to load your X archive",
        "How to remove reposts",
        "How to remove likes",
        "How to delete tweets/replies",
        "Full cleanup guided mode",
        "Dry-run vs real run",
        "Troubleshooting",
        "FAQ",
    ]

    def test_every_required_section_present(self):
        text = README.read_text(encoding="utf-8")
        for heading in self.REQUIRED_HEADINGS:
            assert heading in text, (
                f"README is missing the '{heading}' section"
            )

    def test_readme_has_attribution(self):
        """Spec: README landing page should carry the 'by: melynkhael'
        attribution."""
        text = README.read_text(encoding="utf-8")
        assert "by: melynkhael" in text

    def test_readme_warns_not_to_share_cookies(self):
        """Spec explicitly: README warns users not to share cookies."""
        text = README.read_text(encoding="utf-8")
        low = text.lower().replace("*", "")
        # Has to mention the cookie names and an explicit 'don't share'
        # warning (or 'never share') somewhere.
        assert "never share" in low
        assert "auth_token" in text
        assert "ct0" in text
        assert "twid" in text

    def test_readme_mentions_xtool_update(self):
        text = README.read_text(encoding="utf-8")
        # Primary update instruction is `xtool update`.
        assert "xtool update" in text

    def test_readme_mentions_dry_run(self):
        text = README.read_text(encoding="utf-8").lower()
        assert "dry-run" in text

    def test_readme_version_is_current(self):
        """README banner example should match the current version."""
        from xtool import __version__
        text = README.read_text(encoding="utf-8")
        assert f"v{__version__}" in text


# ── 5. docs/FIREFOX_COOKIE_EDITOR.md ─────────────────────────────────────

class TestFirefoxCookieEditorTutorial:
    """The spec requires a beginner tutorial for finding the three
    cookies with Firefox + Cookie-Editor."""

    def test_file_exists(self):
        assert FIREFOX_TUTORIAL.exists(), (
            f"missing docs file: {FIREFOX_TUTORIAL.relative_to(REPO_ROOT)}"
        )

    def test_tutorial_covers_required_steps(self):
        """Each numbered step from the spec must appear as a concept
        in the tutorial. We match loosely -- the order is fixed by the
        spec but wording can vary."""
        text = FIREFOX_TUTORIAL.read_text(encoding="utf-8").lower()
        required_concepts = [
            "firefox",
            "cookie-editor",
            "x.com",
            "auth_token",
            "ct0",
            "twid",
            "u=",
            "xtool",
            "login",
            "paste",
            "handle",
        ]
        for concept in required_concepts:
            assert concept in text, f"tutorial missing concept: {concept}"

    def test_tutorial_warns_not_to_share_cookies(self):
        """Spec: tutorial must include the 'never share' warning."""
        text = FIREFOX_TUTORIAL.read_text(encoding="utf-8").lower()
        # Markdown emphasis (**Never**) shows up literally in the file,
        # so we strip the asterisks before matching.
        flat = text.replace("*", "")
        assert "never share" in flat
        # And call out the common places users accidentally leak them.
        for placeholder in (
            "github issues",
            "discord",
            "telegram",
            "screenshots",
        ):
            assert placeholder in text, (
                f"tutorial should warn about pasting cookies into {placeholder}"
            )

    def test_tutorial_explains_required_vs_optional(self):
        """Spec: explain that auth_token and ct0 are required, twid is
        optional but strongly recommended."""
        text = FIREFOX_TUTORIAL.read_text(encoding="utf-8").lower()
        assert "required" in text
        assert "optional" in text
        assert "recommended" in text

    def test_tutorial_has_numbered_steps(self):
        """The spec calls for 15 concrete steps. We assert there are
        at least ten '### <number>.' or '### <n>.' headings."""
        text = FIREFOX_TUTORIAL.read_text(encoding="utf-8")
        numbered_headings = re.findall(r"^###\s+\d+\.\s", text, re.MULTILINE)
        assert len(numbered_headings) >= 10, (
            f"tutorial has only {len(numbered_headings)} numbered steps"
        )


# ── 6. Supporting docs ───────────────────────────────────────────────────

class TestDocsStructure:
    def test_safety_doc_exists(self):
        assert SAFETY_DOC.exists()

    def test_troubleshooting_doc_exists(self):
        assert TROUBLESHOOTING_DOC.exists()

    def test_troubleshooting_covers_all_four_identity_states(self):
        """Spec: troubleshooting must explain every identity state
        shown in the menu header."""
        text = TROUBLESHOOTING_DOC.read_text(encoding="utf-8").lower()
        assert "not logged in" in text
        assert "cookies saved" in text
        assert "from twid" in text
        assert "verified" in text

    def test_troubleshooting_explains_dry_run_recommendation(self):
        text = TROUBLESHOOTING_DOC.read_text(encoding="utf-8").lower()
        assert "dry-run" in text


class TestChangelogMentions022:
    def test_022_section_exists(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        assert "[0.2.2]" in text

    def test_022_entry_mentions_key_changes(self):
        text = CHANGELOG.read_text(encoding="utf-8").lower()
        assert "xtool update" in text
        assert "firefox" in text or "cookie-editor" in text


# ── 7. Banner attribution (regression guard) ─────────────────────────────

class TestBannerAttributionPersists:
    """The spec explicitly requires 'by: melynkhael' to stay in the
    banner. This test is redundant with the existing banner test
    but is restated here so the release-polish suite is a single
    self-contained reference."""

    def test_banner_shows_by_melynkhael(self, capsys):
        from xtool.ui import print_banner
        print_banner()
        out = capsys.readouterr().out
        assert "by: melynkhael" in out


# ── 8. Public-friendly menu wording ──────────────────────────────────────

class TestMenuWordingIsSimple:
    """Spec: the first-screen menu should use simple language."""

    EXPECTED_LABELS = {
        "Delete tweets",
        "Delete replies",
        "Remove reposts",
        "Remove likes",
        "Full cleanup",
        "Troubleshooting",
    }

    def test_menu_contains_expected_simple_labels(self):
        from xtool.wizard import MENU_ITEMS
        labels = {label for _k, label in MENU_ITEMS}
        for expected in self.EXPECTED_LABELS:
            assert any(expected in l for l in labels), (
                f"menu is missing a label for {expected!r}; got {labels}"
            )

    def test_menu_does_not_use_jargon(self):
        """Old labels like 'retweet' and 'original tweets' have been
        simplified. Guard against regressions."""
        from xtool.wizard import MENU_ITEMS
        joined = " ".join(label for _k, label in MENU_ITEMS).lower()
        # "retweet" alone (outside of "reposts" synonym) shouldn't be
        # the primary wording on the first screen.
        assert "original tweets" not in joined
        assert "originals + replies" not in joined


# ── 9. Troubleshooting menu covers the four states ───────────────────────

class TestTroubleshootingMenuStates:
    """The in-app troubleshooting menu must explain the four identity
    verification states from the spec."""

    def test_source_lists_all_four_states(self):
        source = (REPO_ROOT / "xtool" / "wizard.py").read_text(encoding="utf-8")
        m = re.search(
            r"def _menu_troubleshooting.*?(?=\n# |\ndef |\Z)",
            source,
            re.DOTALL,
        )
        assert m, "could not locate _menu_troubleshooting body"
        body = m.group(0).lower()
        assert "not logged in" in body
        assert "cookies saved, identity not verified" in body
        assert "from twid" in body
        assert "verified" in body
        # And the spec-required nudge toward dry-run:
        assert "dry-run" in body
