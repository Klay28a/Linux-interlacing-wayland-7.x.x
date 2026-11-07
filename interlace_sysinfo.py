"""
Read-only snapshot of the machine for the GUI: GPUs, DRM ports, bootloader, initramfs, live EDID map.

Pure and injectable like the rest of the suite: ``lspci`` text, the paths, ``which`` and the kernel
release are arguments, so the three mock PC fixtures (and any tmp directory) exercise exactly the code
the GUI runs. Nothing here writes anything or runs a subprocess.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from interlace_boot import initramfs_command
from interlace_gpu import (
    AMD_VENDOR,
    NVIDIA_VENDOR,
    Connector,
    GpuDevice,
    is_rdna_gpu,
    parse_lspci,
    resolve_gpu_profile,
)
from interlace_runner import SystemPaths

_INITRAMFS_NAMES = {
    "limine-mkinitcpio": "limine-mkinitcpio", "mkinitcpio": "mkinitcpio",
    "dracut": "dracut", "update-initramfs": "initramfs-tools",
}
_CARD_RE = re.compile(r"^(card\d+)-(.+)$")


@dataclass(frozen=True)
class GpuRow:
    slot: str
    vendor_dev: str
    model: str
    arch: str


@dataclass(frozen=True)
class Port:
    card: str
    name: str
    status: str
    override: str  # the firmware file the running kernel currently uses for this port ('' = none)


@dataclass(frozen=True)
class SystemInfo:
    gpus: tuple[GpuDevice, ...]
    rows: tuple[GpuRow, ...]
    ports: tuple[Port, ...]
    kernel: str
    bootloader: str
    initramfs: str
    cmdline: str
    live_map: dict[str, str]
    cru_installed: bool
    recommended_profile: str

    @property
    def connectors(self) -> list[Connector]:
        return [Connector(p.name, p.status) for p in self.ports]


def gpu_row(gpu: GpuDevice) -> GpuRow:
    desc = re.sub(r"^[0-9a-fA-F:.]+\s+[^:]+:\s*", "", gpu.line)
    desc = re.sub(r"\s*\([^)]*rev[^)]*\)\s*$", "", desc)
    desc = re.sub(r"\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", desc).strip()
    if gpu.vendor == NVIDIA_VENDOR:
        arch = "NVIDIA"
    elif gpu.vendor == AMD_VENDOR:
        arch = "AMD RDNA" if is_rdna_gpu(gpu) else "AMD GCN"
    else:
        arch = "Other"
    return GpuRow(gpu.pci, f"{gpu.vendor}:{gpu.devid}", desc, arch)


def parse_live_map(text: str) -> dict[str, str]:
    """``drm.edid_firmware`` value (``DP-1:edid/a.bin,VGA-1:edid/b.bin``) as a port -> file dict."""
    found: dict[str, str] = {}
    for item in text.strip().split(","):
        if ":" in item:
            port, _, fw = item.partition(":")
            found[port.strip()] = fw.strip()
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def scan_ports(paths: SystemPaths, live_map: dict[str, str]) -> list[Port]:
    ports: list[Port] = []
    if not paths.drm_class.is_dir():
        return ports
    for entry in sorted(paths.drm_class.glob("card*-*")):
        match = _CARD_RE.match(entry.name)
        status_file = entry / "status"
        if match is None or match[2].startswith("Writeback") or not status_file.exists():
            continue
        status = _read(status_file).strip() or "unknown"
        ports.append(Port(match[1], match[2], status, live_map.get(match[2], "")))
    return ports


def detect_bootloader(paths: SystemPaths, which: Callable[[str], str | None]) -> str:
    """Limine, GRUB or systemd-boot judged by config files, never by ``bootctl`` alone (systemd ships it everywhere)."""
    if paths.default_limine.exists() or which("limine-mkinitcpio") or which("limine"):
        return "Limine"
    if paths.default_grub.exists():
        return "GRUB"
    if paths.kernel_cmdline.exists() or any(d.is_dir() for d in paths.loader_entry_dirs):
        return "systemd-boot"
    return "Unknown"


def detect_initramfs(which: Callable[[str], str | None]) -> str:
    cmd = initramfs_command(which)
    return _INITRAMFS_NAMES.get(cmd[0], cmd[0]) if cmd else "Unknown"


def cru_installed(paths: SystemPaths, which: Callable[[str], str | None]) -> bool:
    candidates = [paths.home / ".local" / "bin" / "linux-cru", *(d / "linux-cru" for d in paths.system_bin_dirs)]
    return bool(which("linux-cru")) or any(c.exists() for c in candidates)


def collect_system_info(
    paths: SystemPaths, lspci_text: str, which: Callable[[str], str | None], release: str,
) -> SystemInfo:
    gpus = parse_lspci(lspci_text)
    live_map = parse_live_map(_read(paths.edid_firmware_param))
    ports = scan_ports(paths, live_map)
    return SystemInfo(
        gpus=tuple(gpus),
        rows=tuple(gpu_row(g) for g in gpus),
        ports=tuple(ports),
        kernel=release,
        bootloader=detect_bootloader(paths, which),
        initramfs=detect_initramfs(which),
        cmdline=_read(paths.proc_cmdline).strip(),
        live_map=live_map,
        cru_installed=cru_installed(paths, which),
        recommended_profile=resolve_gpu_profile("auto", gpus, [p.name for p in ports]),
    )
