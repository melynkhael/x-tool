#!/usr/bin/env bash
# Install script for x-tool on Termux / Linux / macOS / WSL.
#
# Termux-specific notes:
#   * pip is managed by the `python-pip` package; `pip install --upgrade
#     pip` is forbidden and makes the package database inconsistent.
#   * On Termux we also need `libexpat`, `openssl` and `rust` to build
#     some transitive deps of `requests` / `rich` from source.
#
# Flags:
#   --quiet   Beginner-friendly output: three short progress lines
#             instead of hundreds of lines of pip output. Real errors
#             are NEVER suppressed -- if something goes wrong, you
#             still see the full error. Used by the documented update
#             workflow:
#                 cd ~/x-tool
#                 git pull --ff-only --quiet origin main
#                 bash install.sh --quiet

set -euo pipefail

quiet=0
for arg in "$@"; do
    case "$arg" in
        --quiet|-q) quiet=1 ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

say() {
    # Always print progress; callers parse these lines.
    echo "$*"
}

note() {
    # Verbose-only status; suppressed with --quiet.
    if [ "$quiet" -eq 0 ]; then
        echo "$*"
    fi
}

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

is_termux() { command -v pkg >/dev/null 2>&1 && [ -n "${PREFIX:-}" ] && [[ "$PREFIX" == *"/com.termux/"* ]]; }

if is_termux; then
    note "==> Detected Termux environment"
    # python-pip is the Termux package that owns pip; installing it
    # guarantees we never try to bootstrap pip via ensurepip.
    if [ "$quiet" -eq 1 ]; then
        pkg install -y python python-pip git libexpat openssl >/dev/null 2>&1 || {
            # If the quiet install actually failed, rerun verbosely
            # so the user sees the error. Quiet mode must never hide
            # real failures.
            say "Package install failed; rerunning verbosely for diagnosis:"
            pkg install -y python python-pip git libexpat openssl
            exit 1
        }
    else
        pkg install -y python python-pip git libexpat openssl
    fi
    # xtool itself is pure-Python, but some wheels on Termux have no
    # prebuilt binaries and fall back to source; rust is needed for
    # those (e.g. `cryptography` transitive). Safe to install lazily.
    if ! command -v rustc >/dev/null 2>&1; then
        if [ "$quiet" -eq 1 ]; then
            pkg install -y rust >/dev/null 2>&1 || true
        else
            pkg install -y rust || true
        fi
    fi
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

if [ "$quiet" -eq 1 ]; then
    say "Installing X-Tool..."
    # -q keeps pip quiet on success but still prints real errors to
    # stderr. If the quiet call fails, we rerun verbosely so the user
    # sees exactly what went wrong -- real errors are never hidden.
    if ! "$PY" -m pip install --upgrade --disable-pip-version-check -q . 2>/tmp/xtool-install.err; then
        cat /tmp/xtool-install.err >&2 || true
        # Fallback path for Termux where pip may be exposed only as a
        # standalone binary.
        if command -v pip >/dev/null 2>&1; then
            pip install --upgrade --disable-pip-version-check -q . || {
                say "Install failed. Rerunning verbosely to show the full error:"
                "$PY" -m pip install --upgrade --disable-pip-version-check .
                exit 1
            }
        else
            say "Install failed. Rerunning verbosely to show the full error:"
            "$PY" -m pip install --upgrade --disable-pip-version-check .
            exit 1
        fi
    fi
    say "Done."
    # Show the installed version so users know they are on the new build.
    if "$PY" -m pip show xtool >/dev/null 2>&1; then
        ver="$("$PY" -c 'import xtool; print(xtool.__version__)' 2>/dev/null || true)"
        if [ -n "${ver:-}" ]; then
            say "X-Tool v${ver} is ready."
        else
            say "X-Tool is ready."
        fi
    fi
    say "Run \`xtool\` to open the menu."
else
    note "==> Installing xtool"
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
    note "==> x-tool installed."
    "$PY" -m pip show xtool >/dev/null 2>&1 && note "Try:  xtool --help"
fi
