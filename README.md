# x-tool

A Termux / Linux CLI that bulk-deletes tweets, retweets and replies from
your X (Twitter) account using the official archive file (`tweet.js`) —
similar in spirit to Circleboom's
[*Delete Twitter Archive*](https://twitter.circleboom.com/my-tweets/delete-twitter-archive)
but fully local, free, scriptable, and open-source.

> Works with tens of thousands of tweets — X's "More tweets unavailable"
> scroll wall does not apply because we read tweet IDs directly from your
> archive.

---

## Features

- Parse the **entire** archive (`tweet.js` / `tweets.js` / `like.js`),
  no 3200-tweet scroll limit.
- Three bulk actions: **delete** tweets, **unretweet** retweets,
  **unlike** likes.
- **Auto-discovers** GraphQL query IDs from x.com's JS bundle so the
  tool keeps working when X rotates them (`xtool discover`), with a
  one-week cache and a bundled fallback table.
- Rich **filters**: date range, keyword regex, `--type tweet|retweet|reply`,
  min / max likes, min / max retweets, keep pinned, keep bookmarked IDs.
- **Dry-run** mode to preview what would be deleted.
- **Resumable** — writes a `deleted.jsonl` log so you can Ctrl-C and
  rerun without re-deleting anything.
- **No paid API needed** — authenticates with your browser's
  `auth_token` + `ct0` cookies and calls X's own internal GraphQL
  endpoint, the same mechanism Circleboom / Redact / TweetDelete use.
- Handles rate-limits with exponential back-off.
- Works on Termux (Android), any Linux, macOS and WSL.

---

## Install

### Termux (Android)

```bash
pkg update && pkg install -y python git
git clone https://github.com/melynkhael/x-tool
cd x-tool
bash install.sh
```

### Linux / macOS / WSL

```bash
git clone https://github.com/melynkhael/x-tool
cd x-tool
pip install .
```

After install you get an `xtool` command on your `$PATH`.

---

## Getting your X archive

1. Go to <https://x.com/settings/download_your_data> and request your
   archive. X emails you a zip file within 24 h (often much faster).
2. Unzip it. The file you need is `data/tweets.js` (older archives call
   it `tweet.js`). That's the only file `xtool` touches.

---

## Getting your session cookies

`xtool` needs two cookies from a logged-in X browser tab:

| Cookie       | Purpose                                   |
|--------------|-------------------------------------------|
| `auth_token` | proves you're logged in                   |
| `ct0`        | CSRF token, sent as `x-csrf-token` header |

How to find them:

1. Open <https://x.com> in Firefox / Chrome while logged in.
2. DevTools → *Application* (Chrome) or *Storage* (Firefox) → *Cookies*
   → `https://x.com`.
3. Copy the `auth_token` and `ct0` values.

Run `xtool login` for a step-by-step walkthrough, or pass them directly:

```bash
xtool delete filtered.jsonl --auth-token XXXX --ct0 YYYY
```

You can also save them to `~/.xtool/cookies.json` (see `xtool login`).

---

## Quick start

```bash
# 1. Convert archive to a line-delimited JSON we can work with
xtool parse ~/Downloads/twitter-archive/data/tweets.js -o all.jsonl

# 2. See what's in it
xtool stats all.jsonl

# 3. Keep only tweets older than 2023-01-01 with < 5 likes
xtool filter all.jsonl \
      --to 2023-01-01 \
      --max-likes 4 \
      -o to-delete.jsonl

# 4. Preview
xtool delete to-delete.jsonl --dry-run

# 5. Delete for real (1 request/sec, resumable)
xtool delete to-delete.jsonl --rate 1
```

---

## Subcommands

### `xtool parse <tweet.js|like.js> [-o out.jsonl] [--likes]`

Reads the `window.YTD.tweets.partN = [ ... ]` (or `.like.partN`)
JavaScript assignment, strips the prefix, parses the JSON array,
flattens the wrapper, and writes one object per line. Use `--likes`
for `like.js` archives (likes you've given, not received).

### `xtool stats <tweets.jsonl>`

Prints total count, date range, and a breakdown by type
(original / reply / retweet).

### `xtool filter <in.jsonl> [options] -o <out.jsonl>`

| Flag                       | Meaning                                     |
|----------------------------|---------------------------------------------|
| `--from YYYY-MM-DD`        | keep tweets on/after this date              |
| `--to YYYY-MM-DD`          | keep tweets on/before this date             |
| `--type tweet\|retweet\|reply\|all` | filter by type                     |
| `--keyword REGEX`          | keep tweets whose text matches this regex   |
| `--not-keyword REGEX`      | drop tweets whose text matches this regex   |
| `--min-likes N`            | only tweets with >= N likes                 |
| `--max-likes N`            | only tweets with <= N likes                 |
| `--min-retweets N`         | only tweets with >= N retweets              |
| `--max-retweets N`         | only tweets with <= N retweets              |
| `--keep-ids FILE`          | file of tweet IDs (one per line) to exclude |

### `xtool delete <tweets.jsonl> [options]`
### `xtool unretweet <tweets.jsonl> [options]`
### `xtool unlike <likes.jsonl> [options]`

All three share the same flags. They POST to X's internal GraphQL
mutation endpoints (`DeleteTweet`, `UnretweetTweet`, `UnfavoriteTweet`)
using your cookies.

| Flag                 | Meaning                                       |
|----------------------|-----------------------------------------------|
| `--auth-token TOKEN` | X `auth_token` cookie                         |
| `--ct0 TOKEN`        | X `ct0` cookie                                |
| `--cookies-file F`   | JSON file with `{auth_token, ct0}`            |
| `--rate R`           | requests per second (default 1.0)             |
| `--dry-run`          | don't actually call X, just log               |
| `--log FILE`         | progress log (per-action default)             |
| `--query-id ID`      | pin a specific GraphQL query id               |
| `--offline`          | don't auto-discover; use cache/fallback       |
| `--resume`           | skip ids already in the log (default on)      |
| `--no-resume`        | disable resume                                |

Typical flow for likes:

```bash
xtool parse ~/archive/data/like.js --likes -o my-likes.jsonl
xtool unlike my-likes.jsonl --rate 1 --dry-run
xtool unlike my-likes.jsonl --rate 1
```

And for retweets, filter the main archive first:

```bash
xtool filter all.jsonl --type retweet -o rts.jsonl
xtool unretweet rts.jsonl --rate 1
```

### `xtool discover [--refresh] [--offline]`

Fetches <https://x.com/> and the JS chunks it references, extracts every
`{queryId:"...",operationName:"..."}` pair, and caches the result in
`~/.xtool/query_ids.json` for a week. Delete / unretweet / unlike use
this cache automatically so x.com can rotate a query id without
breaking the tool. Pass `--refresh` to force a live fetch; `--offline`
to show what's currently cached / falling back.

You can also pin an id per-operation via env var:

```bash
export XTOOL_DELETE_TWEET_QUERY_ID=nxpZCY2K-I6QoFHAHeojFQ
export XTOOL_UNFAVORITE_TWEET_QUERY_ID=ZYKSe-w7KEslx3JhSIk5LA
```

### `xtool login`

Interactive helper that explains how to grab cookies and stores them in
`~/.xtool/cookies.json`.

---

## Disclaimer

Automating account actions is against X's Terms of Service. Use at your
own risk; this project exists for data-ownership / right-to-be-forgotten
use cases. The author is not responsible for suspended accounts, data
loss, or anything else. **Deleted tweets cannot be recovered.**

MIT License.
