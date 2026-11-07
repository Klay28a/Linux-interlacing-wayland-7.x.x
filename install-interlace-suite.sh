#!/usr/bin/env bash
# Installer for the Linux CRT Interlacing Suite (GUI + scripts + tested Python modules).
# Default: per-user install under ~/.local (no sudo). Use --system for /usr/local as well.
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUITE_SHARE_USER="$HOME/.local/share/linux-interlace-suite"
SUITE_BIN_USER="$HOME/.local/bin/linux-interlace-suite"
SYSTEM=0
DRY_RUN=0

FILES=(
    setup-interlace-env.sh fix-interlaced-kernel.sh install-linux-cru.sh install-interlace-suite.sh
    11_linux_rdna_dp_hdmi_interlace.patch linux-interlace-suite.py linux_cru.py
    interlace_runner.py interlace_gpu.py interlace_edid.py interlace_cmdline.py interlace_boot.py
    interlace_rules.py interlace_state.py interlace_setup.py interlace_apply_rules.py
    interlace_pkgbuild.py interlace_rdna_patch.py interlace_apply_edid.py
    interlace_kernel.py interlace_manifest.py interlace_patches.py interlace_gui_tasks.py
    interlace_selection.py interlace_sysinfo.py interlace_verify.py
)

usage() {
    cat << 'HELP_EOF'
Usage: ./install-interlace-suite.sh [--system] [--dry-run]

  --system    Also install to /usr/local/share and /usr/local/bin (uses sudo)
  --dry-run   Print every command that would run; change nothing
HELP_EOF
}

for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $arg" >&2; usage >&2; exit 2 ;;
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

# Privileged commands never block on a hidden password prompt when there is no terminal.
if [ -t 0 ] || [ -n "${SUDO_ASKPASS:-}" ]; then
    SUDO=(sudo)
else
    SUDO=(sudo -n)
fi

# install(1) refuses to copy a file onto itself (this script can run from the installed directory).
install_unless_same() {
    local src="$1" dest="$2"
    if [ -e "$dest" ] && [ "$src" -ef "$dest" ]; then
        return 0
    fi
    run install -m 0755 "$src" "$dest"
}

install_python_qt() {
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
}

echo "==> [1/3] Checking Python 3 & PyQt6..."
install_python_qt

echo "==> [2/3] Installing Linux Interlacing Suite files to $SUITE_SHARE_USER..."
run mkdir -p "$SUITE_SHARE_USER" "$HOME/.local/bin"
for f in "${FILES[@]}"; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        install_unless_same "$SCRIPT_DIR/$f" "$SUITE_SHARE_USER/$f"
    else
        echo "  -> Skipping missing file: $f"
    fi
done
install_unless_same "$SUITE_SHARE_USER/linux-interlace-suite.py" "$SUITE_BIN_USER"

if [ "$SYSTEM" -eq 1 ]; then
    echo "  -> --system: installing to /usr/local (sudo)..."
    run "${SUDO[@]}" install -d /usr/local/share/linux-interlace-suite /usr/local/bin
    for f in "${FILES[@]}"; do
        [ -f "$SCRIPT_DIR/$f" ] || continue
        if [ -e "/usr/local/share/linux-interlace-suite/$f" ] && [ "$SCRIPT_DIR/$f" -ef "/usr/local/share/linux-interlace-suite/$f" ]; then
            continue
        fi
        run "${SUDO[@]}" install -m 0755 "$SCRIPT_DIR/$f" "/usr/local/share/linux-interlace-suite/$f"
    done
    run "${SUDO[@]}" install -m 0755 "$SCRIPT_DIR/linux-interlace-suite.py" /usr/local/bin/linux-interlace-suite
fi

echo "==> [3/3] Creating Application Menu & Desktop shortcuts..."
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/linux-interlace-suite.desktop"
run mkdir -p "$APPS_DIR"
DESKTOP_CONTENT="[Desktop Entry]
Type=Application
Name=Linux Interlacing Suite
GenericName=CRT Interlacing & RDNA Adapter Suite
Comment=Configure EDID, RDNA/GCN Single & Dual-GPU setups, and 15kHz/Interlace Kernel Patches
Exec=$SUITE_BIN_USER
Icon=video-display
Terminal=false
Categories=Settings;HardwareSettings;System;
Keywords=CRT;EDID;Interlace;15kHz;RDNA;AMDGPU;
StartupNotify=true"
if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would write $DESKTOP_FILE:"
    printf '%s\n' "$DESKTOP_CONTENT" | sed 's/^/[dry-run]   | /'
else
    printf '%s\n' "$DESKTOP_CONTENT" > "$DESKTOP_FILE"
    chmod +x "$DESKTOP_FILE"
fi
if [ -d "$HOME/Desktop" ]; then
    run install -m 0755 "$DESKTOP_FILE" "$HOME/Desktop/Linux Interlacing Suite.desktop"
    if command -v gio >/dev/null 2>&1; then
        run gio set "$HOME/Desktop/Linux Interlacing Suite.desktop" metadata::trusted true || true
    fi
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    run update-desktop-database "$APPS_DIR" || true
fi

echo "==> Linux Interlacing Suite installed successfully!"
echo "  -> Launch from the application menu or run: $SUITE_BIN_USER"
