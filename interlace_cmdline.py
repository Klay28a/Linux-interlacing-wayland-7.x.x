"""
Pure text editors for kernel command lines and initramfs configs (string in, string out).

The original bash passed a bootloader file through a pipe AND a heredoc into one ``python3 -``
call; the heredoc replaced stdin, so the Python saw an empty file and overwrote the real
bootloader config with a single line. Here the existing text is an explicit argument, so that
failure mode cannot occur.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

SI_CIK_ARGS = ("radeon.si_support=0", "amdgpu.si_support=1", "radeon.cik_support=0", "amdgpu.cik_support=1")
CMDLINE_STRIP_PREFIXES = (
    "radeon.si_support=", "amdgpu.si_support=", "radeon.cik_support=", "amdgpu.cik_support=",
    "drm.edid_firmware=",
)

INITRAMFS_TOOLS_HOOK = """#!/bin/sh
# Installed by linux-interlace-suite: embed custom CRT EDID files in the initramfs.
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in
    prereqs) prereqs; exit 0 ;;
esac
. /usr/share/initramfs-tools/hook-functions
for f in /usr/lib/firmware/edid/*.bin; do
    [ -e "$f" ] && copy_file firmware "$f" "/lib/firmware/edid/${f##*/}"
done
exit 0
"""


def si_args_for(profile: str) -> list[str]:
    return [] if profile in ("rdna-single", "nvidia-single") else list(SI_CIK_ARGS)


def _firmware_map(text: str) -> dict[str, str]:
    fw_map: dict[str, str] = {}
    for m in re.finditer(r"\bdrm\.edid_firmware=([^\s\"']+)", text):
        for item in m.group(1).split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                fw_map[k.strip()] = v.strip()
    return fw_map


def _strip_managed_args(text: str, conn: str) -> str:
    for prefix in CMDLINE_STRIP_PREFIXES:
        text = re.sub(r"\b" + re.escape(prefix) + r"[^\s\"']+", "", text)
    text = re.sub(r"\bvideo=" + re.escape(conn) + r":[^\s\"']+", "", text)
    return re.sub(r"  +", " ", text)


def _extra_args(profile: str, fw_map: Mapping[str, str], conn: str) -> str:
    fw_arg = "drm.edid_firmware=" + ",".join(f"{k}:{v}" for k, v in fw_map.items())
    return " ".join([*si_args_for(profile), fw_arg, f"video={conn}:e"])


def update_cmdline_text(text: str, key: str, conn: str, rel_fw: str, profile: str) -> str:
    """Add/merge the EDID override args on the ``key`` line(s) of a bootloader config file.

    ``key`` is ``KERNEL_CMDLINE`` (Limine), ``GRUB_CMDLINE_LINUX_DEFAULT`` (GRUB) or ``options``
    (systemd-boot entry). Every other line is preserved verbatim and EDID entries already present
    for other connectors are kept. If no ``key`` line exists, one is appended.
    """
    out: list[str] = []
    matched = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(key) and not stripped.startswith("#"):
            matched = True
            fw_map = _firmware_map(line)
            fw_map[conn] = rel_fw
            line = _strip_managed_args(line, conn)
            extra = _extra_args(profile, fw_map, conn)
            idx_dq, idx_sq, idx_eq = line.rfind('"'), line.rfind("'"), line.find("=")
            if idx_dq != -1 and idx_dq > idx_eq:
                line = f'{line[:idx_dq].rstrip()} {extra}"\n'
            elif idx_sq != -1 and idx_sq > idx_eq:
                line = f"{line[:idx_sq].rstrip()} {extra}'\n"
            else:
                line = f"{line.rstrip()} {extra}\n"
        out.append(line)

    if not matched:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        extra = _extra_args(profile, {conn: rel_fw}, conn)
        if key == "KERNEL_CMDLINE":
            out.append(f'KERNEL_CMDLINE[default]+="{extra}"\n')
        elif key == "options":
            out.append(f"options {extra}\n")
        else:
            out.append(f'{key}="{extra}"\n')
    return "".join(out)


def update_kernel_cmdline_text(text: str, conn: str, rel_fw: str, profile: str) -> str:
    """Same as ``update_cmdline_text`` for a bare ``/etc/kernel/cmdline`` (one line, no key)."""
    body = text.strip()
    fw_map = _firmware_map(body)
    fw_map[conn] = rel_fw
    body = _strip_managed_args(body, conn).strip()
    return f"{body} {_extra_args(profile, fw_map, conn)}".strip() + "\n"


def merge_edid_firmware_param(current: str, conn: str, rel_fw: str) -> str:
    """Merge ``conn:rel_fw`` into the ``/sys/module/drm/parameters/edid_firmware`` value."""
    fw_map: dict[str, str] = {}
    for item in current.strip().split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            fw_map[k.strip()] = v.strip()
    fw_map[conn] = rel_fw
    return ",".join(f"{k}:{v}" for k, v in fw_map.items())


def add_to_mkinitcpio_files(text: str, dest: str) -> str:
    """Add ``dest`` to the ``FILES=(...)`` array of mkinitcpio.conf (idempotent)."""
    if dest in text:
        return text
    new_text, count = re.subn(r"^FILES=\(", f"FILES=({dest} ", text, count=1, flags=re.MULTILINE)
    if count:
        return new_text
    return text + ("" if text.endswith("\n") or not text else "\n") + f"FILES=({dest})\n"


def dracut_conf_text(existing: str, dest: str) -> str:
    if dest in existing:
        return existing
    return existing + ("" if existing.endswith("\n") or not existing else "\n") + f'install_items+=" {dest} "\n'
