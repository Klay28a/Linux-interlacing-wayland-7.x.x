"""
EDID patching for the Linux CRT Interlacing Suite (pure: bytes in, bytes + log lines out).

Ported unchanged in behaviour from the heredoc in ``setup-interlace-env.sh`` so it can be unit
tested: Windows half-field interlaced DTDs become Linux full-frame height, DCN/RDNA timings are
aligned to even field lines, and checksums are recomputed.
"""

from __future__ import annotations

EDID_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
DTD_OFFSETS = (54, 72, 90, 108)


def default_crt_edid() -> bytearray:
    b = bytearray(128)
    b[0:8] = EDID_HEADER
    b[8:12] = b"\x22\xf0\xd0\x09"
    b[18], b[19], b[20], b[21], b[22], b[23], b[24] = 1, 3, 0x0E, 41, 31, 120, 0xEA
    b[38:40] = bytes([(1600 // 8) - 31, 0x40 | (85 - 60)])
    b[40:54] = b"\x01\x01" * 7
    b[54:72] = bytes([
        0x5C, 0x92, 0x00, 0xD0, 0x82, 0x00, 0x9C, 0x60,
        0x88, 0xE0, 0x68, 0x00, 0x96, 0x31, 0x11, 0x00, 0x00, 0x9C,
    ])
    for empty_off in (72, 90):
        b[empty_off:empty_off + 18] = bytes([0, 0, 0, 0x10, 0] + [0] * 13)
    b[108:126] = bytes([
        0x00, 0x00, 0x00, 0xFD, 0x00,
        30, 200, 30, 200, 70, 0x00,
        0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20,
    ])
    return b


def _fix_interlaced_dtd(b: bytearray, off: int, rdna_or_dcn: bool, log: list[str]) -> None:
    hact = b[off + 2] | ((b[off + 4] & 0xF0) << 4)
    vact = b[off + 5] | ((b[off + 7] & 0xF0) << 4)
    vblk = b[off + 6] | ((b[off + 7] & 0x0F) << 8)
    voff = ((b[off + 10] >> 4) & 0x0F) | ((b[off + 11] & 0x0C) << 2)
    vsyn = (b[off + 10] & 0x0F) | ((b[off + 11] & 0x03) << 4)
    changed = False
    if hact > 0 and vact <= int(hact * 0.45):
        vact, vblk = vact * 2, vblk * 2
        voff, vsyn = min(63, voff * 2), min(63, vsyn * 2)
        changed = True
        log.append(f"  -> Converted Windows half-field DTD @{off} to Linux full-frame height: vactive={vact}")
    if rdna_or_dcn:
        # DCN OTG & DP/HDMI stream encoders divide vertical field timings by 2 and require even parameters
        new_vact = (vact + 1) & ~1
        new_voff = max(2, (voff + 1) & ~1)
        new_vsyn = max(2, (vsyn + 1) & ~1)
        new_vblk = max(new_voff + new_vsyn + 2, (vblk + 1) & ~1)
        if (new_vact, new_vblk, new_voff, new_vsyn) != (vact, vblk, voff, vsyn):
            vact, vblk = new_vact, new_vblk
            voff, vsyn = min(62, new_voff), min(62, new_vsyn)
            changed = True
            log.append(
                f"  -> Aligned interlaced DTD @{off} to even vertical field lines for RDNA/DCN: "
                f"vact={vact}, vblk={vblk}, vfp={voff}, vsync={vsyn}"
            )
    if changed:
        b[off + 5] = vact & 0xFF
        b[off + 6] = vblk & 0xFF
        b[off + 7] = (((vact >> 8) & 0x0F) << 4) | ((vblk >> 8) & 0x0F)
        b[off + 10] = ((voff & 0x0F) << 4) | (vsyn & 0x0F)
        b[off + 11] = (b[off + 11] & 0xF0) | (((voff >> 4) & 0x03) << 2) | ((vsyn >> 4) & 0x03)


DIGITAL_PREFIXES = ("DP-", "HDMI-", "DVI-D-", "eDP-")


def is_digital_output(adapter_mode: str, conn_name: str) -> bool:
    return adapter_mode in ("dp-dac", "hdmi-dac") or conn_name.startswith(DIGITAL_PREFIXES)


def input_byte(adapter_mode: str, conn_name: str) -> int:
    """EDID byte 20 (video input definition) a given adapter/connector needs: DP 0xA5, HDMI 0xA2, analog 0x0E."""
    if not is_digital_output(adapter_mode, conn_name):
        return 0x0E
    return 0xA5 if (adapter_mode == "dp-dac" or conn_name.startswith("DP-")) else 0xA2


def adapter_from_edid(data: bytes) -> str:
    """The adapter mode an EDID is written for, read from its video input byte (20): the inverse of ``input_byte``."""
    if len(data) < 21 or not data[20] & 0x80:
        return "analog-native"
    return "dp-dac" if data[20] & 0x0F == 5 else "hdmi-dac"


def patch_edid(
    src: bytes | None, adapter_mode: str, gpu_profile: str, conn_name: str, src_label: str = "<edid>",
) -> tuple[bytes, list[str]]:
    """Return ``(edid_bytes, log_lines)`` formatted for Linux.

    ``src`` is an existing EDID (>= 128 bytes) or None / too short to synthesise a default CRT EDID.
    Raises ``ValueError`` on an invalid EDID header.
    """
    log: list[str] = []
    is_digital = is_digital_output(adapter_mode, conn_name)
    rdna_or_dcn = gpu_profile == "rdna-single" or is_digital

    if src is not None and len(src) >= 128:
        b = bytearray(src)
        if bytes(b[0:8]) != EDID_HEADER:
            raise ValueError(f"Invalid EDID header in {src_label}")
        log.append(f"  -> Loaded existing EDID from {src_label} ({len(b)} bytes).")
    else:
        b = default_crt_edid()
        log.append("  -> Generated default CRT EDID (2048x1536i @ 160Hz + 1600x1200p @ 85Hz).")

    if is_digital:
        b[18] = 1
        b[19] = 4
        # EDID 1.4 digital input: 8bpc, DisplayPort (0xA5) or HDMI-A (0xA2)
        b[20] = input_byte(adapter_mode, conn_name)
        b[24] = (b[24] & 0xE7) | 0x02 | 0x01
        log.append(
            f"  -> Configured EDID header for Digital DAC Adapter ({adapter_mode} on {conn_name}: "
            f"EDID 1.4, 8bpc RGB444, input=0x{b[20]:02X})."
        )
    else:
        if b[19] < 4:
            b[18], b[19] = 1, 3
        b[20] = 0x0E
        log.append(f"  -> Configured EDID header for Native Analog DAC ({conn_name}: input=0x0E).")

    for off in DTD_OFFSETS:
        if bytes(b[off:off + 4]) == b"\x00\x00\x00\xfd":
            b[off + 8] = max(b[off + 8], 200)
            b[off + 9] = max(b[off + 9], 70)
            continue
        if b[off] == 0 and b[off + 1] == 0:
            continue
        if b[off + 17] & 0x80:
            _fix_interlaced_dtd(b, off, rdna_or_dcn, log)

    if len(b) >= 256:
        b[126] = 1
        b[127] = (256 - (sum(b[:127]) % 256)) % 256
        b[255] = (256 - (sum(b[128:255]) % 256)) % 256
    else:
        b[126] = 0
        b[127] = (256 - (sum(b[:127]) % 256)) % 256
    return bytes(b), log
