"""
What the GUI's dropdowns mean, and the exact command-line arguments each button passes.

One place turns the user's selection into a *resolved* profile / adapter / port using the same
functions the scripts use (``resolve_gpu_profile``, ``pick_connector``, ``resolve_adapter``). The GUI
then passes those resolved values explicitly, so what the badges verify is precisely what the script
was asked to apply, with no second guess in the GUI or in the script.
"""

from __future__ import annotations

from dataclasses import dataclass

from interlace_gpu import pick_connector, resolve_adapter, resolve_gpu_profile
from interlace_sysinfo import SystemInfo


class SelectionError(ValueError):
    """The current selection cannot be applied (message is shown to the user as-is)."""


@dataclass(frozen=True)
class Selection:
    gpu_profile: str = "auto"
    adapter_mode: str = "auto"
    connector: str = "auto"
    kernel_version: str = "auto"
    custom_edid: str = ""
    rdna_patch: bool = True


@dataclass(frozen=True)
class Resolved:
    profile: str
    adapter: str
    connector: str  # '' when no port is detected and none was chosen


def resolve(sel: Selection, info: SystemInfo) -> Resolved:
    profile = resolve_gpu_profile(sel.gpu_profile, list(info.gpus), [p.name for p in info.ports])
    connector = sel.connector
    if connector == "auto":
        connector = pick_connector(sel.adapter_mode, profile, info.connectors) or ""
    return Resolved(profile, resolve_adapter(sel.adapter_mode, connector), connector)


def setup_args(sel: Selection, res: Resolved, *, live_only: bool = False) -> list[str]:
    """Arguments for ``setup-interlace-env.sh`` (``live_only`` = the small 'Reload EDID Live' action)."""
    if not res.connector:
        raise SelectionError("No video port detected. Pick a port in Configuration first.")
    args = ["--gpu-profile", res.profile, "--adapter-mode", res.adapter, "--connector", res.connector]
    if sel.custom_edid:
        args += ["--edid", sel.custom_edid]
    if live_only:
        args.append("--live-only")
    return args


def kernel_args(sel: Selection, res: Resolved, *, config_only: bool = False) -> list[str]:
    """Arguments for ``fix-interlaced-kernel.sh`` (``config_only`` = the small 'Apply GPU Rules' action)."""
    args = ["--gpu-profile", res.profile, "--adapter-mode", res.adapter]
    if config_only:
        return [*args, "--config-only"]
    args += ["--kernel-version", sel.kernel_version]
    if not sel.rdna_patch:
        args.append("--no-rdna-patch")
    return args
