# Troubleshooting

Most issues fall into one of the buckets below. Find the symptom, try
the fix, and if nothing works open an issue at
[https://github.com/melynkhael/x-tool/issues](https://github.com/melynkhael/x-tool/issues)
(never include your cookies).

---

## Login and identity

### The menu says `Account: not logged in`

You have not saved cookies yet. Choose menu option **1 Login / save
cookies** and follow
[docs/FIREFOX_COOKIE_EDITOR.md](FIREFOX_COOKIE_EDITOR.md).

### The menu says `Account: cookies saved, identity not verified`

`auth_token` and `ct0` are saved, but X-Tool could not prove which
account they belong to. This can happen when X's older identity
endpoints are unavailable.

Fix: run option 1 again and **also** paste `twid` and enter your
`@handle`. With those two extra values X-Tool can verify the account
through a different path.

Your cookies may still work — the tool just turns off the strongest
safety check. Always use **dry-run** first in this state.

### The menu says `Account: user id <number> from twid`

X-Tool knows the numeric user ID from your `twid` cookie, but the
handle has not been confirmed. Run option 1 and enter your `@handle`
(without the `@`). That should upgrade the status to
`@handle verified`.

### The menu says `Account: @handle verified`

All good. Safety checks are fully active.

### `authentication rejected` / cookies expired

X sessions expire. You need fresh cookies.

1. Log out of x.com in Firefox.
2. Log back in.
3. Redo [docs/FIREFOX_COOKIE_EDITOR.md](FIREFOX_COOKIE_EDITOR.md) to
   copy the new `auth_token`, `ct0`, and `twid`.
4. Run `xtool`, choose option 1, paste the new values.

---

## Running the actions

### `rate limited` errors during a bulk run

X limits roughly one action per second. If you see `rate limited`:

- Wait 15 minutes.
- Re-run — the resume feature skips anything already done.
- Do **not** raise `--rate` above the built-in safety ceiling.

### `query ID stale` / HTTP 422 GRAPHQL_VALIDATION_FAILED

X rotates internal IDs sometimes. Refresh them with:

```bash
xtool discover --refresh
```

Then re-run the action.

### Reposts still show on my profile

X caches profile counters aggressively. Wait 5–30 minutes and refresh.
If reposts persist, re-run **7 Remove reposts** — X-Tool will pick up
whatever is left.

### `unlike` prints `not_liked`

Normal. It means that specific tweet was already unliked, or the
author deleted it. X-Tool counts it as a success for idempotency.

---

## Archive problems

### X-Tool can't find my archive

X-Tool looks for these files under the folder you give it:

```
<folder>/data/tweets.js
<folder>/data/tweet.js
<folder>/data/like.js
<folder>/data/likes.js
```

Flat layouts (no `data/` subfolder) also work.

Fix: extract the archive ZIP, then give the **extracted folder** path
(not the ZIP). On Termux:

```bash
cp /storage/emulated/0/Download/twitter-archive.zip ~/
cd ~
unzip twitter-archive.zip -d x-archive
```

Then in the menu enter `~/x-archive` when asked for the path.

### Archive is old / missing recent tweets

Your archive is a snapshot from the day X built it. Anything posted
after that is not in the archive. For the most complete cleanup,
download a fresh archive before starting.

---

## Update problems

### `xtool update` says "not installed from a git checkout"

You installed X-Tool with `pip install git+https://...` instead of
cloning the repo. Two options:

Option A — reinstall over the top:

```bash
pip install --upgrade git+https://github.com/melynkhael/x-tool.git
```

Option B — switch to a git clone once (recommended for beginners):

```bash
git clone https://github.com/melynkhael/x-tool.git ~/x-tool
cd ~/x-tool
bash install.sh
```

After either option, `xtool update` will work.

### `git pull failed: ...`

Scroll up — X-Tool prints the actual git error. Common causes:

- **Local changes:** you edited files in `~/x-tool`. Either revert
  them (`git stash` or `git checkout -- .`), or move your edits to a
  branch first.
- **Merge conflict:** follow git's instructions to resolve, then
  re-run `xtool update`.
- **No network:** fix connectivity and retry.

### `pip install failed: ...`

Scroll up for the actual pip error. On Termux, common causes:

- Missing build tools: `pkg install rust openssl libexpat`.
- Out of disk space: `df -h ~` to check.

---

## Network

### Cannot reach x.com

Check that:

- You have network.
- A VPN is not rewriting x.com (some corporate VPNs do).
- You are not behind a captive portal — try opening x.com in the
  browser first.

X-Tool talks only to `x.com`, `twitter.com`, and `api.twitter.com`.

---

## Termux-specific

### `pip: command not found`

```bash
pkg install python-pip
```

### `termux-setup-storage` permission issues

Run `termux-setup-storage` once and allow storage access when
prompted. After that, `/storage/emulated/0/Download/` is accessible
from Termux.

### Phone sleeps mid-run

```bash
termux-wake-lock
xtool
```

Run `termux-wake-unlock` when you're done.

---

## Still stuck?

Open an issue at
[https://github.com/melynkhael/x-tool/issues](https://github.com/melynkhael/x-tool/issues)
and include:

- What you tried (menu option, command, etc.)
- What happened (exact error text)
- Your OS / Termux version
- `xtool --version`

**Never** include `auth_token`, `ct0`, or `twid` in an issue. If the
error message contains them, redact those parts first.
