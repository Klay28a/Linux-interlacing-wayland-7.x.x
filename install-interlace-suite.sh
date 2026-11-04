#!/usr/bin/env bash
# Installer for Linux CRT Interlacing Suite (GUI Manager for Interlacing Scripts)
# Leaves linux-cru as its own standalone app while installing the Interlacing Suite GUI
# and creating Start Menu & Desktop shortcuts.
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUITE_SHARE_USER="$HOME/.local/share/linux-interlace-suite"
SUITE_BIN_USER="$HOME/.local/bin/linux-interlace-suite"

echo "==> [1/3] Checking Python 3 & PyQt6..."
if ! python3 -c "import PyQt6" >/dev/null 2>&1; then
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python python-pyqt6
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pyqt6
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pyqt6
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3 python-PyQt6
    fi
else
    echo "  -> Python 3 & PyQt6 are already installed."
fi

echo "==> [2/3] Installing Linux Interlacing Suite files to $SUITE_SHARE_USER..."
mkdir -p "$SUITE_SHARE_USER" "$HOME/.local/bin"

for f in setup-interlace-env.sh fix-interlaced-kernel.sh install-linux-cru.sh \
         11_linux_rdna_dp_hdmi_interlace.patch linux-interlace-suite.py; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp -f "$SCRIPT_DIR/$f" "$SUITE_SHARE_USER/$f"
    fi
done

chmod +x "$SUITE_SHARE_USER"/*.sh "$SUITE_SHARE_USER/linux-interlace-suite.py"
chmod +x "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR/linux-interlace-suite.py" 2>/dev/null || true

install -m 0755 "$SUITE_SHARE_USER/linux-interlace-suite.py" "$SUITE_BIN_USER"
if [ -d "$HOME/bin" ]; then
    install -m 0755 "$SUITE_SHARE_USER/linux-interlace-suite.py" "$HOME/bin/linux-interlace-suite"
fi
if [ "$(id -u)" -eq 0 ] || sudo -n true >/dev/null 2>&1; then
    sudo mkdir -p /usr/local/share/linux-interlace-suite /usr/local/bin
    sudo cp -f "$SUITE_SHARE_USER"/* /usr/local/share/linux-interlace-suite/
    sudo chmod +x /usr/local/share/linux-interlace-suite/*.sh /usr/local/share/linux-interlace-suite/linux-interlace-suite.py
    sudo install -m 0755 "$SUITE_SHARE_USER/linux-interlace-suite.py" /usr/local/bin/linux-interlace-suite
fi

echo "==> [3/3] Creating Application Menu & Desktop shortcuts..."
mkdir -p "$HOME/.local/share/applications"
DESKTOP_FILE="$HOME/.local/share/applications/linux-interlace-suite.desktop"

cat << DESK_EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=Linux Interlacing Suite
GenericName=CRT Interlacing & RDNA Adapter Suite
Comment=Configure EDID, RDNA/GCN Single & Dual-GPU setups, and 15kHz/Interlace Kernel Patches
Exec=$SUITE_BIN_USER
Icon=video-display
Terminal=false
Categories=Settings;HardwareSettings;System;
Keywords=CRT;EDID;Interlace;15kHz;RDNA;AMDGPU;
StartupNotify=true
DESK_EOF

chmod +x "$DESKTOP_FILE"
if [ -d "$HOME/Desktop" ]; then
    cp -f "$DESKTOP_FILE" "$HOME/Desktop/Linux Interlacing Suite.desktop"
    chmod +x "$HOME/Desktop/Linux Interlacing Suite.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "$HOME/Desktop/Linux Interlacing Suite.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo "==> Linux Interlacing Suite installed successfully!"
echo "  -> Launch from Start Menu / Desktop ('Linux Interlacing Suite') or run: $SUITE_BIN_USER"
