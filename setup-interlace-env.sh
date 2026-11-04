#!/usr/bin/env bash
# Script 1: Standalone CRT Interlace, RDNA DP/HDMI Adapter & Multi-GPU Environment Setup
# Works standalone, via CLI flags, or from the Linux Interlacing Suite GUI alongside linux-cru.
# Supports:
#   - GPU Profiles : auto, rdna-single, gcn-single, nvidia-single, dual-nvidia-amd, dual-amd-amd
#   - Adapter Modes: auto, dp-dac (DisplayPort DAC adapter as DP-*), hdmi-dac (HDMI DAC adapter as HDMI-A-*), analog-native (VGA/DVI-I)
#   - Bootloaders  : Limine, GRUB, systemd-boot | Initramfs: mkinitcpio, dracut, initramfs-tools
# Usage:
#   ./setup-interlace-env.sh [options] [edid_source_path] [connector_name|auto]
#   Options:
#     --gpu-profile <auto|rdna-single|gcn-single|nvidia-single|dual-nvidia-amd|dual-amd-amd>
#     --adapter-mode <auto|dp-dac|hdmi-dac|analog-native>
#     --edid <path>
#     --connector <name|auto>
#     --live-only
set -euo pipefail
umask 022

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Please run this script as your normal user (it will prompt via sudo when needed)." >&2
    exit 1
fi

GPU_PROFILE="auto"
ADAPTER_MODE="auto"
USER_EDID_SRC=""
USER_CONN=""
LIVE_ONLY=0
POSITIONAL=()

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
        --edid)
            USER_EDID_SRC="${2:-}"
            shift 2
            ;;
        --edid=*)
            USER_EDID_SRC="${1#*=}"
            shift
            ;;
        --connector)
            USER_CONN="${2:-auto}"
            shift 2
            ;;
        --connector=*)
            USER_CONN="${1#*=}"
            shift
            ;;
        --live-only)
            LIVE_ONLY=1
            shift
            ;;
        -h|--help)
            cat << 'HELP_EOF'
Usage: ./setup-interlace-env.sh [OPTIONS] [edid_source_path] [connector_name|auto]

Options:
  --gpu-profile <PROFILE>   GPU architecture & setup mode:
                              auto            Auto-detect from PCI hardware (default)
                              rdna-single     Single GPU: AMD RDNA 1/2/3/4
                              gcn-single      Single GPU: AMD GCN 1-5 / Polaris / Vega
                              nvidia-single   Single GPU: NVIDIA (Proprietary / Open Kernel Module)
                              dual-nvidia-amd Dual GPU: NVIDIA Primary + AMD Secondary
                              dual-amd-amd    Dual GPU: AMD Primary + AMD Secondary
  --adapter-mode <MODE>     Video output / DAC adapter preset:
                              auto            Auto-detect from connector & GPU architecture (default)
                              dp-dac          DisplayPort DAC Adapter (DP-*)
                              hdmi-dac        HDMI DAC Adapter (HDMI-A-* / DP-*)
                              analog-native   Native Analog DAC port (VGA-* / DVI-I-*)
  --edid <PATH>             Custom EDID .bin file to load/convert
  --connector <CONN|auto>   Target DRM connector (e.g. DP-1, HDMI-A-1, VGA-1, DVI-I-1, or auto)
  --live-only               Reload EDID into running kernel DRM without rebuilding initramfs/bootloader
HELP_EOF
            exit 0
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [ -z "$USER_EDID_SRC" ] && [ "${#POSITIONAL[@]}" -ge 1 ]; then
    USER_EDID_SRC="${POSITIONAL[0]}"
fi
if [ -z "$USER_CONN" ] && [ "${#POSITIONAL[@]}" -ge 2 ]; then
    USER_CONN="${POSITIONAL[1]}"
fi
USER_CONN="${USER_CONN:-auto}"

TMP_EDID="$(mktemp)"
TMP_CFG="$(mktemp)"
trap 'rm -f "$TMP_EDID" "$TMP_CFG"' EXIT

# ------------------------------------------------------------------------------
# 1. Detect PCI GPUs & Resolve GPU Architecture Profile
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
AMD_LAST_DEVID="$(sed -n 's/.*\[1002:\([0-9a-fA-F]\{4\}\)\].*/\1/p' <<<"$AMD_LAST_LINE" | tr '[:upper:]' '[:lower:]')"

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
    if [ -n "$NV_DEVID" ] && [ -n "$AMD_LAST_DEVID" ]; then
        RESOLVED_PROFILE="dual-nvidia-amd"
    elif [ "$AMD_COUNT" -ge 2 ]; then
        RESOLVED_PROFILE="dual-amd-amd"
    elif [ -n "$NV_DEVID" ] && [ -z "$AMD_LAST_DEVID" ]; then
        RESOLVED_PROFILE="nvidia-single"
    elif is_rdna_gpu "$AMD_LAST_LINE" "$AMD_LAST_DEVID" || [ "$HAS_ANALOG_DRM" -eq 0 ]; then
        RESOLVED_PROFILE="rdna-single"
    else
        RESOLVED_PROFILE="gcn-single"
    fi
else
    RESOLVED_PROFILE="$GPU_PROFILE"
fi


# ------------------------------------------------------------------------------
# 2. Resolve Target DRM Connector & Adapter Signal Type
# ------------------------------------------------------------------------------
detect_connector_by_patterns() {
    local want_status="$1"
    shift
    local pat
    for pat in "$@"; do
        for status_file in /sys/class/drm/card*-*/status; do
            [ -e "$status_file" ] || continue
            local short_name
            short_name="$(basename "$(dirname "$status_file")")"
            short_name="${short_name#card*-}"
            # shellcheck disable=SC2053
            if [[ "$short_name" == $pat ]]; then
                local st_val
                st_val="$(cat "$status_file" 2>/dev/null || true)"
                if [ "$want_status" = "any" ] || [ "$st_val" = "$want_status" ]; then
                    echo "$short_name"
                    return 0
                fi
            fi
        done
    done
    return 1
}

if [ "$USER_CONN" = "auto" ]; then
    DETECTED_CONN=""
    case "$ADAPTER_MODE" in
        dp-dac)
            DETECTED_CONN="$(detect_connector_by_patterns "connected" "DP-*" "HDMI-A-*" || detect_connector_by_patterns "any" "DP-*" "HDMI-A-*" || true)"
            CONNECTOR="${DETECTED_CONN:-DP-1}"
            ;;
        hdmi-dac)
            DETECTED_CONN="$(detect_connector_by_patterns "connected" "HDMI-A-*" "DP-*" || detect_connector_by_patterns "any" "HDMI-A-*" "DP-*" || true)"
            CONNECTOR="${DETECTED_CONN:-HDMI-A-1}"
            ;;
        analog-native)
            DETECTED_CONN="$(detect_connector_by_patterns "connected" "VGA-*" "DVI-I-*" || detect_connector_by_patterns "any" "VGA-*" "DVI-I-*" || true)"
            CONNECTOR="${DETECTED_CONN:-VGA-1}"
            ;;
        *)
            if [ "$RESOLVED_PROFILE" = "rdna-single" ] || [ "$RESOLVED_PROFILE" = "nvidia-single" ]; then
                DETECTED_CONN="$(detect_connector_by_patterns "connected" "DP-*" "HDMI-A-*" "VGA-*" "DVI-I-*" || detect_connector_by_patterns "any" "DP-*" "HDMI-A-*" || true)"
                CONNECTOR="${DETECTED_CONN:-DP-1}"
            else
                DETECTED_CONN="$(detect_connector_by_patterns "connected" "VGA-*" "DVI-I-*" "DP-*" "HDMI-A-*" || detect_connector_by_patterns "any" "VGA-*" "DVI-I-*" "DP-*" "HDMI-A-*" || true)"
                CONNECTOR="${DETECTED_CONN:-VGA-1}"
            fi
            ;;
    esac
else
    CONNECTOR="$USER_CONN"
fi

if [ "$ADAPTER_MODE" = "auto" ]; then
    if [[ "$CONNECTOR" == DP-* ]]; then
        RESOLVED_ADAPTER="dp-dac"
    elif [[ "$CONNECTOR" == HDMI-* || "$CONNECTOR" == DVI-D-* ]]; then
        RESOLVED_ADAPTER="hdmi-dac"
    else
        RESOLVED_ADAPTER="analog-native"
    fi
else
    RESOLVED_ADAPTER="$ADAPTER_MODE"
fi

if [ "$CONNECTOR" = "VGA-1" ]; then
    EDID_NAME="crufile.bin"
else
    CONN_LOWER="$(echo "$CONNECTOR" | tr '[:upper:]' '[:lower:]')"
    EDID_NAME="cru-${CONN_LOWER}.bin"
fi
EDID_DEST="/usr/lib/firmware/edid/${EDID_NAME}"
EDID_SRC="${USER_EDID_SRC:-$EDID_DEST}"

echo "==> [1/5] Configuration Summary:"
echo "  -> GPU Profile   : $RESOLVED_PROFILE (requested: $GPU_PROFILE)"
echo "  -> Adapter Preset: $RESOLVED_ADAPTER (requested: $ADAPTER_MODE)"
echo "  -> DRM Connector : $CONNECTOR (Firmware target: $EDID_DEST)"

# ------------------------------------------------------------------------------
# 3. Create or Validate Linux-Formatted EDID Binary (Analog vs DP/HDMI Adapter)
# ------------------------------------------------------------------------------
echo "==> [2/5] Preparing Linux-formatted EDID at $EDID_DEST..."
python3 - "$EDID_SRC" "$TMP_EDID" "$RESOLVED_ADAPTER" "$RESOLVED_PROFILE" "$CONNECTOR" << 'PYEOF'
import sys, os

src, dst, adapter_mode, gpu_profile, conn_name = sys.argv[1:6]
is_digital_adapter = (
    adapter_mode in ("dp-dac", "hdmi-dac")
    or conn_name.startswith(("DP-", "HDMI-", "DVI-D-", "eDP-"))
)
is_rdna_or_dcn = (
    gpu_profile == "rdna-single"
    or is_digital_adapter
)

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

if is_digital_adapter:
    b[18] = 1
    b[19] = 4
    # EDID 1.4 Digital Input: bit 7=1 (Digital), bits 6:4=010 (8bpc), bits 3:0=0101 (DisplayPort) or 0010 (HDMI-A)
    b[20] = 0xA5 if (adapter_mode == "dp-dac" or conn_name.startswith("DP-")) else 0xA2
    # Digital features: Continuous frequency + Preferred timing mode + sRGB/RGB444
    b[24] = (b[24] & 0xE7) | 0x02 | 0x01
    print(f"  -> Configured EDID header for Digital DAC Adapter ({adapter_mode} on {conn_name}: EDID 1.4, 8bpc RGB444, input=0x{b[20]:02X}).")
else:
    if b[19] < 4:
        b[18], b[19] = 1, 3
    b[20] = 0x0E
    print(f"  -> Configured EDID header for Native Analog DAC ({conn_name}: input=0x0E).")

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
        changed = False
        if hact > 0 and vact <= int(hact * 0.45):
            vact, vblk = vact * 2, vblk * 2
            voff, vsyn = min(63, voff * 2), min(63, vsyn * 2)
            changed = True
            print(f"  -> Converted Windows half-field DTD @{off} to Linux full-frame height: vactive={vact}")
        if is_rdna_or_dcn:
            # DCN OTG & DP/HDMI stream encoders divide vertical field timings by 2 and require even parameters
            new_vact = (vact + 1) & ~1
            new_voff = max(2, (voff + 1) & ~1)
            new_vsyn = max(2, (vsyn + 1) & ~1)
            new_vblk = max(new_voff + new_vsyn + 2, (vblk + 1) & ~1)
            if (new_vact, new_vblk, new_voff, new_vsyn) != (vact, vblk, voff, vsyn):
                vact, vblk = new_vact, new_vblk
                voff, vsyn = min(62, new_voff), min(62, new_vsyn)
                changed = True
                print(f"  -> Aligned interlaced DTD @{off} to even vertical field lines for RDNA/DCN: vact={vact}, vblk={vblk}, vfp={voff}, vsync={vsyn}")
        if changed:
            b[off+5] = vact & 0xFF
            b[off+6] = vblk & 0xFF
            b[off+7] = (((vact >> 8) & 0x0F) << 4) | ((vblk >> 8) & 0x0F)
            b[off+10] = ((voff & 0x0F) << 4) | (vsyn & 0x0F)
            b[off+11] = (b[off+11] & 0xF0) | (((voff >> 4) & 0x03) << 2) | ((vsyn >> 4) & 0x03)

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

# ------------------------------------------------------------------------------
# 4. Configure GPU Architecture & Single/Dual-GPU Environment Rules
# ------------------------------------------------------------------------------
echo "==> [3/5] Applying GPU architecture & multi-GPU rules for profile: $RESOLVED_PROFILE..."
mkdir -p "$HOME/.config/environment.d"
echo "KWIN_FORCE_SW_CURSOR=1" > "$HOME/.config/environment.d/kwin-cursor.conf"

case "$RESOLVED_PROFILE" in
    dual-nvidia-amd)
        echo "  -> Configuring Dual-GPU NVIDIA (${NV_DEVID:-auto}) + AMD (${AMD_LAST_DEVID:-auto}) udev & PRIME rules..."
        rm -f "$HOME/.config/environment.d/amd-dual-gpu.conf"
        if [ -n "$NV_DEVID" ] && [ -n "$AMD_LAST_DEVID" ]; then
            sudo mkdir -p /etc/udev/rules.d
            cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
# PCI-slot-independent Dual-GPU DRM symlinks (immune to M.2 NVMe PCIe bus renumbering)
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x10de", ATTRS{device}=="0x$NV_DEVID", SYMLINK+="dri/primary-nvidia"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_LAST_DEVID", SYMLINK+="dri/secondary-amd"
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
        echo "  -> Configuring Dual-GPU AMD Primary (${AMD_FIRST_DEVID:-auto}) + AMD Secondary (${AMD_LAST_DEVID:-auto})..."
        rm -f "$HOME/.config/environment.d/nvidia-prime.conf"
        sudo mkdir -p /etc/udev/rules.d
        if [ -n "$AMD_FIRST_DEVID" ] && [ -n "$AMD_LAST_DEVID" ] && [ "$AMD_FIRST_DEVID" != "$AMD_LAST_DEVID" ]; then
            cat << UDEV_EOF | sudo tee /etc/udev/rules.d/99-kwin-gpu.rules >/dev/null
# PCI-slot-independent Dual-AMD DRM symlinks
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_FIRST_DEVID", SYMLINK+="dri/primary-amd"
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x1002", ATTRS{device}=="0x$AMD_LAST_DEVID", SYMLINK+="dri/secondary-amd"
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

if [ "$LIVE_ONLY" -eq 0 ]; then
    # 5. Embed EDID in Initramfs (preserving any other EDID files configured by linux-cru)
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

    # 6. Update Bootloader (Limine & GRUB) and Rebuild Initramfs
    echo "==> [5/5] Updating bootloader kernel parameters (preserving multi-port EDIDs) and rebuilding initramfs..."

    update_cmdline_file() {
        local file="$1"
        local key="$2"
        [ -f "${file}.orig.bak" ] || sudo cp -a "$file" "${file}.orig.bak"
        python3 - "$file" "$key" "$CONNECTOR" "edid/${EDID_NAME}" "$RESOLVED_PROFILE" > "$TMP_CFG" << 'PY_BOOT'
import sys, re

path, key, conn, rel_fw, gpu_profile = sys.argv[1:6]
lines = open(path, "r").readlines()
out = []
if gpu_profile in ("rdna-single", "nvidia-single"):
    si_args = []
else:
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
            extra_parts = si_args + [fw_arg, vid_arg]
            line = f'{line[:idx].rstrip()} {" ".join(extra_parts)}"\n'
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
else
    echo "==> [4/5] --live-only specified: skipping initramfs & bootloader rebuild."
fi

# 7. Live Reload EDID in Running Kernel DRM (Supports Analog VGA/DVI-I and RDNA DP/HDMI Adapters)
if [ -e /sys/module/drm/parameters/edid_firmware ]; then
    echo "==> Reloading EDID override live on $CONNECTOR..."
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
            sudo bash -c "echo off > '$st' && sleep 0.15 && echo detect > '$st'" || true
            if [ "$(cat "$st" 2>/dev/null || true)" != "connected" ] || [[ "$CONNECTOR" == VGA-* || "$CONNECTOR" == DVI-I-* ]]; then
                sudo bash -c "echo on > '$st'" || true
            fi
        fi
    done
    sudo udevadm trigger --action=change --subsystem-match=drm || true
fi

echo "==> Environment setup complete! (Profile: $RESOLVED_PROFILE | Adapter: $RESOLVED_ADAPTER | Connector: $CONNECTOR)"
