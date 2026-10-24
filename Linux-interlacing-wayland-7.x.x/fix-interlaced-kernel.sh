#!/usr/bin/env bash
# Script 2: Pure 15kHz & Interlace Kernel Patcher for CachyOS / Arch (No 700 MHz Clock Modifications)
# Works standalone or alongside setup-interlace-env.sh and linux-cru.
# Supports: CachyOS / Arch | Limine, GRUB, systemd-boot
set -euo pipefail
umask 022

BUILD_ROOT="${BUILD_ROOT:-$HOME/kernel-build}"
CACHY_REPO="$BUILD_ROOT/linux-cachyos"
PATCH_REPO="$BUILD_ROOT/linux_kernel_15khz"

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Run this script as your normal user, not root/sudo." >&2
    exit 1
fi

echo "==> [1/6] Ensuring required kernel build tools and LLVM/Rust dependencies are installed..."
sudo pacman -S --needed --noconfirm \
    base-devel git pacman-contrib python bc cpio gettext libelf openssl \
    pahole perl tar xxhash xz zlib zstd clang llvm lld rust rust-bindgen rust-src

mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"

echo "==> [2/6] Fetching latest CachyOS kernel PKGBUILD and fresh 15kHz/interlace patches..."
if [ ! -d "$CACHY_REPO/.git" ]; then
    git clone --depth 1 https://github.com/CachyOS/linux-cachyos.git "$CACHY_REPO"
else
    git -C "$CACHY_REPO" fetch --depth 1 origin
    git -C "$CACHY_REPO" reset --hard FETCH_HEAD
    git -C "$CACHY_REPO" clean -fd
fi

if [ ! -d "$PATCH_REPO/.git" ]; then
    git clone --depth 1 https://github.com/D0023R/linux_kernel_15khz.git "$PATCH_REPO"
else
    git -C "$PATCH_REPO" fetch --depth 1 origin
    git -C "$PATCH_REPO" reset --hard FETCH_HEAD
    git -C "$PATCH_REPO" clean -fd
fi

cd "$CACHY_REPO/linux-cachyos"

if [ ! -f PKGBUILD ]; then
    echo "ERROR: PKGBUILD not found in $CACHY_REPO/linux-cachyos" >&2
    exit 1
fi

KVER_MAJ_MIN="$(python3 - << 'PY_VER'
import re
txt = open("PKGBUILD").read()
m = re.search(r"^_major=([0-9]+\.[0-9]+)", txt, re.M) or re.search(r"^pkgver=([0-9]+\.[0-9]+)", txt, re.M)
print(m.group(1) if m else "7.3")
PY_VER
)"

echo "  -> Target Kernel Series in PKGBUILD: linux-${KVER_MAJ_MIN}"
echo "  -> Available 15kHz Patch Directories: $(cd "$PATCH_REPO" && ls -d linux-[0-9]* 2>/dev/null | sort -V | tr '\n' ' ')"

if [ -d "$PATCH_REPO/linux-$KVER_MAJ_MIN" ]; then
    PATCH_DIR="$PATCH_REPO/linux-$KVER_MAJ_MIN"
    echo "  -> Exact match found: using $(basename "$PATCH_DIR")"
else
    PATCH_DIR="$(ls -d "$PATCH_REPO"/linux-[0-9]* | sort -V | tail -n 1)"
    echo "  -> Using latest stable patch directory: $(basename "$PATCH_DIR")"
fi

echo "==> [3/6] Copying official 15kHz & interlace patches..."
PATCH_FILES=()
for pf in "$PATCH_DIR"/01_*.patch "$PATCH_DIR"/02_*.patch "$PATCH_DIR"/03_*.patch \
          "$PATCH_DIR"/04_*.patch "$PATCH_DIR"/05_*.patch "$PATCH_DIR"/07_*.patch \
          "$PATCH_DIR"/08_*.patch "$PATCH_DIR"/09_*.patch; do
    if [ -f "$pf" ]; then
        cp -f "$pf" .
        PATCH_FILES+=("$(basename "$pf")")
        echo "  -> Added $(basename "$pf")"
    fi
done

if [ "${#PATCH_FILES[@]}" -eq 0 ]; then
    echo "ERROR: No patch files were found in $PATCH_DIR!" >&2
    exit 1
fi

echo "==> [4/6] Configuring PKGBUILD (Native CPU + GPU Modules + Interlace Patches)..."
sed -i 's/: "${_processor_opt:=.*}"/: "${_processor_opt:=native}"/' PKGBUILD

if pacman -Qq linux-cachyos-nvidia-open >/dev/null 2>&1; then
    echo "  -> Detected linux-cachyos-nvidia-open; enabling _build_nvidia_open:=yes"
    sed -i 's/: "${_build_nvidia_open:=.*}"/: "${_build_nvidia_open:=yes}"/' PKGBUILD
else
    echo "  -> No linux-cachyos-nvidia-open package installed; setting _build_nvidia_open:=no"
    sed -i 's/: "${_build_nvidia_open:=.*}"/: "${_build_nvidia_open:=no}"/' PKGBUILD
fi

python3 - "PKGBUILD" "${PATCH_FILES[@]}" << 'PY_PKGBUILD'
import sys
pkgbuild_path = sys.argv[1]
patches = sys.argv[2:]
txt = open(pkgbuild_path, "r").read()
block_lines = ["\n# --- Custom 15kHz & Interlace Patches ---", "source+=("]
for p in patches:
    block_lines.append(f'  "{p}"')
block_lines.append(")\n")
block = "\n".join(block_lines)
idx = txt.find("\nprepare()")
txt = (txt[:idx] + block + txt[idx:]) if idx != -1 else (txt + block)
open(pkgbuild_path, "w").write(txt)
PY_PKGBUILD

echo "==> [5/6] Updating checksums and compiling kernel..."
updpkgsums
makepkg -Csfi --skippgpcheck

echo "==> [6/6] Ensuring custom EDID files remain embedded in initramfs and syncing bootloader..."
if [ -f /etc/mkinitcpio.conf ] && [ -d /usr/lib/firmware/edid ]; then
    for edid_bin in /usr/lib/firmware/edid/*.bin; do
        [ -f "$edid_bin" ] || continue
        if ! grep -Fq "$edid_bin" /etc/mkinitcpio.conf; then
            sudo sed -i "s|^FILES=(|FILES=($edid_bin |" /etc/mkinitcpio.conf
        fi
    done
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

if [ -f /etc/default/grub ]; then
    if command -v update-grub >/dev/null 2>&1; then
        sudo update-grub
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        sudo grub-mkconfig -o /boot/grub/grub.cfg
    fi
fi

echo "==> SUCCESS! Reboot to load your newly compiled interlaced kernel."
