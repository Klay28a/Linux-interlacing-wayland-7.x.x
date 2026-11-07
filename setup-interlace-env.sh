#!/usr/bin/env bash
# Thin wrapper: all logic lives in interlace_setup.py (unit-tested, supports --dry-run).
# Usage: ./setup-interlace-env.sh [--dry-run] [--gpu-profile P] [--adapter-mode M]
#        [--edid FILE] [--connector NAME|auto] [--live-only] [--no-desktop-env]
#
# The Python tool is looked up next to this script and in the installed suite directories. A
# directory only counts if the module *and everything it imports* loads, so a half-populated
# install directory is skipped instead of failing later with "No such file or directory".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="interlace_setup.py"

for dir in "$SCRIPT_DIR" "$HOME/.local/share/linux-interlace-suite" \
           /usr/local/share/linux-interlace-suite /usr/share/linux-interlace-suite; do
    if [ -f "$dir/$TOOL" ] && PYTHONPATH="$dir" python3 -c 'import interlace_setup' >/dev/null 2>&1; then
        exec python3 "$dir/$TOOL" "$@"
    fi
done

echo "ERROR: could not find a complete copy of the Linux CRT Interlacing Suite." >&2
echo "       Looked in: $SCRIPT_DIR, ~/.local/share/linux-interlace-suite, /usr/local/share/linux-interlace-suite, /usr/share/linux-interlace-suite" >&2
echo "       Reinstall with ./install-interlace-suite.sh (or the package) and try again." >&2
exit 1
