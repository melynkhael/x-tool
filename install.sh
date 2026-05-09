#!/usr/bin/env bash
# Install script for x-tool on Termux / Linux / macOS / WSL.
#
# Termux-specific notes:
#   * pip is managed by the `python-pip` package; `pip install --upgrade
#     pip` is forbidden and makes the package database inconsistent.
#   * On Termux we also need `libexpat`, `openssl` and `rust` to build
#     some transitive deps of `requests` / `rich` from source.
#   * /tmp does not exist on Termux. Never hardcode it; use the
#     _tmp_dir helper below.
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

# ---------------------------------------------------------------------------
# Pick a writable temp directory. We do NOT hardcode /tmp because Termux
# does not have it (the shared /tmp is only writable for root on
# Android). Preference order:
#   1. $TMPDIR               -- the POSIX-standard hint; Termux sets it.
#   2. $PREFIX/tmp           -- the Termux-native fallback.
#   3. $here/.tmp            -- last-ditch, always in the repo checkout.
#
# Each candidate is validated with ``mkdir -p`` + writability check so
# that a stale env var (e.g. TMPDIR pointing at a deleted path) still
# falls through cleanly instead of crashing the install.
# ---------------------------------------------------------------------------
_tmp_dir() {
    local cand
    for cand in "${TMPDIR:-}" "${PREFIX:+$PREFIX/tmp}" "$here/.tmp"; do
        [ -z "$cand" ] && continue
        if mkdir -p "$cand" 2>/dev/null && [ -w "$cand" ]; then
            printf '%s\n' "$cand"
            return 0
        fi
    done
    # If nothing worked, fall back to the repo dir itself; it's
    # guaranteed to be writable because we just cd'd into it.
    printf '%s\n' "$here"
}

_make_err_file() {
    # Create a unique temp file for stderr capture. Uses mktemp when
    # available (Termux + Linux + macOS); otherwise constructs a
    # predictable path so ancient busybox shells still work.
    local dir
    dir="$(_tmp_dir)"
    local path
    if command -v mktemp >/dev/null 2>&1; then
        path="$(mktemp "$dir/xtool-install.XXXXXX.err" 2>/dev/null || true)"
    fi
    if [ -z "${path:-}" ]; then
        path="$dir/xtool-install-$$-$(date +%s 2>/dev/null || echo 0).err"
        : > "$path" || { echo "ERROR: cannot create temp file in $dir" >&2; exit 1; }
    fi
    printf '%s\n' "$path"
}

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
    # stderr. We capture that stderr to a temp file so we can replay
    # it if the install fails. On success we delete the file; on
    # failure we print it and exit non-zero so beginners see the real
    # error. Using _make_err_file avoids the old /tmp hardcode that
    # broke on Termux where /tmp does not exist.
    #
    # We install with -e (editable) so the package stays rooted in
    # the git checkout -- that's what makes `xtool update` able to
    # find the repo later via its own source file. A non-editable
    # install would copy xtool/ into site-packages and `xtool update`
    # would have to fall back to cwd detection.
    err_file="$(_make_err_file)"
    install_ok=0
    if "$PY" -m pip install -e . --upgrade --disable-pip-version-check -q 2>"$err_file"; then
        install_ok=1
    elif command -v pip >/dev/null 2>&1; then
        # Fallback path for Termux builds that expose pip only as a
        # standalone binary (no `python -m pip`). Capture its stderr
        # to the same file so failures from either attempt are
        # surfaced together.
        if pip install -e . --upgrade --disable-pip-version-check -q 2>>"$err_file"; then
            install_ok=1
        fi
    fi

    if [ "$install_ok" -ne 1 ]; then
        say "Install failed. Captured error output:"
        if [ -s "$err_file" ]; then
            cat "$err_file" >&2
        else
            say "  (pip produced no error output; rerunning verbosely for diagnosis)"
            # Keep the err_file around for the user to inspect even
            # after the verbose rerun writes to the terminal.
            "$PY" -m pip install -e . --upgrade --disable-pip-version-check || true
        fi
        say ""
        say "Error log: $err_file"
        exit 1
    fi

    # Success path: clean up the (empty) error file.
    rm -f "$err_file"

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
    # -e (editable) keeps the package rooted in this checkout so
    # `xtool update` can locate the git repo later.
    "$PY" -m pip install -e . --upgrade --disable-pip-version-check || {
        # Some Termux builds expose pip as a standalone binary but not as
        # `python -m pip`. Fall back.
        if command -v pip >/dev/null 2>&1; then
            pip install -e . --upgrade --disable-pip-version-check
        else
            echo "ERROR: could not invoke pip. On Termux run 'pkg install python-pip' first." >&2
            exit 1
        fi
    }
    echo
    note "==> x-tool installed."
    "$PY" -m pip show xtool >/dev/null 2>&1 && note "Try:  xtool --help"
fi
