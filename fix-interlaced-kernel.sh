#!/usr/bin/env bash
# 15kHz, Interlace & RDNA DP/HDMI adapter kernel patcher for CachyOS / Arch.
# Build orchestration only (git + makepkg). GPU rules, PKGBUILD edits and the RDNA source patcher
# live in unit-tested Python: interlace_apply_rules.py, interlace_pkgbuild.py, interlace_rdna_patch.py.
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="${BUILD_ROOT:-$HOME/kernel-build}"
CACHY_REPO="$BUILD_ROOT/linux-cachyos"
PATCH_REPO="$BUILD_ROOT/linux_kernel_15khz"

GPU_PROFILE="auto"
ADAPTER_MODE="auto"
KERNEL_VERSION="auto"
PROCESSOR_OPT="native"
INCLUDE_RDNA_PATCH=1
CONFIG_ONLY=0
DRY_RUN=0

usage() {
    cat << 'HELP_EOF'
Usage: ./fix-interlaced-kernel.sh [OPTIONS]

Options:
  --gpu-profile <PROFILE>   auto | rdna-single | gcn-single | nvidia-single | dual-nvidia-amd | dual-amd-amd
  --adapter-mode <MODE>     Adapter preset (auto, dp-dac, hdmi-dac, analog-native)
  --kernel-version <VER>    auto | 7.3 | 7.2 | 6.18 | 6.12 | 6.6 | 6.1 | linux-next
  --processor-opt <OPT>     CachyOS _processor_opt (default: native = tuned for THIS machine only)
  --no-rdna-patch           Skip the RDNA DP/HDMI DAC source patcher
  --config-only             Apply GPU rules + initramfs only (skip the kernel build)
  --dry-run                 Print every command that would run; change nothing
  -h, --help                Show this help
HELP_EOF
}

need_value() {
    if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "ERROR: $1 requires a value" >&2
        exit 2
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --gpu-profile|--adapter-mode|--kernel-version|--processor-opt)
            need_value "$@"
            case "$1" in
                --gpu-profile) GPU_PROFILE="$2" ;;
                --adapter-mode) ADAPTER_MODE="$2" ;;
                --kernel-version) KERNEL_VERSION="$2" ;;
                --processor-opt) PROCESSOR_OPT="$2" ;;
            esac
            shift 2
            ;;
        --gpu-profile=*) GPU_PROFILE="${1#*=}"; shift ;;
        --adapter-mode=*) ADAPTER_MODE="${1#*=}"; shift ;;
        --kernel-version=*) KERNEL_VERSION="${1#*=}"; shift ;;
        --processor-opt=*) PROCESSOR_OPT="${1#*=}"; shift ;;
        --no-rdna-patch) INCLUDE_RDNA_PATCH=0; shift ;;
        --config-only) CONFIG_ONLY=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "ERROR: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$(id -u)" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "ERROR: Run this script as your normal user, not root/sudo." >&2
    exit 1
fi

# Non-interactive privilege escalation unless a terminal or the GUI's SUDO_ASKPASS is available.
if [ -n "${SUDO_ASKPASS:-}" ] || [ -t 0 ]; then
    SUDO=(sudo)
else
    SUDO=(sudo -n)
fi

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '[dry-run] would run:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

py() {
    local script="$1"
    shift
    python3 "$SCRIPT_DIR/$script" "$@"
}

DRY_ARGS=()
if [ "$DRY_RUN" -eq 1 ]; then
    DRY_ARGS=(--dry-run)
fi

RESOLVED_PROFILE="$(py interlace_apply_rules.py --gpu-profile "$GPU_PROFILE" --print-profile)"
echo "==> Selected GPU Architecture Profile: $RESOLVED_PROFILE (requested: $GPU_PROFILE | adapter: $ADAPTER_MODE)"

if [ "$CONFIG_ONLY" -eq 1 ]; then
    echo "==> [1/1] Applying GPU architecture & multi-GPU driver configuration only (--config-only)..."
    py interlace_apply_rules.py --gpu-profile "$RESOLVED_PROFILE" "${DRY_ARGS[@]}"
    echo "==> SUCCESS! GPU profile '$RESOLVED_PROFILE' applied."
    exit 0
fi

if ! command -v pacman >/dev/null 2>&1 || ! command -v makepkg >/dev/null 2>&1; then
    echo "ERROR: Building the patched kernel needs an Arch-based system (pacman + makepkg)." >&2
    echo "       Use --config-only to apply just the GPU rules on this distribution." >&2
    exit 1
fi

echo "==> [1/6] Ensuring required build tools are installed..."
REQ_PKGS=(base-devel git pacman-contrib rust rust-bindgen rust-src python bc cpio gettext libelf openssl pahole perl tar xxhash xz zlib zstd clang llvm lld)
mapfile -t MISSING_PKGS < <(pacman -T "${REQ_PKGS[@]}" || true)
if [ "${#MISSING_PKGS[@]}" -gt 0 ]; then
    echo "  -> Installing missing build dependencies: ${MISSING_PKGS[*]}"
    run "${SUDO[@]}" pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
else
    echo "  -> All required build tools and dependencies are already installed."
fi

# Resolve the target kernel series. The pinned SHAs select the CachyOS PKGBUILD revision that
# matches that series; anything not listed builds from the PKGBUILD repo's current master.
if [ "$KERNEL_VERSION" = "auto" ]; then
    TARGET_KVER="$(uname -r | grep -oE '^[0-9]+\.[0-9]+' || true)"
    if [ -z "$TARGET_KVER" ]; then
        echo "ERROR: could not determine the running kernel series; pass --kernel-version." >&2
        exit 1
    fi
else
    TARGET_KVER="$KERNEL_VERSION"
fi

CACHY_SUBDIR="linux-cachyos"
CACHY_COMMIT="origin/master"
WANT_PATCH_SERIES="linux-${TARGET_KVER}"
case "$TARGET_KVER" in
    7.2) CACHY_COMMIT="4a8d2ec8509d0da7d5fd5293f42251ea99d5ea3c" ;;
    6.18) CACHY_SUBDIR="linux-cachyos-lts" ;;
    6.12) CACHY_SUBDIR="linux-cachyos-lts"; CACHY_COMMIT="1a3b979f284e343eb56a73c45c0ad8d3bf11ecde" ;;
    6.6) CACHY_SUBDIR="linux-cachyos-lts"; CACHY_COMMIT="07ecd945b581930dbf8212bd57b7dd90f3ed51a1" ;;
    6.1) CACHY_SUBDIR="linux-cachyos-lts"; CACHY_COMMIT="97ec6edeea4f4fba456e17bbfc49a8d0fdd5bf11" ;;
    linux-next|rc) CACHY_SUBDIR="linux-cachyos-rc"; WANT_PATCH_SERIES="linux-next" ;;
    *) ;;
esac

echo "==> [2/6] Fetching CachyOS kernel PKGBUILD ($CACHY_SUBDIR @ $TARGET_KVER) and 15kHz/interlace patches..."
run mkdir -p "$BUILD_ROOT"
if [ ! -d "$CACHY_REPO/.git" ]; then
    run git clone --depth 1 https://github.com/CachyOS/linux-cachyos.git "$CACHY_REPO"
fi
if [ "$CACHY_COMMIT" = "origin/master" ]; then
    run git -C "$CACHY_REPO" fetch --depth 1 origin master
    run git -C "$CACHY_REPO" reset --hard FETCH_HEAD
else
    run git -C "$CACHY_REPO" fetch --depth 1 origin "$CACHY_COMMIT"
    run git -C "$CACHY_REPO" reset --hard "$CACHY_COMMIT"
fi
run git -C "$CACHY_REPO" clean -fd -e '*.tar.*' -e '*.run' -e '*.asc'

if [ ! -d "$PATCH_REPO/.git" ]; then
    run git clone --depth 1 https://github.com/D0023R/linux_kernel_15khz.git "$PATCH_REPO"
else
    run git -C "$PATCH_REPO" fetch --depth 1 origin
    run git -C "$PATCH_REPO" reset --hard FETCH_HEAD
    run git -C "$PATCH_REPO" clean -fd
fi

if [ "$DRY_RUN" -eq 1 ] && [ ! -f "$CACHY_REPO/$CACHY_SUBDIR/PKGBUILD" ]; then
    echo "[dry-run] sources are not fetched yet, so the remaining steps cannot be previewed in detail:"
    echo "[dry-run]   [3/6] copy patches, [4/6] GPU rules + PKGBUILD edit, [5/6] makepkg -Csfi, [6/6] sync initramfs/bootloader"
    exit 0
fi

cd "$CACHY_REPO/$CACHY_SUBDIR"
if [ ! -f PKGBUILD ]; then
    echo "ERROR: PKGBUILD not found in $CACHY_REPO/$CACHY_SUBDIR" >&2
    exit 1
fi
KVER_MAJ_MIN="$(sed -nE 's/^_major=([0-9]+\.[0-9]+).*/\1/p; s/^pkgver=([0-9]+\.[0-9]+).*/\1/p' PKGBUILD | head -n 1)"
KVER_MAJ_MIN="${KVER_MAJ_MIN:-$TARGET_KVER}"
echo "  -> Target Kernel Series in PKGBUILD: linux-${KVER_MAJ_MIN} ($CACHY_SUBDIR)"

mapfile -t PATCH_SERIES_DIRS < <(find "$PATCH_REPO" -maxdepth 1 -type d -name 'linux-[0-9]*' | sort -V)
echo "  -> Available 15kHz Patch Directories: $(printf '%s ' "${PATCH_SERIES_DIRS[@]##*/}")"
if [ -d "$PATCH_REPO/$WANT_PATCH_SERIES" ]; then
    PATCH_DIR="$PATCH_REPO/$WANT_PATCH_SERIES"
elif [ -d "$PATCH_REPO/linux-$KVER_MAJ_MIN" ]; then
    PATCH_DIR="$PATCH_REPO/linux-$KVER_MAJ_MIN"
elif [ "${#PATCH_SERIES_DIRS[@]}" -gt 0 ]; then
    PATCH_DIR="${PATCH_SERIES_DIRS[-1]}"
    echo "  -> No exact patch series match; using the latest available: ${PATCH_DIR##*/}"
else
    echo "ERROR: no linux-* patch directories found in $PATCH_REPO" >&2
    exit 1
fi
echo "  -> Selected 15kHz patch directory: ${PATCH_DIR##*/}"

echo "==> [3/6] Copying official 15kHz, interlace & RDNA DP/HDMI adapter patches..."
PATCH_FILES=()
for n in 01 02 03 04 05 07 08 09; do
    for pf in "$PATCH_DIR/${n}_"*.patch; do
        [ -f "$pf" ] || continue
        run cp -f "$pf" .
        PATCH_FILES+=("$(basename "$pf")")
        echo "  -> Added $(basename "$pf")"
    done
done
if [ "${#PATCH_FILES[@]}" -eq 0 ]; then
    echo "ERROR: No patch files were found in $PATCH_DIR!" >&2
    exit 1
fi

PKG_ARGS=()
if [ "$INCLUDE_RDNA_PATCH" -eq 1 ]; then
    # The prepare() hook runs this file from the extracted source tree, so it is listed in source=().
    run cp -f "$SCRIPT_DIR/interlace_rdna_patch.py" apply_rdna_dac_unlock.py
    PATCH_FILES+=("apply_rdna_dac_unlock.py")
    PKG_ARGS+=(--include-rdna)
    echo "  -> Prepared RDNA DCN & DP/HDMI DAC Interlace Unlock (apply_rdna_dac_unlock.py)"
fi

echo "==> [4/6] Configuring GPU driver rules and PKGBUILD (GPU Profile '$RESOLVED_PROFILE' + Interlace Patches)..."
py interlace_apply_rules.py --gpu-profile "$RESOLVED_PROFILE" --no-initramfs "${DRY_ARGS[@]}"

BUILD_NV_OPEN="no"
if pacman -Qq linux-cachyos-nvidia-open >/dev/null 2>&1 || pacman -Qq linux-cachyos-lts-nvidia-open >/dev/null 2>&1; then
    INSTALLED_NV_VER="$(pacman -Q nvidia-utils 2>/dev/null | awk '{print $2}' | cut -d- -f1 || true)"
    if [ -n "$INSTALLED_NV_VER" ] && grep -q "^_nv_ver=${INSTALLED_NV_VER}$" PKGBUILD; then
        echo "  -> Detected matching nvidia-utils ($INSTALLED_NV_VER); enabling _build_nvidia_open"
        BUILD_NV_OPEN="yes"
    else
        echo "  -> PKGBUILD _nv_ver differs from host nvidia-utils (${INSTALLED_NV_VER:-none}); _build_nvidia_open=no"
    fi
else
    echo "  -> No linux-cachyos-nvidia-open package installed; _build_nvidia_open=no"
fi
PKG_ARGS+=(--set "_build_nvidia_open=$BUILD_NV_OPEN")
if ! pacman -Qq nvidia-580xx-utils >/dev/null 2>&1; then
    PKG_ARGS+=(--set "_build_nvidia_580xx=no")
fi
if [ -n "$PROCESSOR_OPT" ]; then
    PKG_ARGS+=(--processor-opt "$PROCESSOR_OPT")
fi
py interlace_pkgbuild.py PKGBUILD "${PATCH_FILES[@]}" "${PKG_ARGS[@]}" "${DRY_ARGS[@]}"

echo "==> [5/6] Compiling and installing patched kernel..."
run makepkg -Csfi --noconfirm --skipinteg

echo "==> [6/6] Syncing initramfs and bootloader..."
py interlace_apply_rules.py --gpu-profile "$RESOLVED_PROFILE" --sync-only "${DRY_ARGS[@]}"

echo "==> SUCCESS! Reboot to load your newly compiled interlaced kernel."
