# X-Tool
X / Twitter Account Cleanup
by: melynkhael

A beginner-friendly tool that helps you clean up **your own** X (Twitter)
account. Delete old tweets, remove replies, undo reposts, and clear
likes — from a simple menu on your phone or computer.

---

## What this tool does

- Deletes tweets and replies from your account
- Removes your reposts (retweets)
- Removes your likes
- Works from your downloaded X archive, so it can reach tweets the
  API can no longer list
- Runs from a single command: `xtool`
- Shows a menu — you do not need to remember any commands
- Has a **dry-run** mode so you can preview what will happen before
  anything is deleted
- Runs on Android (Termux), Linux, macOS, and WSL

---

## Safety warning

This tool only works on your **own** account. It uses **your** session
cookies — it cannot touch anyone else's account.

Please read this before using it:

- Deleted tweets **cannot be recovered**. Always run a **dry-run**
  first.
- Never share your `auth_token`, `ct0`, or `twid` cookies with anyone.
  They give full access to your X session.
- X's profile counters (tweet count, likes count) are cached and may
  take minutes or hours to update after a cleanup.
- Automating actions on X may violate X's Terms of Service. You use
  this tool at your own risk.

See [docs/SAFETY.md](docs/SAFETY.md) for more.

---

## What you need

1. A logged-in X account (this is your account — the one you want
   to clean).
2. A copy of your X archive (X Settings → Your Account → Download an
   archive of your data).
3. Python 3.9 or newer.
4. About 10 minutes for the first run.

On Android, you'll also need the [Termux](https://f-droid.org/en/packages/com.termux/)
app (install from F-Droid, **not** the Play Store — the Play Store
version is out of date).

---

## Install on Termux

```bash
pkg update && pkg upgrade -y
pkg install python python-pip git -y
git clone https://github.com/melynkhael/x-tool.git ~/x-tool
cd ~/x-tool
bash install.sh
```

That's it. Type `xtool` to open the menu.

For a longer walkthrough (including how to move your archive onto
your phone), see [TERMUX_GUIDE.md](TERMUX_GUIDE.md).

---

## Update X-Tool

The easiest way:

```bash
xtool update
```

This prints just a few short progress lines. Real errors are still
shown, so you can tell the difference between "all good" and
"something needs fixing".

If `xtool update` cannot run (for example, you installed from a pip
URL instead of a git clone), use:

```bash
cd ~/x-tool
git pull --ff-only --quiet origin main
bash install.sh --quiet
```

---

## Start the menu

```bash
xtool
```

You'll see something like this:

```
 X-Tool — X / Twitter Account Cleanup  v0.2.4
  by: melynkhael

  Account: not logged in

  What would you like to do?

   1  Login / save cookies
   2  Load X archive
   3  Show archive stats
   4  Delete tweets
   5  Delete replies
   6  Delete tweets and replies
   7  Remove reposts
   8  Remove likes
   9  Full cleanup (guided)
   u  Update X-Tool
   t  Troubleshooting
   0  Exit
```

Type a number (or letter) and press Enter.

---

## Login / save cookies

Choose option **1** in the menu.

X-Tool needs three cookies from your browser session:

- `auth_token` — required
- `ct0` — required
- `twid` — optional, but **strongly recommended** so X-Tool can
  verify which account the cookies belong to

The easiest way to get them is the **Cookie-Editor** browser extension.

See the full step-by-step tutorial:
**[docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md)**

**Never** share these values with anyone. Do not paste them into
screenshots, GitHub issues, Discord, Telegram, or public chats.

---

## How to find auth_token, ct0, and twid using Firefox + Cookie-Editor

Quick version:

1. Open Firefox.
2. Install the Cookie-Editor extension from
   [addons.mozilla.org](https://addons.mozilla.org/firefox/addon/cookie-editor/).
3. Open [https://x.com](https://x.com) and log in to your X account.
4. Click the Cookie-Editor icon while still on x.com.
5. Find `auth_token` and copy its **value** (not the name).
6. Find `ct0` and copy its **value**.
7. Find `twid` and copy its **value** (looks like `u=1234567890`).
8. Back in Termux, run `xtool` and choose **1 Login / save cookies**.
9. Paste each value when prompted.
10. Enter your X handle (without the `@`) when asked.

Full tutorial with screenshots and warnings:
[docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md).

---

## How to load your X archive

1. In X: Settings → Your Account → Download an archive of your data.
2. Wait for the email from X. Download the ZIP to your device.
3. On Android, copy it to your home folder and unzip it:
   ```bash
   cp /storage/emulated/0/Download/twitter-archive.zip ~/
   cd ~
   unzip twitter-archive.zip -d x-archive
   ```
4. In the menu, choose **2 Load X archive** and enter the folder
   path (for example: `~/x-archive`).

X-Tool looks for `data/tweets.js`, `data/tweet.js`, and
`data/like.js` automatically.

---

## How to remove reposts

1. Log in (option 1).
2. Choose **7 Remove reposts**.
3. Enter your X handle (without the `@`).
4. X-Tool walks your live profile timeline to find the real source
   tweet IDs.
5. Review the count, confirm, and let it run.

Reposts use a special resolver because the archive only contains
wrapper IDs that will not work for the undo action.

---

## How to remove likes

1. Make sure your archive is loaded (option 2).
2. Choose **8 Remove likes**.
3. Review the count, dry-run if you want, confirm, and let it run.

---

## How to delete tweets/replies

1. Load your archive (option 2).
2. Choose one of:
   - **4 Delete tweets** — original tweets only
   - **5 Delete replies** — replies only
   - **6 Delete tweets and replies**
3. Dry-run first, then confirm to delete for real.

---

## Full cleanup guided mode

Choose **9 Full cleanup (guided)**.

X-Tool walks you through:

1. Delete tweets
2. Delete replies
3. Remove reposts
4. Remove likes

Each step lets you say yes or no, so you stay in control.

---

## Dry-run vs real run

**Always dry-run first.** A dry-run:

- Counts what would change
- Writes a log to `~/.xtool/logs/`
- Does **not** contact X for deletions
- Does **not** change anything on your account

Only after a dry-run looks correct should you answer `yes` to the
real run. Deleted tweets cannot be recovered.

---

## Troubleshooting

Some common states you may see at the top of the menu:

- `Account: not logged in` — No cookies saved. Run option 1.
- `Account: cookies saved, identity not verified` — auth_token and
  ct0 are saved, but X-Tool cannot prove which account they belong
  to. Add **twid** and your **handle** in option 1 to improve this.
- `Account: user id ... from twid` — The `twid` cookie tells us the
  numeric account ID, but the handle is not confirmed yet. Add your
  handle in option 1.
- `Account: @handle verified` — Identity confirmed. Safety checks
  are fully active.

If identity is not verified, your cookies may still work, but X-Tool
cannot prove which account they belong to. **Always use dry-run first.**

Full list of common problems and fixes:
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## FAQ

**Is this safe?**
It runs 100% on your device. Your cookies never leave your machine.
But deleted tweets are gone forever — always dry-run first.

**Do I need an API key?**
No. X-Tool uses the same web session your browser uses (cookies only).

**Why do I need cookies and not a password?**
X's web client authenticates with session cookies. No password is
stored or sent by X-Tool.

**My repost count didn't go down.**
X caches profile counters. Wait 5–30 minutes and refresh.

**Can I undo a deletion?**
No. That's why dry-run exists.

**Does it work on Android?**
Yes, via Termux. See [TERMUX_GUIDE.md](TERMUX_GUIDE.md).

More questions and answers: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Advanced (optional)

For power users, every menu action is also a CLI command. See
`xtool --help` for the full list (`parse`, `stats`, `filter`,
`delete`, `unretweet`, `unlike`, `resolve-retweets`, `discover`,
`whoami`, `update`).

---

## License

[MIT](LICENSE). See also [SECURITY.md](SECURITY.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).
