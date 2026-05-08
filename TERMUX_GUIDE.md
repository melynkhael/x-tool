# xtool on Termux: step-by-step

A start-to-finish walkthrough for deleting tweets, undoing retweets and
unliking from an Android phone, using only Termux and your X archive.

Time estimate: **~30 minutes of active work**, plus a wait for X to
produce the archive (up to 24 h) and the actual deletion pass (1 tweet
/ second by default — so ~17 minutes per 1000 tweets).

> **Safety summary:** xtool authenticates as you with a cookie you
> extract from your own logged-in browser. It verifies the account
> before doing anything destructive, refuses to run above 2 requests /
> second unless you force it, and always asks for confirmation. All
> network calls go only to `x.com` and `abs.twimg.com`.
> **Deleted tweets cannot be recovered — use `--dry-run` first.**

---

## 0. What you need

- A phone with [Termux](https://f-droid.org/packages/com.termux/)
  installed from F-Droid (the Play Store version is outdated).
- The X (Twitter) account you want to clean.
- A browser on *any* device where you are logged in to that same
  account (Firefox / Chrome / Safari all work).
- ~500 MB of free storage for the archive.

---

## 1. Request your X archive

1. Open <https://x.com/settings/download_your_data> in a browser.
2. Re-enter your password when prompted, then tap **Request archive**.
3. X emails you a download link within 24 h (usually much faster).
4. Download the `.zip` on your phone.

You only need one file from it: `data/tweets.js` (plus
`data/like.js` if you also want to bulk-unlike).

---

## 2. Install xtool in Termux

Paste these into Termux one block at a time:

```bash
# Update base packages
pkg update -y && pkg upgrade -y

# Install Python + git
pkg install -y python git

# Grant Termux access to /sdcard so you can read the archive zip
termux-setup-storage
# (approve the Android permission prompt that pops up)

# Clone xtool and install
git clone https://github.com/melynkhael/x-tool
cd x-tool
bash install.sh
```

Verify:

```bash
xtool --version
```

You should see `xtool 0.1.0`.

---

## 3. Extract the archive zip

Assuming you saved the zip to `Downloads`:

```bash
mkdir -p ~/archive
cd ~/archive
unzip ~/storage/downloads/twitter-*.zip     # name will vary
ls data/tweets.js                            # should exist
ls data/like.js                              # only if you also have likes
```

If `unzip` is missing:

```bash
pkg install -y unzip
```

---

## 4. Convert the archive to JSONL

```bash
cd ~/x-tool          # or wherever - xtool is on your PATH
xtool parse ~/archive/data/tweets.js -o ~/archive/all.jsonl
xtool stats ~/archive/all.jsonl
```

You'll see a table like:

```
total                   12847
original tweets         4210
replies                 7115
retweets                1522
oldest                  2013-08-17T…
newest                  2026-05-08T…
```

That total is the authoritative count of deletable items. Circleboom's
web tool, Redact, and X's own UI all miss anything older than ~3200
tweets — xtool doesn't, because it's reading your archive file directly.

---

## 5. Decide what to delete (filter)

Examples:

**Delete everything older than 2024-01-01:**

```bash
xtool filter ~/archive/all.jsonl \
    --to 2024-01-01 \
    -o ~/archive/to-delete.jsonl
```

**Delete only low-engagement tweets older than a year:**

```bash
xtool filter ~/archive/all.jsonl \
    --to 2025-05-08 --max-likes 2 --max-retweets 0 \
    -o ~/archive/to-delete.jsonl
```

**Delete every retweet but keep your own originals:**

```bash
xtool filter ~/archive/all.jsonl \
    --type retweet \
    -o ~/archive/to-delete.jsonl
```

**Delete replies that mention a specific keyword:**

```bash
xtool filter ~/archive/all.jsonl \
    --type reply --keyword 'crypto' \
    -o ~/archive/to-delete.jsonl
```

**Keep a hand-picked whitelist:**

Put tweet IDs (one per line) in `~/archive/keep.txt`, then:

```bash
xtool filter ~/archive/all.jsonl \
    --to 2024-01-01 --keep-ids ~/archive/keep.txt \
    -o ~/archive/to-delete.jsonl
```

Always re-check the count before going further:

```bash
xtool stats ~/archive/to-delete.jsonl
```

---

## 6. Grab your session cookies

xtool needs two cookies from any logged-in X browser session. It does
**not** need your password and never sees it.

### On a desktop browser (easier)

1. Open <https://x.com> while logged into the account you want to clean.
2. Press **F12** to open DevTools.
   * Chrome/Edge → *Application* tab → *Storage* → *Cookies* →
     `https://x.com`.
   * Firefox → *Storage* tab → *Cookies* → `https://x.com`.
3. Find and copy the *Value* column for these two rows:
   - `auth_token` (~40 hex chars)
   - `ct0`        (~32–160 chars)

### On Android Firefox

1. Install the **Cookie Editor** addon.
2. Open <https://x.com>, log in.
3. Tap the Cookie Editor icon → find `auth_token` and `ct0` → long-press
   the value → *Copy*.

### On Android Chrome

Chrome on Android does not let you view cookies. Use Firefox (above) or
grab them from a desktop.

### Save them

Back in Termux:

```bash
xtool login
```

Paste each value when prompted. xtool will:

1. Save them to `~/.xtool/cookies.json` with `chmod 600`.
2. Verify they work by calling X's `account/settings.json` and printing
   the resulting `@handle`.

If you see `logged in as @yourhandle` you're set.

If you see `authentication failed` — log out and back in on the browser,
then redo `xtool login` with the fresh cookies.

### One-off invocation without saving

```bash
xtool delete … --auth-token XXXX --ct0 YYYY
```

---

## 7. Preview with `--dry-run`

**Always do this first.** No network writes; just shows what *would* happen.

```bash
xtool delete ~/archive/to-delete.jsonl --dry-run
```

You'll see a banner like:

```
Account: (dry-run, cookies not verified)  Action: DeleteTweet  Target: 8421
Rate: 1.0/s  Dry-run: True  Resume: True  queryId: nxpZCY2K-I6QoFHAHeojFQ
```

If the target count matches what `xtool stats` told you, you're good.

---

## 8. Delete for real

### Standard run

```bash
xtool delete ~/archive/to-delete.jsonl \
    --expect-account yourhandle \
    --rate 1
```

`--expect-account` is the single most important safety flag. If your
cookies somehow belong to a different account (an old login, someone
else's phone, etc.) xtool will refuse to do anything.

You'll see a safety banner + a confirmation prompt:

```
Account: @yourhandle  Action: DeleteTweet  Target: 8421  Rate: 1.0/s
Dry-run: False  Resume: True  queryId: nxpZCY2K-I6QoFHAHeojFQ

This will run DeleteTweet on 8421 tweets from @yourhandle.
Estimated duration: ~140.4 min at 1.0/s. Deleted tweets cannot be recovered.
Type 'yes' to proceed:
```

Type `yes` and press Enter. A live progress bar takes over:

```
  ok=237 gone=1 fail=0 skip=0 ████████░░░░░░░░░ 238/8421 0:04:02
```

### Run without the prompt (for scripts / unattended)

```bash
xtool delete ~/archive/to-delete.jsonl \
    --expect-account yourhandle \
    --rate 1 --yes
```

### If Termux sleeps

Stopping Termux from being killed mid-run:

```bash
pkg install -y termux-api
termux-wake-lock                  # keep CPU on
xtool delete ~/archive/to-delete.jsonl --yes --expect-account yourhandle --rate 1
termux-wake-unlock                # when done
```

For *very* long runs you can also run inside `tmux`:

```bash
pkg install -y tmux
tmux new -s del
xtool delete … ; exit
# detach with Ctrl-b then d
# reattach later with: tmux attach -t del
```

---

## 9. If the run is interrupted

xtool is resumable by default. Each attempted ID is appended to
`deleted.jsonl` in the current directory. Just rerun the same command —
it will skip anything already in the log.

```bash
xtool delete ~/archive/to-delete.jsonl --expect-account yourhandle --rate 1
# shows: skip=2374 for the ones it did previously
```

Use `--log /some/other/path.jsonl` to keep separate logs per run.

---

## 10. Undo retweets and unlike

Same flow, different subcommand.

**Undo every retweet in your archive:**

```bash
xtool filter ~/archive/all.jsonl --type retweet -o ~/archive/rts.jsonl
xtool unretweet ~/archive/rts.jsonl --expect-account yourhandle --rate 1
```

**Unlike everything:**

```bash
xtool parse ~/archive/data/like.js --likes -o ~/archive/likes.jsonl
xtool unlike ~/archive/likes.jsonl --expect-account yourhandle --rate 1
```

All three commands share the same flags: `--rate`, `--dry-run`,
`--resume`/`--no-resume`, `--yes`, `--expect-account`, `--log`.

---

## 11. Troubleshooting

### `authentication failed (HTTP 401)`

Your cookies expired. Log back into x.com in a browser, grab fresh
`auth_token` and `ct0`, rerun `xtool login`.

### `HTTP 429` errors in the log

You're being rate-limited. xtool backs off automatically using X's
`x-rate-limit-reset` header. If it's happening constantly:

- Lower `--rate` (try `0.5` = one request every 2 s).
- Wait ~15 minutes and resume the same log.

### `refusing to run at 5.0/s. Rates above 2.0/s are very likely to trigger …`

xtool is saving you from a suspension. Don't override this unless you
understand the risk (`--i-know-what-im-doing`).

### `account mismatch`

Good — this is xtool refusing to delete the wrong account's tweets.
Redo `xtool login` while logged into the *correct* account.

### Query ID stopped working

X rotates its GraphQL query IDs occasionally. xtool auto-discovers them
once a week. Force a refresh:

```bash
xtool discover --refresh
```

If that still doesn't help, pin a specific ID:

```bash
export XTOOL_DELETE_TWEET_QUERY_ID=<id-from-browser-devtools>
```

### `could not chmod 600`

Some Termux shared-storage paths (`/sdcard`) don't support POSIX
permissions. Move the file into `~/.xtool/` (Termux's private home,
which does):

```bash
mv /sdcard/cookies.json ~/.xtool/cookies.json
chmod 600 ~/.xtool/cookies.json
```

### A handful of tweets in `failed=` at the end

Usually tweets X's backend is confused about (deleted mid-run, or
protected). Rerun — `--resume` will skip the successful ones and retry
the failures.

---

## 12. Cleanup

When you're done:

```bash
# Remove cookies from disk
rm ~/.xtool/cookies.json

# Optional: wipe logs too
rm ~/deleted.jsonl ~/unretweeted.jsonl ~/unliked.jsonl
```

You may also want to invalidate the session on X itself — log out of
every device from
<https://x.com/settings/sessions> to rotate `auth_token`.

---

## One-shot script

Once you're comfortable, this is the whole thing as a single script:

```bash
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

HANDLE=yourhandle
ARCHIVE=~/archive/data/tweets.js

xtool parse  "$ARCHIVE" -o ~/archive/all.jsonl
xtool filter ~/archive/all.jsonl --to 2024-01-01 \
             -o ~/archive/to-delete.jsonl
xtool stats  ~/archive/to-delete.jsonl

# dry-run first, then pause for human review
xtool delete ~/archive/to-delete.jsonl --dry-run
read -rp "Continue for real? (yes/no): " go
[ "$go" = "yes" ] || exit 0

termux-wake-lock
xtool delete ~/archive/to-delete.jsonl \
      --expect-account "$HANDLE" --rate 1 --yes
termux-wake-unlock
```

Save as `clean.sh`, `chmod +x clean.sh`, run with `./clean.sh`.
