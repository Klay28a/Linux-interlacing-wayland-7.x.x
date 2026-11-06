"""
GPU / DRM-connector discovery for the Linux CRT Interlacing Suite.

Pure functions: ``parse_lspci`` takes ``lspci -D -nn`` TEXT and ``list_connectors`` takes a
directory path, so tests feed mock text / a temp directory instead of real hardware.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

GPU_PROFILES = ("auto", "rdna-single", "gcn-single", "nvidia-single", "dual-nvidia-amd", "dual-amd-amd")
ADAPTER_MODES = ("auto", "dp-dac", "hdmi-dac", "analog-native")

NVIDIA_VENDOR = "10de"
AMD_VENDOR = "1002"

_PCI_ID_RE = re.compile(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]")
_GPU_CLASS_RE = re.compile(r"VGA|3D|Display")
_RDNA_NAME_RE = re.compile(r"Navi|RDNA|Radeon RX [56789]\d{3}", re.IGNORECASE)
_RDNA_DEVID_RE = re.compile(r"^(73[1-9a-f][0-9a-f]|74[0-9a-f]{2}|75[0-9a-f]{2}|15bf|15c8|163f|164d|1681|1900)$")


@dataclass(frozen=True)
class GpuDevice:
    pci: str
    vendor: str
    devid: str
    line: str


@dataclass(frozen=True)
class Connector:
    name: str
    status: str


def parse_lspci(text: str) -> list[GpuDevice]:
    """Parse ``lspci -D -nn`` output into display-class GPU devices (in lspci order)."""
    gpus: list[GpuDevice] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not _GPU_CLASS_RE.search(line):
            continue
        ids = _PCI_ID_RE.findall(line)
        if not ids:
            continue
        vendor, devid = ids[-1]
        gpus.append(GpuDevice(line.split()[0], vendor.lower(), devid.lower(), line))
    return gpus


def is_rdna_gpu(gpu: GpuDevice | None) -> bool:
    if gpu is None:
        return False
    return bool(_RDNA_NAME_RE.search(gpu.line) or _RDNA_DEVID_RE.match(gpu.devid))


def has_analog_connector(connector_names: Sequence[str]) -> bool:
    return any(n.startswith(("VGA-", "DVI-I-")) for n in connector_names)


def resolve_gpu_profile(requested: str, gpus: Sequence[GpuDevice], connector_names: Sequence[str]) -> str:
    """Return the concrete GPU profile. A non-``auto`` request is returned untouched."""
    if requested != "auto":
        return requested
    nvidia = [g for g in gpus if g.vendor == NVIDIA_VENDOR]
    amd = [g for g in gpus if g.vendor == AMD_VENDOR]
    last_amd = amd[-1] if amd else None
    if nvidia and last_amd:
        return "dual-nvidia-amd"
    if len(amd) >= 2:
        return "dual-amd-amd"
    if nvidia:
        return "nvidia-single"
    if is_rdna_gpu(last_amd) or not has_analog_connector(connector_names):
        return "rdna-single"
    return "gcn-single"


def list_connectors(drm_class: Path) -> list[Connector]:
    """Connectors under ``<drm_class>/card*-*``; the ``cardN-`` prefix is stripped from the name."""
    found: list[Connector] = []
    if not drm_class.is_dir():
        return found
    for entry in sorted(drm_class.glob("card*-*")):
        status_file = entry / "status"
        if not status_file.exists():
            continue
        try:
            status = status_file.read_text(encoding="utf-8").strip()
        except OSError:
            status = ""
        found.append(Connector(re.sub(r"^card\d+-", "", entry.name), status))
    return found


def find_connector(connectors: Sequence[Connector], want_status: str, patterns: Sequence[str]) -> str | None:
    for pat in patterns:
        for conn in connectors:
            if fnmatch.fnmatchcase(conn.name, pat) and want_status in ("any", conn.status):
                return conn.name
    return None


def connector_patterns(adapter_mode: str, profile: str) -> tuple[str, ...]:
    if adapter_mode == "dp-dac":
        return ("DP-*", "HDMI-A-*")
    if adapter_mode == "hdmi-dac":
        return ("HDMI-A-*", "DP-*")
    if adapter_mode == "analog-native":
        return ("VGA-*", "DVI-I-*")
    if profile in ("rdna-single", "nvidia-single"):
        return ("DP-*", "HDMI-A-*", "VGA-*", "DVI-I-*")
    return ("VGA-*", "DVI-I-*", "DP-*", "HDMI-A-*")


def pick_connector(adapter_mode: str, profile: str, connectors: Sequence[Connector]) -> str | None:
    """A connected matching connector, else any matching one, else None.

    There is deliberately NO hardcoded ``DP-1``/``VGA-1`` fallback: guessing a connector name and
    writing it into a bootloader config is unsafe, so the caller must report an error instead.
    """
    patterns = connector_patterns(adapter_mode, profile)
    return find_connector(connectors, "connected", patterns) or find_connector(connectors, "any", patterns)


def resolve_adapter(adapter_mode: str, connector: str) -> str:
    if adapter_mode != "auto":
        return adapter_mode
    if connector.startswith("DP-"):
        return "dp-dac"
    if connector.startswith(("HDMI-", "DVI-D-")):
        return "hdmi-dac"
    return "analog-native"


def edid_file_name(connector: str) -> str:
    return "crufile.bin" if connector == "VGA-1" else f"cru-{connector.lower()}.bin"
