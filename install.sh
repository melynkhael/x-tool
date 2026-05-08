#!/usr/bin/env bash
# Install script for x-tool on Termux / Linux / macOS / WSL.
#
# Termux-specific notes:
#   * pip is managed by the `python-pip` package; `pip install --upgrade
#     pip` is forbidden and makes the package database inconsistent.
#   * On Termux we also need `libexpat`, `openssl` and `rust` to build
#     some transitive deps of `requests` / `rich` from source.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

is_termux() { command -v pkg >/dev/null 2>&1 && [ -n "${PREFIX:-}" ] && [[ "$PREFIX" == *"/com.termux/"* ]]; }

if is_termux; then
    echo "==> Detected Termux environment"
    # python-pip is the Termux package that owns pip; installing it
    # guarantees we never try to bootstrap pip via ensurepip.
    pkg install -y python python-pip git libexpat openssl
    # xtool itself is pure-Python, but some wheels on Termux have no
    # prebuilt binaries and fall back to source; rust is needed for
    # those (e.g. `cryptography` transitive). Safe to install lazily.
    command -v rustc >/dev/null 2>&1 || pkg install -y rust || true
else
    # Non-Termux: be helpful if we can detect a system package manager,
    # but don't fail if we can't.
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 not found. Install Python 3.9+ and re-run." >&2
        exit 1
    fi
fi

# Pick the right interpreter. Termux's `python` is Python 3.
PY="$(command -v python3 || command -v python)"

# DO NOT run `pip install --upgrade pip` here: Termux forbids it, and
# on system Python it needs --user or a venv which we don't want to
# assume. xtool supports any pip from the last ~5 years.

echo "==> Installing xtool"
"$PY" -m pip install --upgrade --disable-pip-version-check . || {
    # Some Termux builds expose pip as a standalone binary but not as
    # `python -m pip`. Fall back.
    if command -v pip >/dev/null 2>&1; then
        pip install --upgrade --disable-pip-version-check .
    else
        echo "ERROR: could not invoke pip. On Termux run 'pkg install python-pip' first." >&2
        exit 1
    fi
}

echo
echo "==> x-tool installed."
"$PY" -m pip show xtool >/dev/null 2>&1 && echo "Try:  xtool --help"
