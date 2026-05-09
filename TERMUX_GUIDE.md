# X-Tool on Android (Termux)

Step-by-step guide for running X-Tool on Android.

If you just want to start quickly, follow the main [README](README.md)
install steps. This guide has extra Android-specific notes.

---

## What you need

- An Android phone or tablet
- Termux app installed
- An X account
- Your X archive (only needed if you plan to delete tweets, replies,
  or likes from archive data)

---

## Install Termux

Install Termux from F-Droid:

[https://f-droid.org/en/packages/com.termux/](https://f-droid.org/en/packages/com.termux/)

Do not install Termux from the Play Store. That version is outdated.

Open Termux after installing.

---

## Install X-Tool

Follow these steps one by one.

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

**Step 6 — Check the install**

```
xtool --version
```

You should see something like:

```
xtool 0.2.5
```

---

## Start the menu

```
xtool
```

Use the numbers and letters on screen. Type the key and press Enter.

---

## Get your cookies

You need three cookies from x.com: `auth_token`, `ct0`, and `twid`.

The safest way to get them is with Firefox and the Cookie-Editor
extension. See the full guide:

[docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md)

After you have them, go to Termux and choose `1 Login / save
cookies` in the menu.

---

## Move your X archive to the phone

You only need this if you want to clean tweets, replies, or likes
using your archive data.

**Step 1 — Allow Termux to access phone storage**

Run this only once:

```
termux-setup-storage
```

Allow storage access when your phone asks.

**Step 2 — Copy the archive ZIP from Downloads**

```
cp /storage/emulated/0/Download/twitter-archive.zip ~/
```

**Step 3 — Open your home folder**

```
cd ~
```

**Step 4 — Unzip the archive**

```
unzip twitter-archive.zip -d x-archive
```

**Step 5 — Load the archive in X-Tool**

Run:

```
xtool
```

Choose:

```
2 Load X archive
```

When X-Tool asks for the path, type:

```
~/x-archive
```

---

## Update X-Tool

Main command:

```
xtool update
```

If `xtool update` does not work, use the fallback:

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

## Keep the phone awake

Long cleanups can take a while. Android may put the phone to sleep.

Start this before running long actions:

```
termux-wake-lock
```

Run this when you are done:

```
termux-wake-unlock
```

---

## Remove X-Tool

If you want to remove X-Tool completely:

```
pip uninstall xtool -y
```

```
rm -rf ~/x-tool
```

```
rm -rf ~/.xtool
```

This deletes the code, your saved cookies, and your saved identity
metadata.

---

## Where to go next

- Main README: [README.md](README.md)
- Safety: [docs/SAFETY.md](docs/SAFETY.md)
- Cookie guide: [docs/FIREFOX_COOKIE_EDITOR.md](docs/FIREFOX_COOKIE_EDITOR.md)
- Troubleshooting: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
