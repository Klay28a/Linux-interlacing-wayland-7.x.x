#!/usr/bin/env python3
"""
CRT interlace environment setup (replaces the logic of ``setup-interlace-env.sh``).

Steps: resolve GPU profile + connector -> patch & install the EDID -> apply GPU rules ->
embed the EDID in the initramfs -> update bootloader command lines -> rebuild initramfs ->
reload the EDID live -> record state for the GUI.

Every state change goes through ``Runner`` so ``--dry-run`` prints the exact commands and file
writes without touching the system. The script never prompts: if no connector can be detected it
exits with an error telling you to pass ``--connector``.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from interlace_boot import (
    embed_edid_in_initramfs,
    rebuild_initramfs,
    update_bootloaders,
)
from interlace_cmdline import merge_edid_firmware_param
from interlace_edid import patch_edid
from interlace_gpu import (
    ADAPTER_MODES,
    GPU_PROFILES,
    GpuDevice,
    edid_file_name,
    list_connectors,
    parse_lspci,
    pick_connector,
    resolve_adapter,
    resolve_gpu_profile,
)
from interlace_rules import apply_gpu_rules, render_gpu_rules
from interlace_runner import CommandError, Host, Runner
from interlace_state import update_state


class SetupError(Exception):
    """A user-facing failure (printed without a traceback)."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="interlace_setup.py",
        description="Configure a custom CRT EDID, GPU rules, initramfs and bootloader for interlaced output.",
    )
    p.add_argument("edid_source", nargs="?", default="", help="EDID source file (default: installed file)")
    p.add_argument("positional_connector", nargs="?", default="", metavar="connector")
    p.add_argument("--gpu-profile", choices=GPU_PROFILES, default="auto")
    p.add_argument("--adapter-mode", choices=ADAPTER_MODES, default="auto")
    p.add_argument("--edid", default="", help="EDID source file")
    p.add_argument("--connector", default="", help="DRM connector name (e.g. DP-1) or 'auto'")
    p.add_argument("--live-only", action="store_true", help="Reload the EDID live; skip initramfs/bootloader")
    p.add_argument("--no-desktop-env", action="store_true", help="Do not write KWin environment.d files")
    p.add_argument("--dry-run", action="store_true", help="Print every command/file write without performing it")
    return p


def read_gpus(host: Host) -> list[GpuDevice]:
    res = host.runner.query(["lspci", "-D", "-nn"], ok_to_fail=True)
    return parse_lspci(res.stdout if res.returncode == 0 else "")


def read_edid(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def live_reload(host: Host, conn: str, rel_fw: str) -> None:
    """Make the running kernel pick up the new EDID without a reboot."""
    runner, paths = host.runner, host.paths
    if not host.exists(paths.edid_firmware_param):
        runner.say("  -> drm.edid_firmware parameter not available on this kernel; skipping live reload.")
        return
    runner.say(f"==> Reloading EDID override live on {conn}...")
    current = runner.read_text(paths.edid_firmware_param)
    runner.write_sysfs(paths.edid_firmware_param, merge_edid_firmware_param(current, conn, rel_fw))
    analog = conn.startswith(("VGA-", "DVI-I-"))
    entries = sorted(paths.drm_class.glob(f"card*-{conn}")) if paths.drm_class.is_dir() else []
    for entry in entries:
        status = entry / "status"
        if not status.exists():
            continue
        runner.write_sysfs(status, "off")
        runner.pause(0.15)
        runner.write_sysfs(status, "detect")
        if analog or status.read_text(encoding="utf-8").strip() != "connected":
            runner.write_sysfs(status, "on")
    runner.run(["udevadm", "trigger", "--action=change", "--subsystem-match=drm"], privileged=True, ok_to_fail=True)


def resolve_connector(args: argparse.Namespace, host: Host, profile: str) -> str:
    requested = args.connector or args.positional_connector or "auto"
    if requested == "auto":
        conn = pick_connector(args.adapter_mode, profile, list_connectors(host.paths.drm_class))
        if conn is None:
            raise SetupError(
                f"No DRM connector could be detected under {host.paths.drm_class}. "
                "Re-run with --connector <name> (e.g. DP-1, HDMI-A-1, VGA-1)."
            )
        return conn
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", requested):
        raise SetupError(f"Invalid connector name: {requested!r}")
    return requested


def run_setup(args: argparse.Namespace, host: Host) -> int:
    runner, paths = host.runner, host.paths
    edid_src_arg = args.edid or args.edid_source

    gpus = read_gpus(host)
    connectors = list_connectors(paths.drm_class)
    profile = resolve_gpu_profile(args.gpu_profile, gpus, [c.name for c in connectors])
    conn = resolve_connector(args, host, profile)

    adapter = resolve_adapter(args.adapter_mode, conn)
    edid_name = edid_file_name(conn)
    edid_dest = paths.firmware_edid_dir / edid_name
    rel_fw = f"edid/{edid_name}"
    src_path = Path(edid_src_arg) if edid_src_arg else edid_dest

    runner.say("==> [1/5] Configuration Summary:")
    runner.say(f"  -> GPU Profile   : {profile} (requested: {args.gpu_profile})")
    runner.say(f"  -> Adapter Preset: {adapter} (requested: {args.adapter_mode})")
    runner.say(f"  -> DRM Connector : {conn} (Firmware target: {edid_dest})")

    runner.say(f"==> [2/5] Preparing Linux-formatted EDID at {edid_dest}...")
    src_bytes = read_edid(src_path)
    if edid_src_arg and (src_bytes is None or len(src_bytes) < 128):
        raise SetupError(f"EDID source {src_path} is missing, unreadable or shorter than 128 bytes.")
    if src_bytes is None and src_path.exists():
        # Never replace an installed EDID we merely failed to read with a generic default.
        raise SetupError(f"Installed EDID {src_path} exists but could not be read; refusing to overwrite it.")
    try:
        data, log = patch_edid(src_bytes, adapter, profile, conn, str(src_path))
    except ValueError as exc:
        raise SetupError(str(exc)) from exc
    for line in log:
        runner.say(line)
    runner.install_bytes(edid_dest, data)

    runner.say(f"==> [3/5] Applying GPU architecture & multi-GPU rules for profile: {profile}...")
    plan = render_gpu_rules(profile, gpus, paths, host.exists, desktop_env=not args.no_desktop_env)
    apply_gpu_rules(host, plan)

    if args.live_only:
        runner.say("==> [4/5] --live-only specified: skipping initramfs & bootloader rebuild.")
    else:
        runner.say(f"==> [4/5] Embedding {edid_dest} in initramfs configuration...")
        embedded = embed_edid_in_initramfs(host, edid_dest)
        runner.say(f"  -> Initramfs configs updated: {', '.join(embedded) or 'none found'}")
        runner.say("==> [5/5] Updating bootloader kernel parameters (preserving multi-port EDIDs)...")
        updated = update_bootloaders(host, conn, rel_fw, profile)
        runner.say(f"  -> Bootloader configs updated: {', '.join(updated) or 'none found'}")
        rebuild_initramfs(host)

    live_reload(host, conn, rel_fw)

    state = update_state(
        runner.read_text(paths.state_file), conn, rel_fw, profile, adapter,
        str(src_path) if edid_src_arg else "", args.live_only, int(time.time()),
    )
    runner.write_text(paths.state_file, state)
    runner.say(f"==> Environment setup complete! (Profile: {profile} | Adapter: {adapter} | Connector: {conn})")
    return 0


def main(argv: Sequence[str] | None = None, host: Host | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = host or Host(runner=Runner(dry_run=args.dry_run))
    if host.runner.is_root and not args.dry_run:
        print("ERROR: Run as your normal user; privileged steps use sudo -n.", file=sys.stderr)
        return 1
    try:
        return run_setup(args, host)
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except CommandError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

