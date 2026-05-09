# Changelog

All notable changes to this project will be documented in this file.

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
