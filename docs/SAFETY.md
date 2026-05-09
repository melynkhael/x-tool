# Safety

This is a short guide to using X-Tool safely. Please read it before
your first real cleanup.

---

## The one-sentence summary

Always **dry-run** first, never share your cookies, and remember that
deleted tweets cannot be undone.

---

## Deletion is permanent

X does not keep a trash bin for deleted tweets. Once X-Tool (or anyone
else) deletes a tweet, it is gone.

Before you start:

- Make sure you have your X archive saved locally. The archive is
  your only offline record.
- If there are tweets you want to keep (a pinned thread, a favourite
  reply), note down their IDs first and use the `--keep-ids` filter
  to exclude them.
- Run a **dry-run** before every real run. A dry-run touches nothing
  on X and tells you exactly what would be deleted.

---

## Your cookies are sensitive

`auth_token`, `ct0`, and `twid` give full access to your X session.

- Treat them like your password.
- Do **not** share them anywhere public — screenshots, GitHub issues,
  Discord, Telegram, Reddit, chat logs.
- Do **not** paste them into random websites or "cookie validators".
- If you ever leak them, log out of X on all devices right away
  (Settings → Security and account access → Apps and sessions → Log
  out of all other sessions). That invalidates the leaked cookies.

X-Tool stores your cookies only in `~/.xtool/cookies.json`, with file
permissions restricted to your user account (`chmod 600` where the
filesystem supports it). Nothing is sent to any third party.

---

## Account verification states

The menu header shows one of four states:

| State                                           | What it means                                                                            |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `Account: not logged in`                        | No cookies saved. Run option 1.                                                          |
| `Account: cookies saved, identity not verified` | `auth_token` and `ct0` are saved, but X-Tool cannot prove which account they belong to.  |
| `Account: user id ... from twid`                | `twid` is saved and gives the numeric user ID. Add your @handle to upgrade to verified.  |
| `Account: @handle verified`                     | Identity confirmed. Safety checks are fully active.                                      |

Only the last state turns on all safety checks. In the other states
X-Tool still works, but it cannot double-check that the cookies belong
to the account you think they do. Always use dry-run first.

---

## Rate limiting

X enforces rate limits. X-Tool defaults to one action per second,
which is safe. Do not raise `--rate` above the built-in safety ceiling
unless you know what you are doing — the risk is a temporary account
lock, not faster cleanup.

---

## Terms of Service

Automating actions on X may violate X's Terms of Service. By using
X-Tool you take on that risk. Read X's current Terms before running
mass actions on your account.

---

## Cleanup checklist

Before a real run:

- [ ] I downloaded my archive from X.
- [ ] I ran `xtool` and logged in (option 1).
- [ ] The menu header says `@handle verified` (ideally).
- [ ] I ran a **dry-run** first and the count looked right.
- [ ] I understand deletion is permanent.

After a cleanup:

- [ ] I expected the profile counters to take minutes/hours to catch up.
- [ ] I ran `xtool` again and the numbers matched.
- [ ] If I'm done with X-Tool for a while, I can delete my cookies:
      `rm ~/.xtool/cookies.json`.
