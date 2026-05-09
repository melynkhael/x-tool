# X-Tool

> Clean up your X (Twitter) account — delete tweets, undo retweets, remove likes.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Termux%20%7C%20Linux%20%7C%20macOS%20%7C%20WSL-lightgrey.svg)](#installation)

---

## What It Does

X-Tool helps you bulk-clean your X/Twitter account using your downloaded data archive:

- **Delete tweets** — originals, replies, or both
- **Remove reposts** — resolves real source IDs from your live profile
- **Unlike tweets** — from your like.js archive
- **Interactive wizard** — no commands to memorize
- **Resume support** — interrupted? Pick up where you left off
- **Dry-run mode** — preview what will happen before committing

---

## Quick Start

### Interactive Mode (Recommended)

```bash
xtool
```

That's it. A guided menu walks you through everything:

```
 X-Tool — X / Twitter Account Cleanup  v0.2.0

 What would you like to do?

   1  Login / update cookies
   2  Load X archive
   3  Show archive stats
   4  Delete original tweets
   5  Delete replies
   6  Delete originals + replies
   7  Remove reposts / retweets
   8  Remove likes
   9  Full cleanup (guided)
   t  Troubleshooting
   0  Exit
```

### Android / Termux Quick Start

```bash
pkg install python python-pip git
pip install git+https://github.com/melynkhael/x-tool.git
xtool
```

See [TERMUX_GUIDE.md](TERMUX_GUIDE.md) for detailed Termux instructions.

---

## Installation

### From GitHub (recommended)

```bash
pip install git+https://github.com/melynkhael/x-tool.git
```

### From source

```bash
git clone https://github.com/melynkhael/x-tool.git
cd x-tool
bash install.sh
```

### Requirements

- Python 3.9+
- `requests`, `python-dateutil`, `rich` (installed automatically)

---

## How It Works

1. **Download your X archive** — X Settings > Your Account > Download an archive
2. **Get your session cookies** — `auth_token` and `ct0` from your browser
3. **Run X-Tool** — choose what to clean, confirm, done

X-Tool talks directly to X's web API using the same requests your browser makes. No third-party services, no OAuth apps, no API keys needed.

---

## Features

| Feature | Description |
|---------|-------------|
| Interactive menu | Guided wizard for all operations |
| Bulk delete | Delete thousands of tweets at ~1/sec |
| Smart unretweet | Live timeline resolver finds real source IDs |
| Unlike | Remove all likes from your like.js archive |
| Dry-run | Preview changes before executing |
| Resume | Automatic — interrupted runs continue where they left off |
| Rate limiting | Built-in safe rate limiting (1 req/sec default) |
| Account safety | `--expect-account` prevents running on wrong account |
| Logs | Every operation logged to `~/.xtool/logs/` |
| Offline mode | Use cached/fallback query IDs without network |

---

## Advanced CLI

For power users, all operations are available as direct commands:

```bash
# Parse archive
xtool parse ~/x-archive/data/tweets.js -o tweets.jsonl

# View stats
xtool stats tweets.jsonl

# Filter (keep only tweets before 2023)
xtool filter tweets.jsonl --to 2023-01-01 -o old-tweets.jsonl

# Delete with confirmation
xtool delete old-tweets.jsonl --expect-account myhandle

# Resolve live reposts and unretweet
xtool resolve-retweets --handle myhandle -o reposts.jsonl
xtool unretweet reposts.jsonl --expect-account myhandle

# Unlike all likes
xtool parse ~/x-archive/data/like.js --likes -o likes.jsonl
xtool unlike likes.jsonl --expect-account myhandle

# Dry-run any command
xtool delete tweets.jsonl --dry-run
```

### All Commands

| Command | Description |
|---------|-------------|
| `xtool` | Interactive menu |
| `xtool menu` | Interactive menu (explicit) |
| `xtool login` | Save X session cookies |
| `xtool parse` | Convert archive JS to JSONL |
| `xtool stats` | Show archive statistics |
| `xtool filter` | Filter tweets by date/type/keyword |
| `xtool delete` | Bulk delete tweets |
| `xtool unretweet` | Bulk undo retweets |
| `xtool unlike` | Bulk remove likes |
| `xtool resolve-retweets` | Find source IDs from live profile |
| `xtool discover` | Refresh GraphQL query IDs |

---

## Safety & Limitations

- **Deleted tweets cannot be recovered.** Always use `--dry-run` first.
- **X rate limits** — the tool respects X's limits (~1 req/sec). Going faster risks temporary account locks.
- **Profile counters lag** — X caches tweet/like counts. After cleanup, counters may take minutes to hours to update.
- **Archive can be stale** — your downloaded archive is a snapshot. Tweets posted after the archive was generated won't be included.
- **Reposts need live resolution** — archive wrapper IDs don't work for unretweet. The tool handles this automatically.
- **Terms of Service** — automating X actions may violate X's ToS. Use at your own risk.

---

## FAQ

**Q: Is this safe?**
A: The tool runs 100% locally. Your cookies never leave your machine. But deleted content is gone forever — use dry-run first.

**Q: Do I need an API key or developer account?**
A: No. X-Tool uses the same web session your browser uses (cookies only).

**Q: Why do I need cookies instead of a password?**
A: X's web client authenticates via session cookies. This is the same mechanism your browser uses — no password is stored or transmitted by X-Tool.

**Q: My repost count doesn't go down after running unretweet.**
A: X caches profile counters aggressively. Wait 5-30 minutes and refresh your profile.

**Q: Can I undo a deletion?**
A: No. Deleted tweets are permanently gone. Always dry-run first.

**Q: Does it work on Android?**
A: Yes, via Termux. See [TERMUX_GUIDE.md](TERMUX_GUIDE.md).

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "authentication rejected" | Cookies expired. Re-login at x.com, run `xtool login` again. |
| "rate limited" | Wait 15 min and retry. Don't increase `--rate` above 1. |
| "no retweets found" | Profile may be cached. Or use `--debug` to inspect timeline shape. |
| "query ID stale" | Run `xtool discover --refresh` to fetch new IDs from x.com. |
| Network errors | Check VPN/firewall. Ensure x.com is reachable. |

---

## Privacy & Security

- All data stays on your device.
- Cookies stored in `~/.xtool/cookies.json` (chmod 600).
- No telemetry, analytics, or third-party services.
- Delete your cookies when done: `rm ~/.xtool/cookies.json`

---

## Roadmap

- [ ] Bookmark cleanup
- [ ] DM cleanup (if X ever exposes the API)
- [ ] Scheduled/timed cleanup
- [ ] Export before delete (backup mode)
- [ ] GUI/TUI with full Rich interface

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Disclaimer

This tool is provided as-is. Use at your own risk. The authors are not responsible for any account actions, bans, or data loss resulting from use of this tool. Automating actions on X may violate their Terms of Service.

---

## License

[MIT](LICENSE)
