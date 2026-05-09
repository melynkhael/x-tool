# Finding auth_token, ct0, and twid in Firefox with Cookie-Editor

This guide is written for non-technical users. If you can install a
browser extension and copy-paste text, you can finish this in about
five minutes.

You do this **once**. After that, X-Tool remembers your cookies.

---

## Before you start

You will need:

- Firefox installed on a phone or computer
- An X (Twitter) account you are already logged in to
- Termux (or a terminal) open with `xtool` installed

If X-Tool is not installed yet, go back to the README first.

---

## Why three cookies?

X-Tool needs three values to act on your account:

- **auth_token** — required. This is your logged-in session token.
- **ct0** — required. This is an anti-forgery token X uses for writes.
- **twid** — optional but strongly recommended. It holds your numeric
  user ID and lets X-Tool confirm that the cookies belong to your
  account.

`auth_token` and `ct0` are enough to make X-Tool work. Adding `twid`
(and your @handle) lets X-Tool show **`Account: @yourhandle verified`**
in the menu, which turns on the full safety checks.

---

## Safety warning (read this)

Your cookies are the same thing as your password — someone who has
them can log in as you without knowing your password.

- **Never** share `auth_token`, `ct0`, or `twid` with anyone.
- Do **not** paste them into screenshots.
- Do **not** paste them into GitHub issues, Discord, Telegram, or any
  chat app.
- Do **not** paste them into online "cookie validators".
- If you are asked for them in a support thread, refuse — X-Tool will
  never need them in a public place.

If you ever accidentally share them, log out of X on all devices
(Settings → Security and account access → Apps and sessions → Log
out of all other sessions). That invalidates the old cookies.

---

## Step-by-step tutorial

### 1. Open Firefox

Open your Firefox browser. On Android, use **Firefox**, not the
built-in browser. On desktop, regular Firefox is fine.

### 2. Install the Cookie-Editor extension

Go to the official Firefox add-ons page and install Cookie-Editor:

- [https://addons.mozilla.org/firefox/addon/cookie-editor/](https://addons.mozilla.org/firefox/addon/cookie-editor/)

Click **Add to Firefox**, then **Add** when prompted.

Only install from this link (or from the Firefox Add-ons store). Do
not install a "Cookie-Editor" extension from any other source.

### 3. Open x.com and log in

Open [https://x.com](https://x.com) in Firefox and sign in to the
account you want X-Tool to clean.

Make sure you are signed in to the **correct** account. If you have
several X accounts, check the profile icon in the top right.

### 4. Open Cookie-Editor while on x.com

Stay on the x.com tab. Click the Cookie-Editor icon (it looks like a
small cookie). On Android Firefox, tap the menu (three dots) →
**Extensions** → **Cookie-Editor**.

Cookie-Editor will show a list of all cookies for the current site.
At the top of the list you should see something like:
`Cookies for .x.com`. If it says something else, you are not on the
x.com tab — close Cookie-Editor, switch to the x.com tab, and open
Cookie-Editor again.

### 5. Find and copy `auth_token`

In the Cookie-Editor search box, type:

```
auth_token
```

One cookie should appear. Click it to expand it. Copy **only the
value**, not the name.

The value is a long hex string, for example:

```
1a2b3c4d5e6f...
```

It is usually 40 characters long.

Tip: Cookie-Editor shows a small "copy" icon next to the value. Use
that — you will avoid selecting extra spaces by accident.

### 6. Find and copy `ct0`

Clear the search and type:

```
ct0
```

Click the cookie, copy **only the value**. `ct0` is usually 32–160
characters long.

### 7. Find and copy `twid`

Clear the search and type:

```
twid
```

Click the cookie, copy the value. It looks like this:

```
u=1234567890
```

The number after `u=` is your numeric X user ID.

It is fine to copy the whole `u=1234567890` form. X-Tool also accepts
just the number.

If you cannot find `twid`, you can skip it — X-Tool still works
without it, you just won't get the fully verified account banner.

### 8. Return to Termux (or your terminal)

Switch back to Termux (or whichever terminal you use) and bring up
X-Tool.

### 9. Run X-Tool

```bash
xtool
```

### 10. Choose option `1 Login / save cookies`

Press `1` and Enter.

### 11. Paste `auth_token` when asked

At the `auth_token` prompt, paste the value you copied in step 5.
You will not see anything as you paste — the prompt is intentionally
hidden for safety. Press Enter after pasting.

X-Tool prints back something like `auth_token captured: 40 chars`.
If the length looks wrong (for example, 3 chars), you probably only
copied part of the value — try again.

### 12. Paste `ct0` when asked

Same thing: paste the value from step 6, press Enter.

### 13. Paste `twid` when asked

Paste the value from step 7 and press Enter. If you could not find
`twid`, just press Enter to skip it.

### 14. Enter your X handle (without `@`)

When asked for your handle, type it without the `@`. For example,
if your handle is `@jane_doe`, type:

```
jane_doe
```

This is optional but recommended — it lets X-Tool check that the
cookies really belong to this handle.

### 15. Done

X-Tool prints `Verifying session with X...` and then shows your
account status in the menu header.

You should see one of:

- `Account: @yourhandle verified` — perfect, safety checks fully on
- `Account: user id ... from twid` — cookies work, you have the twid;
  add your handle to upgrade to verified
- `Account: cookies saved, identity not verified` — cookies work but
  X-Tool could not confirm the account. Try adding `twid` and your
  handle.

---

## What if I pasted the wrong value?

Just run option 1 again. The new cookies overwrite the old ones.

---

## What if my cookies stop working later?

Cookies expire when you log out of X, change your password, or after
a long time.

If X-Tool starts saying things like `authentication rejected` or
`cookies expired`:

1. Open Firefox.
2. Go to x.com and log in again (even if you look logged in, log out
   and back in to force a new session).
3. Redo this tutorial from step 4 to get fresh `auth_token`, `ct0`,
   and `twid` values.
4. Run `xtool`, choose option 1, and paste the new values.

---

## Clean up when you're done

If you finish cleaning and will not use X-Tool again for a while,
delete your saved cookies:

```bash
rm ~/.xtool/cookies.json
```

You can also log out of X on all devices to invalidate the cookies,
as described in the Safety warning above.

---

## Where to get help

- Troubleshooting: [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Safety notes: [docs/SAFETY.md](SAFETY.md)
- Bug reports: [https://github.com/melynkhael/x-tool/issues](https://github.com/melynkhael/x-tool/issues)
  (never include your cookies in an issue)
