"""
GPU-profile rules (udev / modprobe / environment.d) for the Linux CRT Interlacing Suite.

``render_gpu_rules`` is a pure description of the files a profile needs; ``apply_gpu_rules`` is the
only function that writes them, always through the ``Runner`` so ``--dry-run`` shows every step.
This replaces the two copies of the rules logic that lived in ``setup-interlace-env.sh`` and
``fix-interlaced-kernel.sh``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from interlace_gpu import AMD_VENDOR, NVIDIA_VENDOR, GpuDevice
from interlace_runner import Host, Runner, SystemPaths

MODPROBE_CRT_CONF = (
    "options radeon si_support=0 cik_support=0\n"
    "options amdgpu si_support=1 cik_support=1\n"
    "blacklist radeon\n"
)

_DRM_RULE = 'SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{{vendor}}=="0x{vendor}", ATTRS{{device}}=="0x{devid}", SYMLINK+="dri/{link}"\n'


@dataclass
class GpuRulesPlan:
    write: dict[Path, str] = field(default_factory=dict)
    remove: list[Path] = field(default_factory=list)
    reload_udev: bool = False


def _rule(vendor: str, devid: str, link: str) -> str:
    return _DRM_RULE.format(vendor=vendor, devid=devid, link=link)


def render_gpu_rules(
    profile: str, gpus: Sequence[GpuDevice], paths: SystemPaths, exists: Callable[[Path], bool],
    desktop_env: bool = True,
) -> GpuRulesPlan:
    """Describe the files for ``profile``. ``desktop_env`` controls the KWin/environment.d files."""
    plan = GpuRulesPlan()
    env = paths.user_env_dir
    nv_prime, amd_dual = env / "nvidia-prime.conf", env / "amd-dual-gpu.conf"
    nvidia = next((g for g in gpus if g.vendor == NVIDIA_VENDOR), None)
    amd = [g for g in gpus if g.vendor == AMD_VENDOR]
    amd_first, amd_last = (amd[0], amd[-1]) if amd else (None, None)

    if desktop_env:
        plan.write[env / "kwin-cursor.conf"] = "KWIN_FORCE_SW_CURSOR=1\n"

    def drop(path: Path) -> None:
        if exists(path):
            plan.remove.append(path)
            if path == paths.gpu_udev_rules:
                plan.reload_udev = True

    if profile == "dual-nvidia-amd":
        drop(amd_dual)
        if nvidia and amd_last:
            plan.write[paths.gpu_udev_rules] = (
                "# PCI-slot-independent Dual-GPU DRM symlinks (immune to M.2 NVMe PCIe bus renumbering)\n"
                + _rule("10de", nvidia.devid, "primary-nvidia")
                + _rule("1002", amd_last.devid, "secondary-amd")
            )
            plan.reload_udev = True
            if desktop_env:
                plan.write[nv_prime] = (
                    "KWIN_DRM_DEVICES=/dev/dri/primary-nvidia:/dev/dri/secondary-amd\n"
                    "__NV_PRIME_RENDER_OFFLOAD=1\n"
                    "__GLX_VENDOR_LIBRARY_NAME=nvidia\n"
                    "VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json\n"
                )
        plan.write[paths.gpu_modprobe_conf] = MODPROBE_CRT_CONF
    elif profile == "dual-amd-amd":
        drop(nv_prime)
        if amd_first and amd_last and amd_first.devid != amd_last.devid:
            plan.write[paths.gpu_udev_rules] = (
                "# PCI-slot-independent Dual-AMD DRM symlinks\n"
                + _rule("1002", amd_first.devid, "primary-amd")
                + _rule("1002", amd_last.devid, "secondary-amd")
            )
        elif amd_first and amd_last:
            plan.write[paths.gpu_udev_rules] = (
                "# Dual-AMD DRM symlinks by PCI slot\n"
                f'SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="{amd_first.pci}", SYMLINK+="dri/primary-amd"\n'
                f'SUBSYSTEM=="drm", KERNEL=="card[0-9]*", KERNELS=="{amd_last.pci}", SYMLINK+="dri/secondary-amd"\n'
            )
        plan.reload_udev = True
        if desktop_env:
            plan.write[amd_dual] = "KWIN_DRM_DEVICES=/dev/dri/primary-amd:/dev/dri/secondary-amd\n"
        plan.write[paths.gpu_modprobe_conf] = MODPROBE_CRT_CONF
    elif profile in ("rdna-single", "nvidia-single"):
        drop(nv_prime)
        drop(amd_dual)
        drop(paths.gpu_udev_rules)
        drop(paths.gpu_modprobe_conf)
    else:  # gcn-single and anything unknown
        drop(nv_prime)
        drop(amd_dual)
        drop(paths.gpu_udev_rules)
        plan.write[paths.gpu_modprobe_conf] = MODPROBE_CRT_CONF
    return plan


def _is_user_path(path: Path, paths: SystemPaths) -> bool:
    return path.is_relative_to(paths.home)


def _write_user(runner: Runner, path: Path, content: str) -> None:
    runner.write_text(path, content, privileged=False)


def apply_gpu_rules(host: Host, plan: GpuRulesPlan) -> None:
    runner = host.runner
    for path, content in plan.write.items():
        if _is_user_path(path, host.paths):
            _write_user(runner, path, content)
        else:
            runner.write_text(path, content)
    for path in plan.remove:
        runner.remove(path, privileged=not _is_user_path(path, host.paths))
    if plan.reload_udev:
        runner.run(["udevadm", "control", "--reload-rules"], privileged=True)
        runner.run(["udevadm", "trigger"], privileged=True)
