# Changelog

All notable changes to this project will be documented in this file.

## [0.2.5] - 2026-05-09 (docs)

Documentation-only polish on top of the v0.2.5 security/privacy
release. No code changes. No behaviour changes. All CLI commands,
menu options, and security protections from v0.2.5 still work the
same way.

### Changed

- README rewritten to be shorter and more beginner-friendly,
  especially on mobile. Uses short sections, one command per block,
  and step numbers. No tables. Long tutorials moved to `docs/`.
- Termux install steps are now broken into six single-command
  steps in the README, so each block is easy to copy on a phone.
- `docs/FIREFOX_COOKIE_EDITOR.md` rewritten with a simpler
  step-by-step structure and a clearer safety warning up front.
  Every step is its own heading.
- `docs/TROUBLESHOOTING.md` reorganised into named short sections
  (login failed, cookies saved but identity not verified, archive
  not found, `xtool update` failed, permission warning in doctor,
  etc.). Each answer is one to three short lines.
- `docs/SAFETY.md` simplified: what cookies are, why they are
  sensitive, what not to share, why dry-run matters, what
  `xtool doctor` checks, which files live in `~/.xtool`, and how
  to remove saved cookies.
- `TERMUX_GUIDE.md` rewritten with the same step-by-step voice as
  the README, single-command blocks, and no tables.
- Menu example in the README matches the actual v0.2.5 menu
  labels.
- Docs no longer show raw numeric user IDs in normal examples.

### Not changed

- No changes to `xtool/` source code.
- No changes to tests.
- No changes to version numbers; this is still v0.2.5.
- No weakening of the privacy or security posture.

## [0.2.5] - 2026-05-09

### Security / privacy audit

This release is a small, targeted security/privacy pass on top of
v0.2.4. The user-visible menu UX is unchanged: `Account: @handle`
still does not surface the numeric user ID, `xtool whoami --show-user-id`
is still the opt-in, `xtool update` still works, and destructive
actions still require the typed `yes` confirmation and dry-run flow.

#### Fixed

- **Cookie file permission race.** `Credentials.to_file()` previously
  called `Path.write_text` (which honours the process umask -- often
  `0o644`) and then followed up with `chmod 0o600`. Between the two
  steps a local attacker could open the file and read the cookie.
  The new write path uses `mkstemp` + `fsync` + atomic `os.replace`
  and opens the tempfile with `mode=0o600` from the first byte, so
  the file is never world-readable.
- **`~/.xtool/` directory mode.** The directory used to be created
  with whatever `mkdir` produced under the user umask (typically
  `0o755`). It is now created and re-tightened to `0o700` every
  time xtool touches it. This is not a credential leak on its own,
  but it did betray which accounts were actively being cleaned up.
- **Sensitive file modes.** `cookies.json`, `identity.json`,
  `query_ids.json`, per-operation log files, and resolver `--debug`
  dumps are now chmodded to `0o600` at creation time via the shared
  `xtool._safe_io` helpers, and re-clamped to `0o600` whenever
  `xtool doctor` or the log lister touches them.
- **Symlink / path traversal.** All writes to sensitive paths now
  use `O_NOFOLLOW` on the tempfile create and rename-based atomic
  replace at the destination. An attacker-placed symlink at
  `~/.xtool/cookies.json` (or any log file) no longer redirects the
  write to another target.
- **Log redaction.** `bulk_action` used to record truncated GraphQL
  response bodies and raw error messages. Both now pass through
  `xtool._redact.redact_record` before serialization, which replaces
  `auth_token` / `ct0` / `twid` / `Cookie:` / `authorization:` /
  `Bearer …` values with placeholder tokens and scrubs
  `user_id` / `rest_id` fields from response snippets.
- **`whoami` error hint.** The error message emitted when all REST
  identity endpoints fail used to interpolate the raw numeric
  `user_id` from the `twid` cookie into the hint text. The hint now
  only tells the user whether a twid cookie was present; the numeric
  value is redacted.
- **Resolver debug dumps.** `xtool resolve-retweets --debug` writes
  raw timeline instructions for diagnosis. Those dumps are now
  `0o600`, the payload is piped through `redact_record` before
  write, and the CLI prints a visible notice telling users the file
  is private before the walk begins.

#### Added

- **`xtool doctor` command.** Local, read-only security self-check.
  Reports on `~/.xtool` permissions, per-file modes, symlink
  tampering, credential-shaped content in `identity.json`, probable
  leaks in common shell history files, and sensitive filenames
  tracked in the current git checkout. Never prints secret values.
  `xtool doctor --fix` clamps obvious permission issues; it does not
  move, rename, or delete files. Exit code `0` / `1` is driven by
  whether any critical finding remains, so CI can wire it up.
- **Shell-history leak warning.** Running `xtool delete`,
  `xtool unretweet`, `xtool unlike`, or `xtool resolve-retweets`
  with `--auth-token` / `--ct0` on the command line now prints a
  yellow warning explaining that shell history and `ps` listings
  retain the value, and recommending `xtool login` instead.
- **Debug dump share warning.** When `--debug` is passed to
  `xtool resolve-retweets` the tool prints the dump path, its
  `chmod 600` mode, and a reminder to review before sharing.
- **`xtool/_safe_io.py`** -- private I/O primitives reused by every
  callsite that writes under `~/.xtool/`.
- **`xtool/_redact.py`** -- redaction helpers reused by logs,
  debug dumps, and the `whoami` error path.

#### Changed

- Expanded `.gitignore` to cover `cookies.json`, `identity.json`,
  `query_ids.json`, `*.debug.jsonl`, `*.err`, `.tmp/`, and
  per-action log filenames, so users who keep xtool state inside
  the repo directory cannot accidentally stage a credential file.
- Version bumped to v0.2.5 in `__init__.py`, `pyproject.toml`,
  `README.md`, and the CHANGELOG.

## [0.2.4] - 2026-05-09

### Fixed (privacy / UX)
- The menu header no longer prints the raw numeric X user ID. The
  v0.2.3 shape `Account: user id 1816262302209085440 from twid`
  leaked a permanent account identifier into every screenshot;
  it is now `Account: twid found, handle not verified` in that
  state. The user ID is still kept internally for verification, but
  it is never shown anywhere in default output.
- The verified menu line is now just `Account: @handle` (green).
  The word "verified" is dropped -- the colour carries the meaning
  and the line looks much cleaner in a Termux terminal.
- `xtool login` and `xtool whoami` no longer print `User ID: …` in
  their success / twid-only panels by default. The CLI gains a new
  opt-in flag for power users:
      xtool whoami --show-user-id
      xtool account --show-user-id
  With that flag the numeric user ID is shown; without it, it is not.

### Added
- New `~/.xtool/identity.json` file (chmod 600) that records the
  last verified handle, a UTC timestamp, and -- for internal use --
  the user_id and verification source. **No credentials** are
  stored here: `auth_token`, `ct0`, and `twid` remain in
  `cookies.json` only.
- Plain `xtool` now seeds the expected handle from that file, so
  after `xtool whoami --expect-handle veldorakite` succeeds the
  next `xtool` shows `Account: @veldorakite` without re-prompting.
- New menu state for stale verifications:
      Account: @veldorakite last verified, recheck failed
  shown when a previous verification is on file but the current
  network probe could not reconfirm the handle. Safety warnings
  for destructive actions still fire in this state.

### Changed
- `format_identity_line()` and `print_identity_banner()` gained a
  `show_user_id` flag (default False). The wizard always passes
  False; only the CLI `--show-user-id` opts in.
- CHANGELOG / README / banner bumped to v0.2.4.

## [0.2.3] - 2026-05-09

### Fixed
- `xtool update` no longer incorrectly reports "not installed from a
  git checkout" for a working editable checkout. The updater used to
  walk up from its own package directory only; when the package had
  been installed non-editably (which `install.sh --quiet` did on
  v0.2.2), `xtool/` lived in `site-packages` with no `.git`
  ancestor, so the walk found nothing. The updater now exposes a
  spec-named `find_git_root()` helper, runs it from both the
  package file **and** the current working directory, and prefers
  the package-location result when both succeed. The cwd fallback
  is guarded by a sanity check (``xtool/__init__.py`` must be
  present at the candidate root) so `xtool update` never tries to
  update an unrelated repo the user happens to be standing in.
- `install.sh` now installs editable (`pip install -e .`) in both
  quiet and verbose modes. This keeps the installed package rooted
  in the local git checkout, which is what the editable-aware
  detection in `xtool update` depends on. Users who installed with
  v0.2.2's quiet path should re-run `bash install.sh --quiet` once
  to switch over; after that `xtool update` will work for future
  releases.
- When the updater truly cannot find a git checkout, the error
  message now tells the user how to set one up
  (`git clone … && bash install.sh --quiet`) rather than pointing
  them at a pip URL that would reproduce the same problem.

## [0.2.2] - 2026-05-09

### Fixed
- `bash install.sh --quiet` no longer writes to the hardcoded
  `/tmp/xtool-install.err`. That path does not exist on Termux, so
  the script produced noisy `No such file or directory` warnings
  even on successful installs. The script now picks a temp dir by
  consulting `$TMPDIR`, then `$PREFIX/tmp` (Termux-native), then a
  repo-local `.tmp/`, and creates a unique file with `mktemp`. On
  success the temp file is removed; on failure it is preserved and
  its path is printed.

### Added
- `xtool update` command: beginner-friendly self-update. Runs a quiet
  `git pull --ff-only --quiet origin main` followed by a quiet
  `pip install -e . --upgrade` and prints only short progress lines.
  Real errors are never suppressed.
- `install.sh --quiet` flag for the same UX when `xtool update` is
  not an option. Falls back to verbose output on failure so users
  still see real errors.
- Menu option **u** to update X-Tool from inside the interactive menu.
- `docs/FIREFOX_COOKIE_EDITOR.md`: full beginner tutorial for finding
  `auth_token`, `ct0`, and `twid` with Firefox + Cookie-Editor.
- `docs/SAFETY.md` and `docs/TROUBLESHOOTING.md`: split out of the
  README so the landing page stays simple.
- README rewritten for beginners with a clear structure:
  what it does, safety, what you need, install, update, menu, login,
  cookies tutorial, archive, per-action guides, dry-run, troubleshooting,
  FAQ.

### Changed
- Login instruction text now asks for `auth_token`, `ct0`, **and**
  `twid` (previously said only `auth_token` and `ct0`).
- `xtool login` CLI now also prompts for the optional `twid` cookie.
- Verification message is exactly `Verifying session with X...` in
  every code path (previously one path showed `verifying cookies
  with X...`).
- Menu labels are simpler: "Login / save cookies", "Delete tweets",
  "Delete replies", "Delete tweets and replies", "Remove reposts",
  "Remove likes".
- Troubleshooting menu now explains all four identity verification
  states (`not logged in` / `cookies saved, identity not verified` /
  `user id ... from twid` / `@handle verified`).

## [0.2.1] - 2026-05-09

### Added
- Multi-signal identity verification (REST → twid → GraphQL handle
  match). The account header now shows `@handle verified` when the
  cookies can be confirmed, even after X deprecated the old REST
  whoami endpoints.
- Optional `twid` cookie support in `xtool login` and the wizard.
- `xtool whoami` / `xtool account` subcommand with
  `--expect-handle`.

### Fixed
- Login flow no longer saves broken cookies when the user pasted an
  empty or whitespace-only value.

## [0.2.0] - 2026-05-09

### Added
- **Interactive wizard/menu mode** — run `xtool` or `xtool menu` for a guided experience.
- Auto-detection of archive files (tweets.js, tweet.js, like.js).
- Live repost resolver with multi-round unretweet loop.
- `--debug` flag for resolve-retweets to dump raw timeline entries.
- Centralized log storage in `~/.xtool/logs/`.
- Full cleanup guided workflow (delete + unretweet + unlike in one flow).
- Troubleshooting menu with common issues and fixes.
- Professional README with badges, FAQ, and quick-start guide.
- CONTRIBUTING.md, SECURITY.md, LICENSE files.
- New modules: `ui.py`, `safety.py`, `logs.py`, `wizard.py`.
- Tests for wizard/menu integration.

### Fixed
- Resolver now follows `TimelineReplaceEntry` cursors (no longer stops after page 1).
- Resolver parses `TimelineTimelineModule` entries (older reposts).
- Resolver detects `SocialContextSelfRepost` entries (profile "You reposted").
- Empty `source_tweet_results` in DeleteRetweet correctly treated as no-op.

### Changed
- Running `xtool` with no subcommand now opens the interactive menu (was: error).
- Version bumped to 0.2.0.

## [0.1.0] - 2026-05-08

### Added
- Initial release.
- Parse tweets.js / tweet.js / like.js archives.
- Bulk delete tweets, unretweet, unlike.
- GraphQL query ID auto-discovery.
- Rate limiting and resume support.
- Dry-run mode.
- Termux / Linux / macOS / WSL support.
