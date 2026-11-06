#!/usr/bin/env bash
# Installer for Linux CRU (standalone ToastyX-style custom resolution utility).
# The application itself is linux_cru.py (linted and testable); this script only installs it.
# Default: per-user install under ~/.local/bin. Use --system to also install to /usr/local/bin.
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$SCRIPT_DIR/linux_cru.py"
# The Apply buttons run interlace_apply_edid.py (via pkexec); it needs these sibling modules.
SUPPORT_FILES=(
    interlace_apply_edid.py interlace_boot.py interlace_cmdline.py interlace_edid.py interlace_gpu.py
    interlace_rules.py interlace_runner.py interlace_setup.py interlace_state.py
)
SUPPORT_USER="$HOME/.local/share/linux-interlace-suite"
SUPPORT_SYSTEM="/usr/local/share/linux-interlace-suite"
SYSTEM=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            echo "Usage: ./install-linux-cru.sh [--system] [--dry-run]"
            exit 0
            ;;
        *) echo "ERROR: unknown option: $arg" >&2; exit 2 ;;
    esac
done

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '[dry-run] would run:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

if [ -t 0 ] || [ -n "${SUDO_ASKPASS:-}" ]; then
    SUDO=(sudo)
else
    SUDO=(sudo -n)
fi

if [ ! -f "$APP_SRC" ]; then
    echo "ERROR: $APP_SRC not found (run this script from the project directory)." >&2
    exit 1
fi

echo "==> [1/3] Checking Python 3 & PyQt6..."
if python3 -c "import PyQt6" >/dev/null 2>&1; then
    echo "  -> Python 3 & PyQt6 are already installed."
elif command -v pacman >/dev/null 2>&1; then
    run "${SUDO[@]}" pacman -S --needed --noconfirm python python-pyqt6
elif command -v apt-get >/dev/null 2>&1; then
    run "${SUDO[@]}" apt-get update
    run "${SUDO[@]}" apt-get install -y python3 python3-pyqt6
elif command -v dnf >/dev/null 2>&1; then
    run "${SUDO[@]}" dnf install -y python3 python3-pyqt6
elif command -v zypper >/dev/null 2>&1; then
    run "${SUDO[@]}" zypper --non-interactive install python3 python-PyQt6
else
    echo "ERROR: PyQt6 is missing and no supported package manager was found." >&2
    exit 1
fi

echo "==> [2/3] Installing linux-cru..."
run mkdir -p "$HOME/.local/bin" "$SUPPORT_USER"
run install -m 0755 "$APP_SRC" "$HOME/.local/bin/linux-cru"
for f in "${SUPPORT_FILES[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$f" ]; then
        echo "ERROR: $SCRIPT_DIR/$f not found (needed by the Apply buttons)." >&2
        exit 1
    fi
    run install -m 0755 "$SCRIPT_DIR/$f" "$SUPPORT_USER/$f"
done
if [ "$SYSTEM" -eq 1 ]; then
    run "${SUDO[@]}" install -m 0755 "$APP_SRC" /usr/local/bin/linux-cru
    run "${SUDO[@]}" install -d "$SUPPORT_SYSTEM"
    for f in "${SUPPORT_FILES[@]}"; do
        run "${SUDO[@]}" install -m 0755 "$SCRIPT_DIR/$f" "$SUPPORT_SYSTEM/$f"
    done
fi

echo "==> [3/3] Creating Desktop Launcher Shortcut..."
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/linux-cru.desktop"
run mkdir -p "$APPS_DIR"
DESKTOP_CONTENT="[Desktop Entry]
Name=Linux CRU
Comment=ToastyX-Style Custom Resolution Utility for Linux
Exec=$HOME/.local/bin/linux-cru
Icon=video-display
Terminal=false
Type=Application
Categories=System;Settings;HardwareSettings;"
if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would write $DESKTOP_FILE:"
    printf '%s\n' "$DESKTOP_CONTENT" | sed 's/^/[dry-run]   | /'
else
    printf '%s\n' "$DESKTOP_CONTENT" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"
fi
if [ -d "$HOME/Desktop" ]; then
    run install -m 0755 "$DESKTOP_FILE" "$HOME/Desktop/Linux CRU.desktop"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    run update-desktop-database "$APPS_DIR" || true
fi

echo "==> Linux CRU installed! Run 'linux-cru' or launch it from your application menu."
