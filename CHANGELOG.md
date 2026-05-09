# Changelog

All notable changes to this project will be documented in this file.

## [0.2.2] - 2026-05-09

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
