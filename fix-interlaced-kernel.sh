#!/usr/bin/env bash
# Script 2: 15kHz, Interlace & RDNA DP/HDMI Adapter Kernel Patcher for CachyOS / Arch
# Works standalone, via CLI flags, or from the Linux Interlacing Suite GUI alongside setup-interlace-env.sh and linux-cru.
# Supports:
#   - GPU Profiles : auto, rdna-single, gcn-single, nvidia-single, dual-nvidia-amd, dual-amd-amd
#   - Adapter Modes: auto, dp-dac (DisplayPort DAC adapter), hdmi-dac (HDMI DAC adapter), analog-native
#   - Bootloaders  : Limine, GRUB, systemd-boot
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RDNA_PATCH_SRC="$SCRIPT_DIR/11_linux_rdna_dp_hdmi_interlace.patch"

BUILD_ROOT="${BUILD_ROOT:-$HOME/kernel-build}"
CACHY_REPO="$BUILD_ROOT/linux-cachyos"
PATCH_REPO="$BUILD_ROOT/linux_kernel_15khz"

GPU_PROFILE="auto"
ADAPTER_MODE="auto"
KERNEL_VERSION="auto"
INCLUDE_RDNA_PATCH=1
CONFIG_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --gpu-profile)
            GPU_PROFILE="${2:-auto}"
            shift 2
            ;;
        --gpu-profile=*)
            GPU_PROFILE="${1#*=}"
            shift
            ;;
        --adapter-mode)
            ADAPTER_MODE="${2:-auto}"
            shift 2
            ;;
        --adapter-mode=*)
            ADAPTER_MODE="${1#*=}"
            shift
            ;;
        --kernel-version)
            KERNEL_VERSION="${2:-auto}"
            shift 2
            ;;
        --kernel-version=*)
            KERNEL_VERSION="${1#*=}"
            shift
            ;;
        --no-rdna-patch)
            INCLUDE_RDNA_PATCH=0
            shift
            ;;
        --config-only)
            CONFIG_ONLY=1
            shift
            ;;
        -h|--help)
            cat << 'HELP_EOF'
Usage: ./fix-interlaced-kernel.sh [OPTIONS]

Options:
  --gpu-profile <PROFILE>   GPU architecture & setup mode:
                              auto            Auto-detect from PCI hardware (default)
                              rdna-single     Single GPU: AMD RDNA 1/2/3/4
                              gcn-single      Single GPU: AMD GCN 1-5 / Polaris / Vega
                              nvidia-single   Single GPU: NVIDIA (Proprietary / Open Kernel Module)
                              dual-nvidia-amd Dual GPU: NVIDIA Primary + AMD Secondary
                              dual-amd-amd    Dual GPU: AMD Primary + AMD Secondary
  --adapter-mode <MODE>     Adapter preset (auto, dp-dac, hdmi-dac, analog-native)
  --kernel-version <VER>    Target Linux kernel & 15kHz patch series to fetch & compile:
                              auto            Auto-detect from running kernel / latest mainline (default)
                              7.3             Linux 7.3 Mainline (linux-cachyos + linux-7.3 patches)
                              7.2             Linux 7.2 Stable (linux-cachyos 7.2.11 + linux-7.2 patches)
                              6.18            Linux 6.18 LTS (linux-cachyos-lts + linux-6.18 patches)
                              6.12            Linux 6.12 LTS (linux-cachyos-lts 6.12.69 + linux-6.12 patches)
                              6.6             Linux 6.6 LTS (linux-cachyos-lts 6.6.51 + linux-6.6 patches)
                              6.1             Linux 6.1 LTS (linux-cachyos-lts 6.1.55 + linux-6.1 patches)
                              linux-next      Linux RC / Next (linux-cachyos-rc + linux-next patches)
  --no-rdna-patch           Skip applying 11_linux_rdna_dp_hdmi_interlace.patch
  --config-only             Apply GPU architecture / multi-GPU udev & modprobe rules only (skip kernel build)
HELP_EOF
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done


if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Run this script as your normal user, not root/sudo." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Detect PCI GPUs & Resolve GPU Architecture Profile
# ------------------------------------------------------------------------------
NV_LINE="$(lspci -D -nn 2>/dev/null | grep -E "VGA|3D|Display" | grep -i "10de:" | head -n 1 || true)"
AMD_LINES="$(lspci -D -nn 2>/dev/null | grep -E "VGA|3D|Display" | grep -i "1002:" || true)"
AMD_COUNT="$(printf "%s\n" "$AMD_LINES" | sed '/^$/d' | wc -l)"
AMD_FIRST_LINE="$(printf "%s\n" "$AMD_LINES" | head -n 1)"
AMD_LAST_LINE="$(printf "%s\n" "$AMD_LINES" | tail -n 1)"

NV_PCI="$(awk '{print $1}' <<<"$NV_LINE")"
AMD_FIRST_PCI="$(awk '{print $1}' <<<"$AMD_FIRST_LINE")"
AMD_LAST_PCI="$(awk '{print $1}' <<<"$AMD_LAST_LINE")"

NV_DEVID="$(sed -n 's/.*\[10de:\([0-9a-fA-F]\{4\}\)\].*/\1/p' <<<"$NV_LINE" | tr '[:upper:]' '[:lower:]')"
AMD_FIRST_DEVID="$(sed -n 's/.*\[1002:\([0-9a-fA-F]\{4\}\)\].*/\1/p' <<<"$AMD_FIRST_LINE" | tr '[:upper:]' '[:lower:]')"
AMD_DEVID="$(sed -n 's/.*\[1002:\([0-9a-fA-F]\{4\}\)\].*/\1/p' <<<"$AMD_LAST_LINE" | tr '[:upper:]' '[:lower:]')"

is_rdna_gpu() {
    local line="$1"
    local devid="$2"
    if grep -qiE "Navi|RDNA|Radeon RX [56789][0-9]{3}" <<<"$line"; then
        return 0
    fi
    case "$devid" in
        73[1-9a-f][0-9a-f]|74[0-9a-f][0-9a-f]|75[0-9a-f][0-9a-f]|15bf|15c8|163f|164d|1681|1900)
            return 0
            ;;
    esac
    return 1
}

HAS_ANALOG_DRM=0
for st in /sys/class/drm/card*-*/status; do
    [ -e "$st" ] || continue
    sn="$(basename "$(dirname "$st")")"
    sn="${sn#card*-}"
    if [[ "$sn" == VGA-* || "$sn" == DVI-I-* ]]; then
        HAS_ANALOG_DRM=1
        break
    fi
done

if [ "$GPU_PROFILE" = "auto" ]; then
    if [ -n "$NV_DEVID" ] && [ -n "$AMD_DEVID" ]; then
        RESOLVED_PROFILE="dual-nvidia-amd"
    elif [ "$AMD_COUNT" -ge 2 ]; then
        RESOLVED_PROFILE="dual-amd-amd"
    elif [ -n "$NV_DEVID" ] && [ -z "$AMD_DEVID" ]; then
        RESOLVED_PROFILE="nvidia-single"
    elif is_rdna_gpu "$AMD_LAST_LINE" "$AMD_DEVID" || [ "$HAS_ANALOG_DRM" -eq 0 ]; then
        RESOLVED_PROFILE="rdna-single"
    else
        RESOLVED_PROFILE="gcn-single"
    fi
else
    RESOLVED_PROFILE="$GPU_PROFILE"
fi

echo "==> Selected GPU Architecture Profile: $RESOLVED_PROFILE (requested: $GPU_PROFILE | adapter: $ADAPTER_MODE)"

apply_gpu_profile_rules() {
    mkdir -p "$HOME/.config/environment.d"
    echo "KWIN_FORCE_SW_CURSOR=1" > "$HOME/.config/environment.d/kwin-cursor.conf"

    case "$RESOLVED_PROFILE" in
        dual-nvidia-amd)
            echo "  -> Configuring Dual-GPU NVIDIA (${NV_DEVID:-auto} @ ${NV_PCI:-pci}) + AMD (${AMD_DEVID:-auto} @ ${AMD_LAST_PCI:-pci}) setup..."
            rm -f "$HOME/.config/environment.d/amd-dual-gpu.conf"
            if [ -n "$NV_DEVID" ] && [ -n "$AMD_DEVID" ]; then
                sudo mkdir -p /etc/udev/rules.d
                cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
# PCI-slot-independent Dual-GPU DRM symlinks (immune to M.2 NVMe PCIe bus renumbering)
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x10de", ATTRS{device}=="0x$NV_DEVID", SYMLINK+="dri/primary-nvidia"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_DEVID", SYMLINK+="dri/secondary-amd"
UDEV_EOF
                sudo udevadm control --reload-rules && sudo udevadm trigger
                cat << ENV_EOF > "$HOME/.config/environment.d/nvidia-prime.conf"
KWIN_DRM_DEVICES=/dev/dri/primary-nvidia:/dev/dri/secondary-amd
__NV_PRIME_RENDER_OFFLOAD=1
__GLX_VENDOR_LIBRARY_NAME=nvidia
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
ENV_EOF
            fi
            sudo mkdir -p /etc/modprobe.d
            cat << 'MOD_EOF' | sudo tee /etc/modprobe.d/amdgpu-crt.conf >/dev/null
options radeon si_support=0 cik_support=0
options amdgpu si_support=1 cik_support=1
blacklist radeon
MOD_EOF
            ;;
        dual-amd-amd)
            echo "  -> Configuring Dual-GPU AMD Primary (${AMD_FIRST_DEVID:-auto}) + AMD Secondary (${AMD_DEVID:-auto}) setup..."
            rm -f "$HOME/.config/environment.d/nvidia-prime.conf"
            sudo mkdir -p /etc/udev/rules.d
            if [ -n "$AMD_FIRST_DEVID" ] && [ -n "$AMD_DEVID" ] && [ "$AMD_FIRST_DEVID" != "$AMD_DEVID" ]; then
                cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
# PCI-slot-independent Dual-AMD DRM symlinks
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_FIRST_DEVID", SYMLINK+="dri/primary-amd"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_DEVID", SYMLINK+="dri/secondary-amd"
UDEV_EOF
            elif [ -n "$AMD_FIRST_PCI" ] && [ -n "$AMD_LAST_PCI" ]; then
                cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
# Dual-AMD DRM symlinks by PCI slot
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="$AMD_FIRST_PCI", SYMLINK+="dri/primary-amd"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="$AMD_LAST_PCI", SYMLINK+="dri/secondary-amd"
UDEV_EOF
            fi
            sudo udevadm control --reload-rules && sudo udevadm trigger
            cat << 'ENV_EOF' > "$HOME/.config/environment.d/amd-dual-gpu.conf"
KWIN_DRM_DEVICES=/dev/dri/primary-amd:/dev/dri/secondary-amd
ENV_EOF
            sudo mkdir -p /etc/modprobe.d
            cat << 'MOD_EOF' | sudo tee /etc/modprobe.d/amdgpu-crt.conf >/dev/null
options radeon si_support=0 cik_support=0
options amdgpu si_support=1 cik_support=1
blacklist radeon
MOD_EOF
            ;;
        rdna-single|nvidia-single)
            echo "  -> Configuring Single-GPU ($RESOLVED_PROFILE) setup (cleaning legacy radeon SI/CIK & dual-GPU overrides)..."
            rm -f "$HOME/.config/environment.d/nvidia-prime.conf" "$HOME/.config/environment.d/amd-dual-gpu.conf"
            if [ -f /etc/udev/rules.d/99-kwin-gpu.rules ]; then
                sudo rm -f /etc/udev/rules.d/99-kwin-gpu.rules
                sudo udevadm control --reload-rules && sudo udevadm trigger
            fi
            if [ -f /etc/modprobe.d/amdgpu-crt.conf ]; then
                sudo rm -f /etc/modprobe.d/amdgpu-crt.conf
            fi
            ;;
        gcn-single|*)
            echo "  -> Configuring Single-GPU AMD GCN/DCE setup (enabling amdgpu SI/CIK support)..."
            rm -f "$HOME/.config/environment.d/nvidia-prime.conf" "$HOME/.config/environment.d/amd-dual-gpu.conf"
            if [ -f /etc/udev/rules.d/99-kwin-gpu.rules ]; then
                sudo rm -f /etc/udev/rules.d/99-kwin-gpu.rules
                sudo udevadm control --reload-rules && sudo udevadm trigger
            fi
            sudo mkdir -p /etc/modprobe.d
            cat << 'MOD_EOF' | sudo tee /etc/modprobe.d/amdgpu-crt.conf >/dev/null
options radeon si_support=0 cik_support=0
options amdgpu si_support=1 cik_support=1
blacklist radeon
MOD_EOF
            ;;
    esac
}

if [ "$CONFIG_ONLY" -eq 1 ]; then
    echo "==> [1/2] Applying GPU architecture & multi-GPU driver configuration only (--config-only)..."
    apply_gpu_profile_rules
    echo "==> [2/2] Syncing initramfs..."
    if command -v limine-mkinitcpio >/dev/null 2>&1; then
        sudo limine-mkinitcpio
    elif command -v mkinitcpio >/dev/null 2>&1; then
        sudo mkinitcpio -P
    fi
    echo "==> SUCCESS! GPU profile '$RESOLVED_PROFILE' applied."
    exit 0
fi

echo "==> [1/6] Ensuring required build tools are installed..."
REQ_PKGS=(base-devel git pacman-contrib rust rust-bindgen rust-src python bc cpio gettext libelf openssl pahole perl tar xxhash xz zlib zstd clang llvm lld)
MISSING_PKGS=($(pacman -T "${REQ_PKGS[@]}" || true))
if [ "${#MISSING_PKGS[@]}" -gt 0 ]; then
    echo "  -> Installing missing build dependencies: ${MISSING_PKGS[*]}"
    sudo pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
else
    echo "  -> All required build tools and dependencies are already installed."
fi


mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"

# Resolve target kernel series and CachyOS PKGBUILD directory/commit
if [ "$KERNEL_VERSION" = "auto" ]; then
    RUNNING_MAJ_MIN="$(uname -r | grep -oE '^[0-9]+\.[0-9]+' || echo "7.3")"
    case "$RUNNING_MAJ_MIN" in
        7.3|7.2|6.18|6.12|6.6|6.1)
            TARGET_KVER="$RUNNING_MAJ_MIN"
            ;;
        *)
            TARGET_KVER="7.3"
            ;;
    esac
else
    TARGET_KVER="$KERNEL_VERSION"
fi

case "$TARGET_KVER" in
    7.3)
        CACHY_SUBDIR="linux-cachyos"
        CACHY_COMMIT="origin/master"
        WANT_PATCH_SERIES="linux-7.3"
        ;;
    7.2)
        CACHY_SUBDIR="linux-cachyos"
        CACHY_COMMIT="4a8d2ec8509d0da7d5fd5293f42251ea99d5ea3c"
        WANT_PATCH_SERIES="linux-7.2"
        ;;
    6.18)
        CACHY_SUBDIR="linux-cachyos-lts"
        CACHY_COMMIT="origin/master"
        WANT_PATCH_SERIES="linux-6.18"
        ;;
    6.12)
        CACHY_SUBDIR="linux-cachyos-lts"
        CACHY_COMMIT="1a3b979f284e343eb56a73c45c0ad8d3bf11ecde"
        WANT_PATCH_SERIES="linux-6.12"
        ;;
    6.6)
        CACHY_SUBDIR="linux-cachyos-lts"
        CACHY_COMMIT="07ecd945b581930dbf8212bd57b7dd90f3ed51a1"
        WANT_PATCH_SERIES="linux-6.6"
        ;;
    6.1)
        CACHY_SUBDIR="linux-cachyos-lts"
        CACHY_COMMIT="97ec6edeea4f4fba456e17bbfc49a8d0fdd5bf11"
        WANT_PATCH_SERIES="linux-6.1"
        ;;
    linux-next|rc)
        CACHY_SUBDIR="linux-cachyos-rc"
        CACHY_COMMIT="origin/master"
        WANT_PATCH_SERIES="linux-next"
        ;;
    *)
        CACHY_SUBDIR="linux-cachyos"
        CACHY_COMMIT="origin/master"
        WANT_PATCH_SERIES="linux-${TARGET_KVER}"
        ;;
esac

echo "==> [2/6] Fetching CachyOS kernel PKGBUILD ($CACHY_SUBDIR @ $TARGET_KVER) and 15kHz/interlace patches..."
if [ ! -d "$CACHY_REPO/.git" ]; then
    git clone --depth 1 https://github.com/CachyOS/linux-cachyos.git "$CACHY_REPO"
fi

if [ "$CACHY_COMMIT" = "origin/master" ]; then
    git -C "$CACHY_REPO" fetch --depth 1 origin master
    git -C "$CACHY_REPO" reset --hard FETCH_HEAD
else
    git -C "$CACHY_REPO" fetch --depth 1 origin "$CACHY_COMMIT"
    git -C "$CACHY_REPO" reset --hard "$CACHY_COMMIT"
fi
git -C "$CACHY_REPO" clean -fd -e '*.tar.*' -e '*.run' -e '*.asc'

if [ ! -d "$PATCH_REPO/.git" ]; then
    git clone --depth 1 https://github.com/D0023R/linux_kernel_15khz.git "$PATCH_REPO"
else
    git -C "$PATCH_REPO" fetch --depth 1 origin
    git -C "$PATCH_REPO" reset --hard FETCH_HEAD
    git -C "$PATCH_REPO" clean -fd
fi

cd "$CACHY_REPO/$CACHY_SUBDIR"

if [ ! -f PKGBUILD ]; then
    echo "ERROR: PKGBUILD not found in $CACHY_REPO/$CACHY_SUBDIR" >&2
    exit 1
fi

KVER_MAJ_MIN="$(python3 - << 'PY_VER'
import re
txt = open("PKGBUILD").read()
m = re.search(r"^_major=([0-9]+\.[0-9]+)", txt, re.M) or re.search(r"^pkgver=([0-9]+\.[0-9]+)", txt, re.M)
print(m.group(1) if m else "7.3")
PY_VER
)"

echo "  -> Target Kernel Series in PKGBUILD: linux-${KVER_MAJ_MIN} ($CACHY_SUBDIR)"
echo "  -> Available 15kHz Patch Directories: $(cd "$PATCH_REPO" && ls -d linux-* 2>/dev/null | sort -V | tr '\n' ' ')"

if [ -d "$PATCH_REPO/$WANT_PATCH_SERIES" ]; then
    PATCH_DIR="$PATCH_REPO/$WANT_PATCH_SERIES"
    echo "  -> Selected 15kHz patch directory: $(basename "$PATCH_DIR")"
elif [ -d "$PATCH_REPO/linux-$KVER_MAJ_MIN" ]; then
    PATCH_DIR="$PATCH_REPO/linux-$KVER_MAJ_MIN"
    echo "  -> Exact match found: using $(basename "$PATCH_DIR")"
else
    PATCH_DIR="$(ls -d "$PATCH_REPO"/linux-[0-9]* | sort -V | tail -n 1)"
    echo "  -> Using latest stable patch directory: $(basename "$PATCH_DIR")"
fi


echo "==> [3/6] Copying official 15kHz, interlace & RDNA DP/HDMI adapter patches..."
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

if [ "$INCLUDE_RDNA_PATCH" -eq 1 ] && [ -f "$RDNA_PATCH_SRC" ]; then
    cp -f "$RDNA_PATCH_SRC" .
    PATCH_FILES+=("$(basename "$RDNA_PATCH_SRC")")
    echo "  -> Added $(basename "$RDNA_PATCH_SRC") (RDNA DCN & DP/HDMI DAC Adapter Interlace Unlock)"
fi

if [ "${#PATCH_FILES[@]}" -eq 0 ]; then
    echo "ERROR: No patch files were found in $PATCH_DIR!" >&2
    exit 1
fi

echo "==> [4/6] Configuring GPU driver rules and PKGBUILD (Native CPU + GPU Profile '$RESOLVED_PROFILE' + Interlace Patches)..."
apply_gpu_profile_rules

sed -i 's/: "${_processor_opt:=.*}"/: "${_processor_opt:=native}"/' PKGBUILD

if pacman -Qq linux-cachyos-nvidia-open >/dev/null 2>&1 || pacman -Qq linux-cachyos-lts-nvidia-open >/dev/null 2>&1; then
    INSTALLED_NV_VER="$(pacman -Q nvidia-utils 2>/dev/null | awk '{print $2}' | cut -d- -f1 || true)"
    if [ -n "$INSTALLED_NV_VER" ] && grep -q "^_nv_ver=${INSTALLED_NV_VER}$" PKGBUILD; then
        echo "  -> Detected matching nvidia-utils ($INSTALLED_NV_VER); enabling _build_nvidia_open:=yes"
        sed -i 's/: "${_build_nvidia_open:=.*}"/: "${_build_nvidia_open:=yes}"/' PKGBUILD
    else
        echo "  -> PKGBUILD _nv_ver differs from host nvidia-utils ($INSTALLED_NV_VER); setting _build_nvidia_open:=no for compatibility"
        sed -i 's/: "${_build_nvidia_open:=.*}"/: "${_build_nvidia_open:=no}"/' PKGBUILD
    fi
else
    echo "  -> No linux-cachyos-nvidia-open package installed; setting _build_nvidia_open:=no"
    sed -i 's/: "${_build_nvidia_open:=.*}"/: "${_build_nvidia_open:=no}"/' PKGBUILD
fi


python3 - "PKGBUILD" "${PATCH_FILES[@]}" << 'PY_PKGBUILD'
import hashlib, re, sys

pkgbuild_path = sys.argv[1]
patches = sys.argv[2:]
txt = open(pkgbuild_path, "r").read()

# Relax strict pahole pkgrel constraint (e.g. 'pahole>=1:1.32-2' -> 'pahole') so makepkg
# does not abort with exit code 8 when the local repo has pahole 1:1.32-1.1 installed.
txt = re.sub(r"'pahole>=[^']*'", "'pahole'", txt)
txt = re.sub(r'"nvidia-utils=\$\{_nv_ver\}"', '"nvidia-utils"', txt)

block_lines = ["\n# --- Custom 15kHz, Interlace & RDNA DP/HDMI DAC Patches ---", "source+=("]
sum_lines = ["\nb2sums+=("]
for p in patches:
    block_lines.append(f'  "{p}"')
    h = hashlib.blake2b(open(p, "rb").read()).hexdigest()
    sum_lines.append(f"  '{h}'")
block_lines.append(")\n")
sum_lines.append(")\n")

block = "\n".join(block_lines)
idx = txt.find("\nprepare()")
txt = (txt[:idx] + block + txt[idx:]) if idx != -1 else (txt + block)
txt = txt.rstrip() + "\n" + "\n".join(sum_lines)
open(pkgbuild_path, "w").write(txt)
PY_PKGBUILD

echo "==> [5/6] Compiling and installing patched kernel..."
makepkg -Csfi --noconfirm --skipinteg



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
