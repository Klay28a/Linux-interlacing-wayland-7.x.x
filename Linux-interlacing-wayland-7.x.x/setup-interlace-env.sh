#!/usr/bin/env bash
# Universal Linux CRT Interlace Environment Setup
# Supports: Limine, GRUB, systemd-boot | mkinitcpio, dracut, initramfs-tools
set -euo pipefail
umask 022

EDID_SRC="${1:-/usr/lib/firmware/edid/crufile.bin}"
USER_CONN="${2:-auto}"
EDID_NAME="crufile.bin"
EDID_DEST="/usr/lib/firmware/edid/${EDID_NAME}"

TMP_EDID="$(mktemp)"
trap 'rm -f "$TMP_EDID"' EXIT

# 1. Auto-detect connected analog DRM connector (VGA-* or DVI-I-*) if not specified
if [ "$USER_CONN" = "auto" ]; then
    DETECTED_CONN=""
    for status_file in /sys/class/drm/card*-*/status; do
        [ -e "$status_file" ] || continue
        port_dir="$(dirname "$status_file")"
        port_name="$(basename "$port_dir")"
        short_name="${port_name#card*-}"
        if [[ "$short_name" == VGA-* || "$short_name" == DVI-I-* ]]; then
            if [ "$(cat "$status_file")" = "connected" ]; then
                DETECTED_CONN="$short_name"
                break
            fi
        fi
    done
    CONNECTOR="${DETECTED_CONN:-VGA-1}"
else
    CONNECTOR="$USER_CONN"
fi

echo "==> Target DRM Connector: $CONNECTOR"

# 2. Validate & Fix CRU EDID Binary (Convert half-field height to Linux full-frame height)
echo "==> [1/5] Validating EDID and converting interlaced DTDs to Linux full-frame height..."
if [ ! -f "$EDID_SRC" ]; then
    echo "ERROR: EDID file not found at: $EDID_SRC"
    echo "Usage: $0 [/path/to/edid.bin] [VGA-1|DVI-I-1]"
    exit 1
fi

python3 - "$EDID_SRC" "$TMP_EDID" << 'PYEOF'
import sys

src, dst = sys.argv[1], sys.argv[2]
b = bytearray(open(src, "rb").read())

if len(b) < 128 or b[0:8] != b'\x00\xff\xff\xff\xff\xff\xff\x00':
    print("ERROR: Invalid EDID header! File is not a valid 128/256-byte raw EDID binary.", file=sys.stderr)
    sys.exit(1)

for off in (54, 72, 90, 108):
    if b[off] == 0 and b[off+1] == 0:
        continue
    if b[off+17] & 0x80:
        vact = b[off+5] | ((b[off+7] & 0xF0) << 4)
        vblk = b[off+6] | ((b[off+7] & 0x0F) << 8)
        voff = ((b[off+10] >> 4) & 0x0F) | ((b[off+11] & 0x0C) << 2)
        vsyn = (b[off+10] & 0x0F) | ((b[off+11] & 0x03) << 4)
        if vact < 1000:
            vact, vblk = vact * 2, vblk * 2
            voff, vsyn = min(63, voff * 2), min(63, vsyn * 2)
            b[off+5] = vact & 0xFF
            b[off+6] = vblk & 0xFF
            b[off+7] = (((vact >> 8) & 0x0F) << 4) | ((vblk >> 8) & 0x0F)
            b[off+10] = ((voff & 0x0F) << 4) | (vsyn & 0x0F)
            b[off+11] = (b[off+11] & 0xF0) | (((voff >> 4) & 0x03) << 2) | ((vsyn >> 4) & 0x03)
            print(f"  -> Converted DTD @{off} to Linux frame height: vactive={vact}, vblank={vblk}")
        else:
            print(f"  -> Verified DTD @{off} already uses Linux frame height: vactive={vact}")

b[127] = (256 - (sum(b[:127]) % 256)) % 256
open(dst, "wb").write(b)
PYEOF

sudo mkdir -p /usr/lib/firmware/edid
sudo install -m 0644 "$TMP_EDID" "$EDID_DEST"

# 3. Ensure Pacman has no IgnorePkg locks on kernel packages (if on Arch/CachyOS)
if [ -f /etc/pacman.conf ]; then
    echo "==> [2/5] Ensuring /etc/pacman.conf allows normal kernel updates..."
    sudo sed -i 's/^IgnorePkg = linux-cachyos.*/#IgnorePkg =/' /etc/pacman.conf
fi

# 4. Apply KWin Wayland Software Cursor Fix
echo "==> [3/5] Configuring Wayland software cursor fix (~/.config/environment.d/kwin-cursor.conf)..."
mkdir -p "$HOME/.config/environment.d"
echo "KWIN_FORCE_SW_CURSOR=1" > "$HOME/.config/environment.d/kwin-cursor.conf"

# 5. Embed EDID in Initramfs Configuration (mkinitcpio / dracut / initramfs-tools)
echo "==> [4/5] Registering $EDID_DEST in initramfs configuration..."
if [ -f /etc/mkinitcpio.conf ]; then
    sudo cp -a /etc/mkinitcpio.conf "/etc/mkinitcpio.conf.bak.$(date +%Y%m%d%H%M%S)"
    if ! grep -Fq "$EDID_DEST" /etc/mkinitcpio.conf; then
        sudo sed -i "s|^FILES=(|FILES=($EDID_DEST |" /etc/mkinitcpio.conf
    fi
fi
if [ -d /etc/dracut.conf.d ]; then
    echo "install_items+=\" $EDID_DEST \"" | sudo tee /etc/dracut.conf.d/99-crt-edid.conf >/dev/null
fi
if [ -d /etc/initramfs-tools/hooks ]; then
    sudo tee /etc/initramfs-tools/hooks/crt-edid >/dev/null << HOOK_EOF
#!/bin/sh
PREREQ=""
prereqs() { echo "\$PREREQ"; }
case "\${1:-}" in prereqs) prereqs; exit 0;; esac
. /usr/share/initramfs-tools/hook-functions
mkdir -p "\${DESTDIR}/usr/lib/firmware/edid"
cp -pnL "$EDID_DEST" "\${DESTDIR}/usr/lib/firmware/edid/"
HOOK_EOF
    sudo chmod +x /etc/initramfs-tools/hooks/crt-edid
fi

# 6. Configure Bootloader Parameters (Limine, GRUB, or systemd-boot) & Rebuild Initramfs
echo "==> [5/5] Updating bootloader kernel parameters and regenerating initramfs..."
REQUIRED_ARGS="radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1 drm.edid_firmware=${CONNECTOR}:edid/${EDID_NAME} video=${CONNECTOR}:e"

update_cmdline_file() {
    local file="$1"
    local key="$2"
    sudo cp -a "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
    sudo python3 - "$file" "$key" "$REQUIRED_ARGS" << 'PY_BOOT'
import sys, re
path, key, req = sys.argv[1], sys.argv[2], sys.argv[3].split()
lines = open(path, "r").readlines()
out = []
for line in lines:
    if line.strip().startswith(key):
        # Clean old instances of our managed parameters
        for prefix in ("radeon.si_support=", "amdgpu.si_support=", "radeon.cik_support=", "amdgpu.cik_support=", "drm.edid_firmware=", "video=VGA-", "video=DVI-I-"):
            line = re.sub(r'\b' + re.escape(prefix) + r'[^\s"\']+', '', line)
        line = re.sub(r'  +', ' ', line)
        # Append required args before the closing quote
        idx = line.rfind('"')
        if idx != -1:
            prefix_str = line[:idx].rstrip()
            line = f'{prefix_str} {" ".join(req)}"\n'
    out.append(line)
open(path, "w").writelines(out)
PY_BOOT
}

if [ -f /etc/default/limine ]; then
    echo "  -> Detected Limine (/etc/default/limine)"
    update_cmdline_file "/etc/default/limine" "KERNEL_CMDLINE"
fi

if [ -f /etc/default/grub ]; then
    echo "  -> Detected GRUB (/etc/default/grub)"
    update_cmdline_file "/etc/default/grub" "GRUB_CMDLINE_LINUX_DEFAULT"
    if command -v update-grub >/dev/null 2>&1; then
        sudo update-grub
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        sudo grub-mkconfig -o /boot/grub/grub.cfg
    elif command -v grub2-mkconfig >/dev/null 2>&1; then
        sudo grub2-mkconfig -o /boot/grub2/grub.cfg
    fi
fi

# Rebuild initramfs using the active distro tool
if command -v limine-mkinitcpio >/dev/null 2>&1; then
    sudo limine-mkinitcpio
elif command -v mkinitcpio >/dev/null 2>&1; then
    sudo mkinitcpio -P
elif command -v dracut >/dev/null 2>&1; then
    sudo dracut --regenerate-all --force
elif command -v update-initramfs >/dev/null 2>&1; then
    sudo update-initramfs -u -k all
fi

echo "==> Setup complete! Configured for $CONNECTOR with $EDID_DEST."
