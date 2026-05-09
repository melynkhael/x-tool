# Finding auth_token, ct0, and twid in Firefox

This is a beginner guide. You only need to do this once. It takes
about five minutes.

---

## What you will need

- Firefox on your phone or computer
- Your X (Twitter) account
- Termux (or any terminal) with X-Tool installed

If X-Tool is not installed yet, start with the [README](../README.md)
first.

---

## Why three cookies?

X-Tool needs three values from your logged-in browser session:

- `auth_token` — **required**. Your logged-in session token.
- `ct0` — **required**. A security token used for any write action.
- `twid` — **optional** but strongly **recommended**. It holds your
  internal user ID and lets X-Tool verify the account.

`auth_token` and `ct0` are enough to make X-Tool work. Adding `twid`
(and your @handle) lets X-Tool show `Account: @yourhandle` in the
menu, which turns on the full safety checks.

---

## Safety first

Your cookies are as sensitive as your password. Anyone who has them
can act as you on X.

**Never share** `auth_token`, `ct0`, or `twid`.

Never paste them into:

- screenshots
- github issues
- discord chats
- telegram chats
- reddit threads
- "online cookie checker" websites

If you ever share them by mistake, log out of X on all devices right
away. That invalidates the old cookies.

---

## Step-by-step tutorial

### 1. Open Firefox

If you do not have Firefox, install it. On Android, use the real
Firefox app from the official store.

### 2. Install the Cookie-Editor extension

Open this link in Firefox:

[https://addons.mozilla.org/firefox/addon/cookie-editor/](https://addons.mozilla.org/firefox/addon/cookie-editor/)

Tap or click **Add to Firefox**, then confirm.

Only install from this link. Do not use unknown "cookie editor"
copies.

### 3. Open x.com

Open a new tab and go to:

```
https://x.com
```

### 4. Log in to your X account

Sign in to the account you want X-Tool to clean. If you use more
than one account, check that you are on the correct one.

### 5. Open Cookie-Editor while still on x.com

Stay on the x.com tab.

- On desktop: click the small cookie icon in the Firefox toolbar.
- On Android: tap the menu (three dots), then Extensions, then
  Cookie-Editor.

You should see cookies for `.x.com` at the top of the list.

### 6. Find auth_token

In the Cookie-Editor search box, type:

```
auth_token
```

Tap or click the result.

Copy the **value**, not the name.

Tip: use Cookie-Editor's copy icon. It avoids copying extra spaces.

### 7. Copy auth_token's value (not its name)

Make sure you copy the long string of letters and numbers under
"Value", not the word `auth_token` itself.

### 8. Find ct0

Clear the search. Type:

```
ct0
```

Tap or click the result.

### 9. Copy ct0's value (not its name)

Copy the **value** only.

### 10. Find twid

Clear the search. Type:

```
twid
```

Tap or click the result.

### 11. Copy twid's value (not its name)

Copy the value. It looks like `u=...`. That is normal.

If you cannot find `twid`, you can skip it. X-Tool still works, but
identity verification will be weaker.

### 12. Switch back to Termux

Open Termux (or your terminal).

### 13. Run X-Tool and choose login

```
xtool
```

Then choose:

```
1 Login / save cookies
```

### 14. Paste each cookie when asked

1. Paste `auth_token` and press Enter.
2. Paste `ct0` and press Enter.
3. Paste `twid` and press Enter (or just press Enter to skip).
4. Enter your X handle without the `@`.

### 15. Done

X-Tool will check your session with X and show the account state at
the top of the menu. If everything worked, you will see:

```
Account: @yourhandle
```

That means your cookies are saved and your account is verified.

---

## Why the screen looks empty while you paste

Hidden input is normal. The cookie values will not appear on screen
as you paste. This is a safety feature so nobody looking over your
shoulder can read them.

X-Tool will print a short confirmation after each paste, like:

```
auth_token captured: 40 chars
```

If the number of characters looks too small (for example, `3 chars`),
you probably only copied part of the value. Try again.

---

## What if cookies stop working later?

Cookies expire when you log out, change your password, or after a
long time.

If X-Tool starts saying `authentication rejected` or `cookies
expired`, repeat this guide with fresh values.

---

## Remove saved cookies when you are done

If you finish cleaning and will not use X-Tool for a while, you can
delete your saved cookies:

```
rm ~/.xtool/cookies.json
```

You can also log out of X on all devices to invalidate them.

---

## Where to get help

- [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) — common fixes
- [docs/SAFETY.md](SAFETY.md) — safety notes
- [GitHub issues](https://github.com/melynkhael/x-tool/issues) — bug
  reports (never include cookies in an issue)
