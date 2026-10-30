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

echo "==> [1/6] Ensuring required build tools are installed..."
sudo pacman -S --needed --noconfirm base-devel git pacman-contrib rust rust-bindgen rust-src python

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

echo "==> [4/6] Configuring GPU driver rules and PKGBUILD (Native CPU + GPU Modules + Interlace Patches)..."
NV_PCI="$(lspci -D -nn 2>/dev/null | grep -E "VGA|3D" | grep -i "10de:" | head -n 1 | awk '{print $1}' || true)"
AMD_LAST_PCI="$(lspci -D -nn 2>/dev/null | grep -E "VGA|Display" | grep -i "1002:" | tail -n 1 | awk '{print $1}' || true)"

mkdir -p "$HOME/.config/environment.d"
echo "KWIN_FORCE_SW_CURSOR=1" > "$HOME/.config/environment.d/kwin-cursor.conf"

if [ -n "$NV_PCI" ] && [ -n "$AMD_LAST_PCI" ]; then
    echo "  -> Detected Dual-GPU NVIDIA ($NV_PCI) + AMD ($AMD_LAST_PCI) setup"
    sudo mkdir -p /etc/udev/rules.d
    cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="$NV_PCI", SYMLINK+="dri/primary-nvidia"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="$AMD_LAST_PCI", SYMLINK+="dri/secondary-amd"
UDEV_EOF
    sudo udevadm control --reload-rules && sudo udevadm trigger
    cat << ENV_EOF > "$HOME/.config/environment.d/nvidia-prime.conf"
KWIN_DRM_DEVICES=/dev/dri/primary-nvidia:/dev/dri/secondary-amd
__NV_PRIME_RENDER_OFFLOAD=1
__GLX_VENDOR_LIBRARY_NAME=nvidia
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
ENV_EOF
else
    rm -f "$HOME/.config/environment.d/nvidia-prime.conf"
    if [ -f /etc/udev/rules.d/99-kwin-gpu.rules ]; then
        sudo rm -f /etc/udev/rules.d/99-kwin-gpu.rules
        sudo udevadm control --reload-rules && sudo udevadm trigger
    fi
fi

sudo mkdir -p /etc/modprobe.d
cat << 'MOD_EOF' | sudo tee /etc/modprobe.d/amdgpu-crt.conf >/dev/null
options radeon si_support=0 cik_support=0
options amdgpu si_support=1 cik_support=1
blacklist radeon
MOD_EOF

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

echo "==> [6/6] Syncing initramfs and bootloader..."
if command -v limine-mkinitcpio >/dev/null 2>&1; then
    sudo limine-mkinitcpio
elif command -v mkinitcpio >/dev/null 2>&1; then
    sudo mkinitcpio -P
fi

if [ -f /etc/default/grub ]; then
    if command -v update-grub >/dev/null 2>&1; then
        sudo update-grub
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        sudo grub-mkconfig -o /boot/grub/grub.cfg
    fi
fi

echo "==> SUCCESS! Reboot to load your newly compiled interlaced kernel."
