# Troubleshooting

Find your problem below, try the fix, and if you are still stuck,
open an issue at
[https://github.com/melynkhael/x-tool/issues](https://github.com/melynkhael/x-tool/issues).

Never include your cookies, tokens, or numeric user ID in an issue.

Always use **dry-run** first before running any real cleanup.

---

## Account status meanings

The menu header shows one of these states.

**Account: not logged in**
No cookies saved yet. Choose option `1 Login / save cookies`.

**Account: cookies saved, identity not verified**
`auth_token` and `ct0` are saved, but X-Tool cannot confirm the
account. Paste `twid` and enter your handle in option `1` to fix
this.

**Account: user id ... from twid**
`twid` is saved and gives the numeric account ID, but the handle is
not matched yet. Enter your handle in option `1`.

**Account: @handle**
Your account is verified. Safety checks are fully active.

Only the `@handle` state turns on all safety checks. In the other
states X-Tool still works, but cannot fully confirm that the cookies
belong to the account you think. Always use dry-run first.

---

## Login failed

Most of the time, your cookies have expired.

1. Log out of x.com in Firefox.
2. Log back in.
3. Redo [docs/FIREFOX_COOKIE_EDITOR.md](FIREFOX_COOKIE_EDITOR.md) to
   copy fresh `auth_token`, `ct0`, and `twid`.
4. Run `xtool` and choose `1 Login / save cookies`.
5. Paste the new values.

---

## Cookies saved but identity not verified

You see this state:

```
Account: cookies saved, identity not verified
```

Fix: run option `1` again. This time also paste `twid` and enter
your X handle without the `@`.

Your cookies may still work. X-Tool just turns off the strongest
safety check in this state. Always use dry-run first.

---

## twid found but handle not verified

You see a state like this:

```
Account: user id ... from twid
```

Meaning: X-Tool knows your internal account ID but has not matched
it to your handle yet.

Fix: choose option `1` and enter your handle without the `@`.

---

## Archive not found

X-Tool looks for your archive files inside the folder you give it.
You need to point it at the **extracted folder**, not the ZIP.

Example:

```
cp /storage/emulated/0/Download/twitter-archive.zip ~/
cd ~
unzip twitter-archive.zip -d x-archive
```

Then in the menu, enter:

```
~/x-archive
```

If it still fails, check that one of these files exists:

- `x-archive/data/tweets.js`
- `x-archive/data/tweet.js`
- `x-archive/data/like.js`
- `x-archive/data/likes.js`

---

## Reposts still visible after running

X caches profile counters. It can take several minutes to update.

If reposts still show after waiting, run `7 Remove reposts` again.
X-Tool will skip ones it already removed and process anything new.

---

## Likes still visible after running

Same reason. Wait 5–30 minutes and refresh.

If some likes are never removed, they may belong to protected or
deleted accounts. X-Tool counts those as `not_liked`, which is
normal.

---

## X counter still shows old numbers

X's profile numbers are cached. This can take minutes or even hours
to update, even when the tweets are already gone.

Check one individual tweet — if it opens as "tweet not found", then
it really is deleted. The counter will catch up later.

---

## xtool update failed

Use the fallback commands:

```
cd ~/x-tool
```

```
git pull --ff-only --quiet origin main
```

```
bash install.sh --quiet
```

If `git pull` fails, check:

- You have internet.
- You are inside the `~/x-tool` folder.
- You did not edit any files inside the folder.

---

## Permission warning in xtool doctor

If `xtool doctor` shows warnings about file or folder permissions,
the fix is usually:

```
xtool doctor --fix
```

This command only adjusts permissions. It never deletes files and
never contacts the network.

If it still warns after a fix, your device or storage may not
support POSIX permissions. This is common on Android shared storage.
Your cookies still work — but it is safer to keep them under
`~/.xtool/` on the Termux home folder, not on shared storage.

---

## Rate limited

X limits how often you can act.

- Wait about 15 minutes.
- Run the same option again. X-Tool will skip the items it already
  handled.
- Do not raise the rate manually — you may get your account
  temporarily locked.

---

## Query ID errors (HTTP 422)

X rotates internal IDs sometimes. Refresh them:

```
xtool discover --refresh
```

Then run the cleanup again.

---

## Cannot reach x.com

Check:

- You have network.
- No VPN is blocking x.com.
- You are not behind a captive portal (try opening x.com in Firefox
  first).

X-Tool talks only to `x.com`, `twitter.com`, and `api.twitter.com`.

---

## Termux specific

**`pip: command not found`**

```
pkg install python-pip
```

**Phone sleeps mid-run**

```
termux-wake-lock
xtool
```

Run `termux-wake-unlock` when done.

---

## Still stuck?

Open an issue:
[https://github.com/melynkhael/x-tool/issues](https://github.com/melynkhael/x-tool/issues)

Include:

- What you tried (menu option or command)
- What happened (the exact error text)
- Your operating system or Termux version
- The output of `xtool --version`

Never include `auth_token`, `ct0`, `twid`, numeric user IDs, or any
of the `cookies.json`, `identity.json`, or `query_ids.json` files.
