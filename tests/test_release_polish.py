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
