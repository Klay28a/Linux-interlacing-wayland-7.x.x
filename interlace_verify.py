"""
Is the machine in the state the CURRENT selection asks for?

Each check compares what is on disk with what the scripts would write for the *resolved* profile /
adapter / port, so changing a dropdown immediately flips a badge to "not applied" until the matching
script has run, and running it flips the badge back. Read-only and injectable (paths, GPUs, kernel
release), so the same code is tested against the three mock PC fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from interlace_cmdline import si_args_for
from interlace_edid import input_byte
from interlace_gpu import edid_file_name
from interlace_rules import render_gpu_rules
from interlace_runner import SystemPaths
from interlace_selection import Resolved, Selection
from interlace_state import parse_kernel_record
from interlace_sysinfo import SystemInfo


@dataclass(frozen=True)
class Check:
    ok: bool
    short: str  # badge text, a few words
    detail: str = ""  # tooltip text


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _boot_texts(paths: SystemPaths) -> list[str]:
    files = [paths.default_limine, paths.default_grub, paths.kernel_cmdline]
    for entry_dir in paths.loader_entry_dirs:
        if entry_dir.is_dir():
            files += sorted(entry_dir.glob("*.conf"))
    return [t for f in files if (t := _read(f))]


def _connector_record(paths: SystemPaths, conn: str) -> dict:
    text = _read(paths.state_file)
    if not text.strip():
        return {}
    try:
        record = json.loads(text).get("connectors", {}).get(conn, {})
    except (ValueError, AttributeError):
        return {}
    return record if isinstance(record, dict) else {}


def _custom_edid_installed(sel: Selection, dest: Path, record: dict) -> bool:
    if not sel.custom_edid:
        return True
    if record.get("source_edid") == sel.custom_edid:
        return True
    try:
        return dest.stat().st_mtime >= Path(sel.custom_edid).stat().st_mtime
    except OSError:
        return False


def check_edid(sel: Selection, res: Resolved, info: SystemInfo, paths: SystemPaths) -> Check:
    conn = res.connector
    if not conn:
        return Check(False, "No port", "No video port detected.")
    name = edid_file_name(conn)
    dest = paths.firmware_edid_dir / name
    rel_fw = f"edid/{name}"
    try:
        data = dest.read_bytes()
    except OSError:
        return Check(False, "Not installed", f"{dest} is missing.")

    want = input_byte(res.adapter, conn)
    if len(data) < 21 or data[20] != want:
        have = f"0x{data[20]:02X}" if len(data) >= 21 else "unreadable"
        return Check(False, "Wrong adapter", f"EDID input byte is {have}; {res.adapter} needs 0x{want:02X}.")

    record = _connector_record(paths, conn)
    if not _custom_edid_installed(sel, dest, record):
        return Check(False, "Custom EDID pending", f"{Path(sel.custom_edid).name} is not installed yet.")
    if record and (record.get("gpu_profile") != res.profile or record.get("adapter_mode") != res.adapter):
        last = f"{record.get('gpu_profile')} / {record.get('adapter_mode')}"
        return Check(False, "Other profile applied", f"Last applied: {last}.")

    wanted = f"{conn}:{rel_fw}"
    boot = _boot_texts(paths)
    in_boot = any(wanted in t and f"video={conn}:e" in t for t in boot)
    if not (info.live_map.get(conn) == rel_fw or wanted in info.cmdline or in_boot):
        return Check(False, "Not in boot config", f"{wanted} is not in the kernel command line.")
    if in_boot and si_args_for(res.profile) and not any("amdgpu.cik_support=1" in t for t in boot):
        return Check(False, "GPU flags missing", "amdgpu si/cik support is not in the boot config.")
    return Check(True, conn, f"{wanted} ({res.adapter})")


def check_rules(res: Resolved, info: SystemInfo, paths: SystemPaths) -> Check:
    """Files for ``res.profile`` hold exactly what the scripts write; files it must not have are gone."""
    plan = render_gpu_rules(res.profile, list(info.gpus), paths, lambda _p: True)
    wrong = [p.name for p, content in plan.write.items() if _read(p) != content]
    stale = [p.name for p in plan.remove if p.exists()]
    if wrong or stale:
        parts = [*(f"{n} differs" for n in wrong), *(f"{n} should not exist" for n in stale)]
        return Check(False, "Not applied", "; ".join(parts))
    return Check(True, res.profile)


def check_kernel(sel: Selection, info: SystemInfo, paths: SystemPaths) -> Check:
    record = parse_kernel_record(_read(paths.kernel_state_file))
    if record is None:
        return Check(False, "Not built", "No kernel built by this suite was found.")
    built = f"{record.get('pkgver', '')}-{record.get('pkgrel', '')}"
    series = str(record.get("series", ""))
    if not record.get("pkgver") or not info.kernel.startswith(built):
        return Check(False, "Reboot to load", f"Built {built} ({series}); running {info.kernel}.")
    if sel.kernel_version not in ("auto", series):
        return Check(False, f"Selected {sel.kernel_version}", f"The running build is {series}.")
    if bool(record.get("rdna")) != sel.rdna_patch:
        state = "with" if record.get("rdna") else "without"
        return Check(False, "RDNA unlock differs", f"The running build is {state} the RDNA unlock.")
    return Check(True, series, f"{info.kernel} ({series})")


def check_cru(info: SystemInfo) -> Check:
    return Check(info.cru_installed, "Installed" if info.cru_installed else "Not installed")


def check_bootloader(info: SystemInfo) -> Check:
    return Check(info.bootloader != "Unknown", info.bootloader, f"{info.bootloader} / {info.initramfs}")


@dataclass(frozen=True)
class Verification:
    edid: Check
    rules: Check
    kernel: Check
    cru: Check
    boot: Check

    @property
    def pending(self) -> list[str]:
        names = {"edid": "EDID", "rules": "GPU rules", "kernel": "Kernel", "cru": "Linux CRU"}
        return [label for key, label in names.items() if not getattr(self, key).ok]


def verify_all(sel: Selection, res: Resolved, info: SystemInfo, paths: SystemPaths) -> Verification:
    return Verification(
        edid=check_edid(sel, res, info, paths),
        rules=check_rules(res, info, paths),
        kernel=check_kernel(sel, info, paths),
        cru=check_cru(info),
        boot=check_bootloader(info),
    )
