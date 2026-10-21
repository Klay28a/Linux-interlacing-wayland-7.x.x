#!/usr/bin/env bash
# Post-Update Kernel Interlace Patcher (Supports Limine, GRUB, systemd-boot & DKMS/Prebuilt NVIDIA)
set -euo pipefail
umask 022

BUILD_ROOT="$HOME/kernel-build"
CACHY_REPO="$BUILD_ROOT/linux-cachyos"
PATCH_REPO="$BUILD_ROOT/linux_kernel_15khz"

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Do not run this script as root/sudo. makepkg must run as a regular user."
    exit 1
fi

echo "==> [1/6] Checking required build dependencies..."
sudo pacman -S --needed --noconfirm base-devel git pacman-contrib rust rust-bindgen rust-src

mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"

echo "==> [2/6] Fetching latest kernel PKGBUILD and 15kHz interlace patches..."
if [ ! -d "$CACHY_REPO/.git" ]; then
    git clone --depth 1 https://github.com/CachyOS/linux-cachyos.git "$CACHY_REPO"
else
    git -C "$CACHY_REPO" fetch --depth 1 origin
    git -C "$CACHY_REPO" reset --hard origin/HEAD
    git -C "$CACHY_REPO" clean -fd
fi

if [ ! -d "$PATCH_REPO/.git" ]; then
    git clone --depth 1 https://github.com/D0023R/linux_kernel_15khz.git "$PATCH_REPO"
else
    git -C "$PATCH_REPO" fetch --depth 1 origin
    git -C "$PATCH_REPO" reset --hard origin/HEAD
fi

cd "$CACHY_REPO/linux-cachyos"

# Automatically match the kernel major.minor version to the patch directory (e.g., linux-7.2)
KVER_MAJ_MIN=$(grep -E "^_major=|^pkgver=" PKGBUILD | head -n 1 | grep -oE "[0-9]+\.[0-9]+" || echo "7.2")
if [ -d "$PATCH_REPO/linux-$KVER_MAJ_MIN" ]; then
    PATCH_DIR="$PATCH_REPO/linux-$KVER_MAJ_MIN"
else
    PATCH_DIR=$(ls -d "$PATCH_REPO"/linux-* | sort -V | tail -n 1)
fi

echo "==> [3/6] Copying interlace patches from $(basename "$PATCH_DIR")..."
cp "$PATCH_DIR"/01_linux_15khz.patch .
cp "$PATCH_DIR"/02_linux_15khz_interlaced_mode_fix.patch .
cp "$PATCH_DIR"/03_linux_15khz_dcn1_dcn2_dcn3_dcn4_interlaced_mode_fix.patch .
cp "$PATCH_DIR"/04_linux_15khz_dce_interlaced_mode_fix.patch .
cp "$PATCH_DIR"/05_linux_15khz_amdgpu_pll_fix.patch .

echo "==> [4/6] Configuring PKGBUILD options..."
sed -i 's/_processor_opt:=/_processor_opt:=native/' PKGBUILD

# Only build bundled linux-cachyos-nvidia-open if the user has that package installed
# (Users on nvidia-open-dkms or AMD-only systems do not need it bundled)
if pacman -Qq linux-cachyos-nvidia-open >/dev/null 2>&1; then
    echo "  -> Detected installed linux-cachyos-nvidia-open package; enabling _build_nvidia_open:=yes"
    sed -i 's/_build_nvidia_open:=no/_build_nvidia_open:=yes/' PKGBUILD
elif pacman -Qq nvidia-open-dkms nvidia-dkms >/dev/null 2>&1; then
    echo "  -> Detected NVIDIA DKMS setup; DKMS will automatically build modules on install."
fi

cat << 'PATCH_EOF' >> PKGBUILD

source+=(
  "01_linux_15khz.patch"
  "02_linux_15khz_interlaced_mode_fix.patch"
  "03_linux_15khz_dcn1_dcn2_dcn3_dcn4_interlaced_mode_fix.patch"
  "04_linux_15khz_dce_interlaced_mode_fix.patch"
  "05_linux_15khz_amdgpu_pll_fix.patch"
)
PATCH_EOF

echo "==> [5/6] Updating source checksums and compiling patched kernel..."
updpkgsums
makepkg -Csfi --skippgpcheck

echo "==> [6/6] Updating initramfs and bootloader (Limine / GRUB / systemd-boot)..."
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

echo "==> SUCCESS! Reboot your system to use interlaced modes on the updated kernel."
