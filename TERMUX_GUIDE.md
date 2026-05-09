# X-Tool on Termux (Android)

Complete guide to running X-Tool on Android via Termux.

---

## Prerequisites

1. Install [Termux](https://f-droid.org/en/packages/com.termux/) from F-Droid (not Play Store).
2. Open Termux and run the initial setup below.

---

## Installation

```bash
# Update packages
pkg update && pkg upgrade -y

# Install dependencies
pkg install python python-pip git -y

# Clone and install
git clone https://github.com/melynkhael/x-tool.git ~/x-tool
cd ~/x-tool
bash install.sh
```

### Verify installation

```bash
xtool --version
```

---

## Setup

### 1. Get your X cookies

1. Open **Chrome** or **Firefox** on your phone/tablet.
2. Go to [https://x.com](https://x.com) and log in.
3. For Chrome on Android:
   - Type `chrome://inspect` in a new tab (or use a desktop browser with USB debugging).
   - Alternatively, use a cookie viewer extension.
4. You need two values: **auth_token** and **ct0**.

### 2. Save cookies

```bash
xtool login
```

Or use the interactive menu:

```bash
xtool
# Choose option 1
```

---

## Usage

### Interactive mode (easiest)

```bash
xtool
```

Follow the on-screen menu.

### Transfer your X archive

1. Download your X archive from: **X Settings > Your Account > Download an archive**
2. Transfer the ZIP to your phone.
3. Extract it:

```bash
# If the zip is in Downloads:
cp /storage/emulated/0/Download/twitter-archive.zip ~/
cd ~
unzip twitter-archive.zip -d x-archive
```

4. In X-Tool, load the archive:

```bash
xtool
# Choose option 2, enter: ~/x-archive
```

---

## Updating

```bash
cd ~/x-tool
git pull --ff-only origin main
bash install.sh
```

---

## Tips

- **Storage access**: Run `termux-setup-storage` once to access `/storage/emulated/0/`.
- **Keep screen on**: Long operations can take minutes. Disable phone sleep or use `termux-wake-lock`.
- **Background**: Use `tmux` or `screen` to keep sessions alive if you switch apps.
- **Rate**: Default 1 request/sec is safe. Don't go higher.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `pip: command not found` | `pkg install python-pip` |
| `permission denied` on cookies | Normal on shared storage. Cookies still work. |
| Phone sleeps during operation | Run `termux-wake-lock` before starting |
| `rust` build errors | `pkg install rust` then retry install |
| Can't find archive | Use `ls ~/x-archive/data/` to verify files exist |

---

## Uninstall

```bash
pip uninstall xtool -y
rm -rf ~/x-tool
rm -rf ~/.xtool
```
