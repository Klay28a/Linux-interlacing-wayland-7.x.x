#!/usr/bin/env bash
# Thin wrapper: all logic lives in interlace_kernel.py (unit-tested, supports --dry-run).
# Usage: ./fix-interlaced-kernel.sh [--dry-run] [--config-only] [--gpu-profile P] [--adapter-mode M]
#        [--kernel-version auto|X.Y|linux-next] [--processor-opt OPT] [--no-rdna-patch]
#
# The Python tool is looked up next to this script and in the installed suite directories. A
# directory only counts if the module *and everything it imports* loads, so a half-populated
# install directory is skipped instead of failing later with "No such file or directory".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="interlace_kernel.py"

for dir in "$SCRIPT_DIR" "$HOME/.local/share/linux-interlace-suite" \
           /usr/local/share/linux-interlace-suite /usr/share/linux-interlace-suite; do
    if [ -f "$dir/$TOOL" ] && PYTHONPATH="$dir" python3 -c 'import interlace_kernel' >/dev/null 2>&1; then
        exec python3 "$dir/$TOOL" "$@"
    fi
done

echo "ERROR: could not find a complete copy of the Linux CRT Interlacing Suite." >&2
echo "       Looked in: $SCRIPT_DIR, ~/.local/share/linux-interlace-suite, /usr/local/share/linux-interlace-suite, /usr/share/linux-interlace-suite" >&2
echo "       Reinstall with ./install-interlace-suite.sh (or the package) and try again." >&2
exit 1
