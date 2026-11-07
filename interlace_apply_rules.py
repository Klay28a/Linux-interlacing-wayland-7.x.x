#!/usr/bin/env python3
"""
Apply (or just resolve) the GPU-profile rules: udev / modprobe / environment.d + initramfs rebuild.

Used by ``fix-interlaced-kernel.sh`` so the rules logic exists in exactly one tested place.

  interlace_apply_rules.py --gpu-profile auto --print-profile      # print the resolved profile only
  interlace_apply_rules.py --gpu-profile gcn-single [--dry-run]    # apply the rules
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from interlace_boot import rebuild_initramfs, sync_boot
from interlace_gpu import (
    GPU_PROFILES,
    GpuDevice,
    list_connectors,
    parse_lspci,
    resolve_gpu_profile,
)
from interlace_rules import apply_gpu_rules, render_gpu_rules
from interlace_runner import CommandError, Host, Runner


def resolve_profile(host: Host, requested: str) -> tuple[str, list[GpuDevice]]:
    """Resolve ``requested`` (possibly ``auto``) to a concrete GPU profile using lspci + DRM connectors."""
    res = host.runner.query(["lspci", "-D", "-nn"], ok_to_fail=True)
    gpus = parse_lspci(res.stdout if res.returncode == 0 else "")
    connectors = [c.name for c in list_connectors(host.paths.drm_class)]
    return resolve_gpu_profile(requested, gpus, connectors), gpus


def apply_profile(
    host: Host, profile: str, gpus: Sequence[GpuDevice], *, desktop_env: bool = True, initramfs: bool = True,
) -> None:
    """Write the udev/modprobe/environment.d rules for ``profile`` and optionally rebuild the initramfs."""
    host.runner.say(f"==> Applying GPU architecture rules for profile: {profile}")
    plan = render_gpu_rules(profile, gpus, host.paths, host.exists, desktop_env=desktop_env)
    apply_gpu_rules(host, plan)
    if initramfs:
        rebuild_initramfs(host)


def main(argv: Sequence[str] | None = None, host: Host | None = None) -> int:
    p = argparse.ArgumentParser(description="Resolve/apply GPU architecture & multi-GPU rules")
    p.add_argument("--gpu-profile", choices=GPU_PROFILES, default="auto")
    p.add_argument("--print-profile", action="store_true", help="print the resolved profile and exit")
    p.add_argument("--no-initramfs", action="store_true", help="do not rebuild the initramfs afterwards")
    p.add_argument("--sync-only", action="store_true", help="only rebuild initramfs / regenerate GRUB; no rules")
    p.add_argument("--no-desktop-env", action="store_true", help="do not write KWin environment.d files")
    p.add_argument("--dry-run", action="store_true", help="print every command/file write without performing it")
    args = p.parse_args(argv)

    host = host or Host(runner=Runner(dry_run=args.dry_run))
    profile, gpus = resolve_profile(host, args.gpu_profile)

    if args.print_profile:
        print(profile)
        return 0
    if host.runner.is_root and not args.dry_run:
        print("ERROR: Run as your normal user; privileged steps use sudo.", file=sys.stderr)
        return 1

    if args.sync_only:
        try:
            sync_boot(host)
        except CommandError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        return 0

    try:
        apply_profile(host, profile, gpus, desktop_env=not args.no_desktop_env, initramfs=not args.no_initramfs)
    except CommandError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
