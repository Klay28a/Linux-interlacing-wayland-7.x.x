#!/usr/bin/env bash
# Script 1: Standalone CRT Interlace & Multi-GPU Environment Setup
# Works standalone or alongside linux-cru without requiring linux-cru.
# Supports: Limine, GRUB | mkinitcpio, dracut, initramfs-tools
# Usage: ./setup-interlace-env.sh [edid_source_path] [connector_name|auto]
set -euo pipefail
umask 022

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Please run this script as your normal user (it will prompt via sudo when needed)." >&2
    exit 1
fi

USER_EDID_SRC="${1:-}"
USER_CONN="${2:-auto}"

TMP_EDID="$(mktemp)"
TMP_CFG="$(mktemp)"
trap 'rm -f "$TMP_EDID" "$TMP_CFG"' EXIT

# 1. Auto-detect analog connector (VGA-* or DVI-I-*) or use user-specified connector
if [ "$USER_CONN" = "auto" ]; then
    DETECTED_CONN=""
    for status_file in /sys/class/drm/card*-*/status; do
        [ -e "$status_file" ] || continue
        short_name="$(basename "$(dirname "$status_file")")"
        short_name="${short_name#card*-}"
        if [[ "$short_name" == VGA-* || "$short_name" == DVI-I-* ]]; then
            if [ "$(cat "$status_file" 2>/dev/null || true)" = "connected" ]; then
                DETECTED_CONN="$short_name"
                break
            fi
        fi
    done
    if [ -z "$DETECTED_CONN" ]; then
        for status_file in /sys/class/drm/card*-*/status; do
            [ -e "$status_file" ] || continue
            short_name="$(basename "$(dirname "$status_file")")"
            short_name="${short_name#card*-}"
            if [[ "$short_name" == VGA-* || "$short_name" == DVI-I-* ]]; then
                DETECTED_CONN="$short_name"
                break
            fi
        done
    fi
    CONNECTOR="${DETECTED_CONN:-VGA-1}"
else
    CONNECTOR="$USER_CONN"
fi

if [ "$CONNECTOR" = "VGA-1" ]; then
    EDID_NAME="crufile.bin"
else
    CONN_LOWER="$(echo "$CONNECTOR" | tr '[:upper:]' '[:lower:]')"
    EDID_NAME="cru-${CONN_LOWER}.bin"
fi
EDID_DEST="/usr/lib/firmware/edid/${EDID_NAME}"
EDID_SRC="${USER_EDID_SRC:-$EDID_DEST}"

echo "==> [1/4] Target DRM Connector: $CONNECTOR (Firmware target: $EDID_DEST)"

# 2. Create or Validate Linux-Formatted EDID Binary
echo "==> [2/4] Preparing Linux-formatted EDID at $EDID_DEST..."
python3 - "$EDID_SRC" "$TMP_EDID" << 'PYEOF'
import sys, os

src, dst = sys.argv[1], sys.argv[2]

if os.path.exists(src) and os.path.getsize(src) >= 128:
    b = bytearray(open(src, "rb").read())
    if b[0:8] != b'\x00\xff\xff\xff\xff\xff\xff\x00':
        print(f"ERROR: Invalid EDID header in {src}!", file=sys.stderr)
        sys.exit(1)
    print(f"  -> Loaded existing EDID from {src} ({len(b)} bytes).")
else:
    b = bytearray(128)
    b[0:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
    b[8:12] = b'\x22\xf0\xd0\x09'
    b[18], b[19], b[20], b[21], b[22], b[23], b[24] = 1, 3, 0x0E, 41, 31, 120, 0xEA
    b[38:40] = bytes([(1600 // 8) - 31, 0x40 | (85 - 60)])
    b[40:54] = b'\x01\x01' * 7
    b[54:72] = bytes([
        0x5C, 0x92, 0x00, 0xD0, 0x82, 0x00, 0x9C, 0x60,
        0x88, 0xE0, 0x68, 0x00, 0x96, 0x31, 0x11, 0x00, 0x00, 0x9C
    ])
    for empty_off in (72, 90):
        b[empty_off:empty_off+18] = bytes([0, 0, 0, 0x10, 0] + [0] * 13)
    b[108:126] = bytes([
        0x00, 0x00, 0x00, 0xFD, 0x00,
        30, 200, 30, 200, 70, 0x00,
        0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20
    ])
    print("  -> Generated default CRT EDID (2048x1536i @ 160Hz + 1600x1200p @ 85Hz).")

for off in (54, 72, 90, 108):
    if b[off:off+4] == b'\x00\x00\x00\xfd':
        b[off+8] = max(b[off+8], 200)
        b[off+9] = max(b[off+9], 70)
        continue
    if b[off] == 0 and b[off+1] == 0:
        continue
    if b[off+17] & 0x80:
        hact = b[off+2] | ((b[off+4] & 0xF0) << 4)
        vact = b[off+5] | ((b[off+7] & 0xF0) << 4)
        vblk = b[off+6] | ((b[off+7] & 0x0F) << 8)
        voff = ((b[off+10] >> 4) & 0x0F) | ((b[off+11] & 0x0C) << 2)
        vsyn = (b[off+10] & 0x0F) | ((b[off+11] & 0x03) << 4)
        if hact > 0 and vact <= int(hact * 0.45):
            vact, vblk = vact * 2, vblk * 2
            voff, vsyn = min(63, voff * 2), min(63, vsyn * 2)
            b[off+5] = vact & 0xFF
            b[off+6] = vblk & 0xFF
            b[off+7] = (((vact >> 8) & 0x0F) << 4) | ((vblk >> 8) & 0x0F)
            b[off+10] = ((voff & 0x0F) << 4) | (vsyn & 0x0F)
            b[off+11] = (b[off+11] & 0xF0) | (((voff >> 4) & 0x03) << 2) | ((vsyn >> 4) & 0x03)
            print(f"  -> Converted Windows half-field DTD @{off} to Linux full-frame height: vactive={vact}")

if len(b) >= 256:
    b[126] = 1
    b[127] = (256 - (sum(b[:127]) % 256)) % 256
    b[255] = (256 - (sum(b[128:255]) % 256)) % 256
else:
    b[126] = 0
    b[127] = (256 - (sum(b[:127]) % 256)) % 256

open(dst, "wb").write(b)
PYEOF

sudo mkdir -p /usr/lib/firmware/edid
sudo install -m 0644 "$TMP_EDID" "$EDID_DEST"

# 4. Embed EDID in Initramfs (preserving any other EDID files configured by linux-cru)
echo "==> [4/5] Embedding $EDID_DEST in initramfs configuration..."
if [ -f /etc/mkinitcpio.conf ]; then
    [ -f /etc/mkinitcpio.conf.orig.bak ] || sudo cp -a /etc/mkinitcpio.conf /etc/mkinitcpio.conf.orig.bak
    if ! grep -Fq "$EDID_DEST" /etc/mkinitcpio.conf; then
        sudo sed -i "s|^FILES=(|FILES=($EDID_DEST |" /etc/mkinitcpio.conf
    fi
fi
if [ -d /etc/dracut.conf.d ]; then
    DRACUT_CONF="/etc/dracut.conf.d/99-crt-edid.conf"
    if [ ! -f "$DRACUT_CONF" ] || ! grep -Fq "$EDID_DEST" "$DRACUT_CONF"; then
        echo "install_items+=\" $EDID_DEST \"" | sudo tee -a "$DRACUT_CONF" >/dev/null
    fi
fi

# 5. Update Bootloader (Limine & GRUB), Rebuild Initramfs, and Reload Live DRM
echo "==> [5/5] Updating bootloader kernel parameters (preserving multi-port EDIDs) and rebuilding initramfs..."

update_cmdline_file() {
    local file="$1"
    local key="$2"
    [ -f "${file}.orig.bak" ] || sudo cp -a "$file" "${file}.orig.bak"
    python3 - "$file" "$key" "$CONNECTOR" "edid/${EDID_NAME}" > "$TMP_CFG" << 'PY_BOOT'
import sys, re

path, key, conn, rel_fw = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
lines = open(path, "r").readlines()
out = []
si_args = ["radeon.si_support=0", "amdgpu.si_support=1", "radeon.cik_support=0", "amdgpu.cik_support=1"]

for line in lines:
    if line.lstrip().startswith(key):
        fw_map = {}
        for m in re.finditer(r'\bdrm\.edid_firmware=([^\s"\']+)', line):
            for item in m.group(1).split(","):
                if ":" in item:
                    k, v = item.split(":", 1)
                    fw_map[k.strip()] = v.strip()
        fw_map[conn] = rel_fw
        fw_arg = "drm.edid_firmware=" + ",".join(f"{k}:{v}" for k, v in fw_map.items())
        vid_arg = f"video={conn}:e"

        for prefix in ("radeon.si_support=", "amdgpu.si_support=", "radeon.cik_support=", "amdgpu.cik_support=", "drm.edid_firmware="):
            line = re.sub(r'\b' + re.escape(prefix) + r'[^\s"\']+', '', line)
        line = re.sub(r'\bvideo=' + re.escape(conn) + r':[^\s"\']+', '', line)
        line = re.sub(r'  +', ' ', line)
        idx = line.rfind('"')
        if idx != -1:
            line = f'{line[:idx].rstrip()} {" ".join(si_args)} {fw_arg} {vid_arg}"\n'
    out.append(line)

sys.stdout.writelines(out)
PY_BOOT
    sudo install -m 0644 "$TMP_CFG" "$file"
}

if [ -f /etc/default/limine ]; then
    update_cmdline_file "/etc/default/limine" "KERNEL_CMDLINE"
    grep "KERNEL_CMDLINE" /etc/default/limine || true
fi

if [ -f /etc/default/grub ]; then
    update_cmdline_file "/etc/default/grub" "GRUB_CMDLINE_LINUX_DEFAULT"
    if command -v update-grub >/dev/null 2>&1; then
        sudo update-grub
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        sudo grub-mkconfig -o /boot/grub/grub.cfg
    fi
fi

if command -v limine-mkinitcpio >/dev/null 2>&1; then
    sudo limine-mkinitcpio
elif command -v mkinitcpio >/dev/null 2>&1; then
    sudo mkinitcpio -P
elif command -v dracut >/dev/null 2>&1; then
    sudo dracut --regenerate-all --force
elif command -v update-initramfs >/dev/null 2>&1; then
    sudo update-initramfs -u -k all
fi

if [ -e /sys/module/drm/parameters/edid_firmware ]; then
    NEW_FW_PARAM="$(python3 - "$CONNECTOR" "edid/${EDID_NAME}" << 'PY_LIVE'
import os, sys
conn, rel = sys.argv[1], sys.argv[2]
p = "/sys/module/drm/parameters/edid_firmware"
fw_map = {}
if os.path.exists(p):
    for item in open(p).read().strip().split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            fw_map[k.strip()] = v.strip()
fw_map[conn] = rel
print(",".join(f"{k}:{v}" for k, v in fw_map.items()))
PY_LIVE
)"
    echo -n "$NEW_FW_PARAM" | sudo tee /sys/module/drm/parameters/edid_firmware >/dev/null || true
    for st in /sys/class/drm/card*-"${CONNECTOR}"/status; do
        if [ -e "$st" ]; then
            REPROBE_STATE="detect"
            [[ "$CONNECTOR" == VGA-* || "$CONNECTOR" == DVI-I-* ]] && REPROBE_STATE="on"
            sudo bash -c "echo off > '$st' && sleep 0.15 && echo '$REPROBE_STATE' > '$st'" || true
        fi
    done
    sudo udevadm trigger --action=change --subsystem-match=drm || true
fi

echo "==> Environment setup complete!"
