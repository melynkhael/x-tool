#!/usr/bin/env bash
# Install script for x-tool on Termux / Linux / macOS.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

if command -v pkg >/dev/null 2>&1; then
    # Termux
    pkg install -y python git
fi

python -m pip install --upgrade pip
python -m pip install .

echo
echo "x-tool installed. Try:"
echo "    xtool --help"
