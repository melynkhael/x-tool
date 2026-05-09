# X-Tool
X / Twitter Account Cleanup
by: melynkhael

X-Tool helps you clean your own X / Twitter account from a simple
terminal menu. It can delete tweets, delete replies, remove reposts,
and remove likes. It walks you through each step, so you do not need
to know any commands.

Current version: v0.2.5

---

## What this tool does

- Delete tweets
- Delete replies
- Remove reposts (retweets)
- Remove likes
- Run a guided full cleanup
- Work on Android with Termux
- Use dry-run before any real action

---

## Safety warning

- Only use X-Tool on your own account.
- Deleted tweets cannot be recovered.
- Never share your `auth_token`, `ct0`, `twid`, `cookies.json`,
  `identity.json`, or `query_ids.json`.
- Always run a dry-run first.
- You use this tool at your own risk.

Full safety guide: [docs/SAFETY.md](docs/SAFETY.md)

---

## What you need

- Android with Termux, or Linux / macOS / WSL
- Python 3.9 or newer
- Git
- Your own X account
- Your X archive (needed if you want to delete tweets, replies, or
  likes based on archive data)

---

## Install on Termux

Follow the steps below one by one. Each command is on its own line,
so it is easy to copy on your phone.

**Step 1 — Update Termux**

```
pkg update && pkg upgrade -y
```

**Step 2 — Install requirements**

```
pkg install python python-pip git -y
```

**Step 3 — Clone X-Tool**

```
git clone https://github.com/melynkhael/x-tool ~/x-tool
```

**Step 4 — Open the folder**

```
cd ~/x-tool
```

**Step 5 — Install X-Tool**

```
bash install.sh
```

**Step 6 — Start X-Tool**

```
xtool
```

That is all. The menu will open.

Need more detail for Android? See [TERMUX_GUIDE.md](TERMUX_GUIDE.md).

---

## Update X-Tool

Use this when you already installed X-Tool before and want the latest
version.

Main command:

```
xtool update
```

If `xtool update` does not work, use this fallback:

```
cd ~/x-tool
```

```
git pull --ff-only --quiet origin main
```

```
bash install.sh --quiet
```

---

## Start the menu

```
xtool
```

You will see something like this:

```
 X-Tool — X / Twitter Account Cleanup  v0.2.5
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

Type the number or letter, then press Enter.

---

## Login / save cookies

Follow these steps once:

1. Run `xtool`.
2. Choose `1 Login / save cookies`.
3. Paste `auth_token` when asked.
4. Paste `ct0` when asked.
5. Paste `twid` if you have it.
6. Enter your X handle without `@`.

Important:

- `auth_token` and `ct0` are required.
- `twid` is optional but strongly recommended. It helps X-Tool verify
  your account.
- Hidden input is normal. The cookie text will not appear on screen
  while you paste. That is a safety feature.

For the full cookie tutorial, see
[docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md).

---

## How to find auth_token, ct0, and twid using Firefox + Cookie-Editor

Quick version:

1. Open Firefox.
2. Install the Cookie-Editor extension from
   [addons.mozilla.org](https://addons.mozilla.org/firefox/addon/cookie-editor/).
3. Open [https://x.com](https://x.com) and log in.
4. Open Cookie-Editor while still on x.com.
5. Find `auth_token` and copy its **value** (not the name).
6. Find `ct0` and copy its **value**.
7. Find `twid` and copy its **value**.
8. Go back to Termux and paste them into X-Tool when it asks.

For full screenshots and detailed steps, read
[docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md).

---

## How to load your X archive

Some cleanups (tweets, replies, likes) use your X archive.

Steps:

1. Download your X archive from your X account settings.
2. Move the archive ZIP to your phone storage.
3. In Termux, copy it to your home folder and unzip it.
4. Open `xtool`.
5. Choose `2 Load X archive`.
6. Enter the folder path when asked.

Need help moving files on Android? See
[TERMUX_GUIDE.md](TERMUX_GUIDE.md).

---

## How to remove reposts

1. Choose `1` and login.
2. Choose `7 Remove reposts`.
3. Enter your X handle without `@`.
4. Review the dry-run.
5. Type `yes` only if the result looks correct.

---

## How to remove likes

1. Choose `2` and load your X archive.
2. Choose `8 Remove likes`.
3. Review the dry-run.
4. Type `yes` only if the result looks correct.

---

## How to delete tweets/replies

Delete tweets:

1. Choose `2` and load your X archive.
2. Choose `4 Delete tweets`.
3. Review the dry-run.
4. Type `yes` only if the result looks correct.

Delete replies:

1. Choose `2` and load your X archive.
2. Choose `5 Delete replies`.
3. Review the dry-run.
4. Type `yes` only if the result looks correct.

---

## Full cleanup guided mode

1. Choose `9 Full cleanup (guided)`.
2. Follow each step.
3. Say yes or no for each action.

---

## Dry-run vs real run

A dry-run shows what X-Tool would do, without changing your account.
A real run only happens after you confirm by typing `yes`.

Always check the dry-run first.

---

## Account status meanings

You will see one of these lines at the top of the menu.

**Account: not logged in**
No cookies saved. Choose option `1`.

**Account: cookies saved, identity not verified**
Cookies are saved, but X-Tool cannot confirm the account yet. Add
`twid` and your handle in option `1`.

**Account: twid found, handle not verified**
X-Tool found your account's internal ID, but has not matched it to
your handle yet. Enter your handle in option `1`.

**Account: @handle**
X-Tool verified your account. All safety checks are on.

---

## Security check

X-Tool has a built-in security check.

Run it with:

```
xtool doctor
```

If it says `0 warnings` and `0 critical`, your local X-Tool files
look safe.

If there are warnings, you can try:

```
xtool doctor --fix
```

This fixes local file permissions when possible. It never deletes
files and never contacts the network.

---

## Troubleshooting

**Login failed**
Your cookies may have expired. Log in to x.com again in Firefox,
copy fresh cookies, and redo option `1`.

**Account not verified**
Make sure you pasted `twid` and entered your handle. See
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for details.

**X profile count still shows old number**
X caches profile counters. Wait 5–30 minutes, then refresh.

**Archive not found**
Make sure you extracted the ZIP and that a `data` folder exists
inside. Enter the extracted folder path, not the ZIP.

**xtool update failed**
Use the fallback commands in the "Update X-Tool" section above.

Full list of problems and fixes:
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## FAQ

**Is this safe?**
It runs only on your device. Your cookies never leave your machine.
Deleted tweets are gone forever, so always use dry-run first.

**Can deleted tweets be recovered?**
No. There is no trash bin on X.

**Do I need an API key?**
No. X-Tool uses the same web session your browser uses.

**Why do I need cookies?**
X's web client uses session cookies. No password is stored or sent
by X-Tool.

**Does it work on Android?**
Yes, through Termux. See [TERMUX_GUIDE.md](TERMUX_GUIDE.md).

**Why is the X post count still showing old numbers?**
X caches profile counters. It can take minutes to hours to catch up.

---

## Advanced usage

Advanced users can still use CLI commands directly.

```
xtool --help
```

This shows every subcommand (`parse`, `stats`, `filter`, `delete`,
`unretweet`, `unlike`, `resolve-retweets`, `discover`, `whoami`,
`update`, `doctor`).

Each subcommand has its own help too:

```
xtool delete --help
```

---

## License

[MIT](LICENSE). See also [SECURITY.md](SECURITY.md).

This project is maintained privately by melynkhael. Public contributions are
not currently accepted.
