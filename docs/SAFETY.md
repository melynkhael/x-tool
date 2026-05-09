# Safety

A short guide to using X-Tool safely. Please read this before your
first real cleanup.

---

## One-sentence summary

Always dry-run first, never share your cookies, and remember that
deleted tweets cannot be undone.

---

## What cookies are

X-Tool uses three session cookies from your logged-in X browser
session:

- `auth_token` — required. Your logged-in session token.
- `ct0` — required. A security token X uses for any write action.
- `twid` — optional but strongly recommended. It holds your internal
  user ID and helps X-Tool verify the account.

These cookies let X-Tool act on your account the same way your own
browser does. They do not include your password, but they give the
same access.

---

## Why they are sensitive

Anyone who has `auth_token` and `ct0` can act as you on X without a
password.

Treat them like your password.

---

## What not to share

Never share or post any of these:

- `auth_token`
- `ct0`
- `twid`
- `cookies.json`
- `identity.json`
- `query_ids.json`
- Your numeric X user ID from `twid`

Do not:

- Paste them in screenshots.
- Paste them in GitHub issues, Discord, Telegram, or any chat app.
- Paste them into random "cookie validator" websites.
- Send them to anyone asking for them in a support thread.

If you ever share them by mistake, log out of X on all devices
(X Settings → Security and account access → Apps and sessions → Log
out of all other sessions). That invalidates the old cookies.

---

## Why dry-run matters

Deletion is permanent. X does not keep a trash bin.

A dry-run:

- Tells X-Tool to count what would change.
- Writes a plan to your logs.
- Does not contact X for any delete action.
- Does not change your account.

Only after a dry-run looks correct should you type `yes` for a real
run.

---

## What xtool doctor checks

Run this anytime:

```
xtool doctor
```

It checks:

- That the `~/.xtool/` folder is private.
- That `cookies.json`, `identity.json`, and `query_ids.json` have
  safe file permissions.
- That X-Tool's log files have safe permissions.
- That your shell history does not appear to contain cookies.
- That no sensitive files are accidentally tracked by git.
- That `identity.json` does not contain credential fields.

It never prints the actual secret values, only file names and
permission status.

If it finds problems you can try:

```
xtool doctor --fix
```

This only adjusts file permissions. It never deletes or moves files.

---

## What files are stored in ~/.xtool

- `~/.xtool/cookies.json` — your saved cookies. Sensitive.
- `~/.xtool/identity.json` — your verified handle metadata. Not
  supposed to contain credentials.
- `~/.xtool/query_ids.json` — cached X query IDs. Not sensitive, but
  kept in the same folder for tidiness.
- `~/.xtool/logs/` — per-action log files. Sensitive fields are
  redacted before writing.

All of these live only on your device.

---

## Remove saved cookies

When you are done using X-Tool, or if you want to rotate cookies, you
can remove them:

```
rm ~/.xtool/cookies.json
```

You may also want to log out of X on all devices to make sure the
old cookies no longer work.

---

## Terms of Service

Automating actions on X may violate X's Terms of Service. By using
X-Tool you accept that risk. Read X's current Terms before running
any mass action.

---

## Cleanup checklist

Before a real run:

- I downloaded my archive from X.
- I ran `xtool` and chose `1 Login / save cookies`.
- The menu header shows `Account: @handle`.
- I ran a dry-run and the count looked correct.
- I understand deletion is permanent.

After a cleanup:

- I know that X profile counters update slowly.
- I may delete my cookies when I am done:

```
rm ~/.xtool/cookies.json
```
