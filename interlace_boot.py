"""
Bootloader / initramfs detection and application for the Linux CRT Interlacing Suite.

Detection takes injected ``which`` / ``exists`` callables (via ``Host``) so tests can simulate
Limine, GRUB, systemd-boot, mkinitcpio, dracut and initramfs-tools hosts. Every mutation goes
through ``Runner`` so ``--dry-run`` prints it instead of performing it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from interlace_cmdline import (
    INITRAMFS_TOOLS_HOOK,
    add_to_mkinitcpio_files,
    dracut_conf_text,
    update_cmdline_text,
    update_kernel_cmdline_text,
)
from interlace_runner import Host


def initramfs_command(which: Callable[[str], str | None]) -> list[str] | None:
    """The regeneration command for the first initramfs generator found on this host."""
    if which("limine-mkinitcpio"):
        return ["limine-mkinitcpio"]
    if which("mkinitcpio"):
        return ["mkinitcpio", "-P"]
    if which("dracut"):
        return ["dracut", "--regenerate-all", "--force"]
    if which("update-initramfs"):
        return ["update-initramfs", "-u", "-k", "all"]
    return None


def grub_regen_command(
    which: Callable[[str], str | None], exists: Callable[[Path], bool], cfg_candidates: Sequence[Path],
) -> list[str] | None:
    """GRUB regeneration: Debian ``update-grub``, else ``grub-mkconfig`` / ``grub2-mkconfig`` (Fedora, SUSE)."""
    if which("update-grub"):
        return ["update-grub"]
    for tool in ("grub-mkconfig", "grub2-mkconfig"):
        if which(tool):
            existing = [c for c in cfg_candidates if exists(c)]
            preferred = [c for c in existing if ("grub2" in str(c)) == (tool == "grub2-mkconfig")]
            target = (preferred or existing or [cfg_candidates[0]])[0]
            return [tool, "-o", str(target)]
    return None


def loader_entry_dirs(host: Host) -> list[Path]:
    """systemd-boot entry dirs: static candidates plus whatever ``bootctl`` reports for this host."""
    dirs = list(host.paths.loader_entry_dirs)
    if host.which("bootctl"):
        for flag in ("--print-esp-path", "--print-boot-path"):
            res = host.runner.query(["bootctl", flag], ok_to_fail=True)
            path = res.stdout.strip()
            if res.returncode == 0 and path:
                cand = Path(path) / "loader" / "entries"
                if cand not in dirs:
                    dirs.append(cand)
    return dirs


def detect_bootloaders(host: Host) -> list[str]:
    found: list[str] = []
    if host.exists(host.paths.default_limine) or host.which("limine-mkinitcpio") or host.which("limine"):
        found.append("limine")
    if host.exists(host.paths.default_grub):
        found.append("grub")
    if host.exists(host.paths.kernel_cmdline) or host.which("bootctl"):
        found.append("systemd-boot")
    return found


def embed_edid_in_initramfs(host: Host, edid_dest: Path) -> list[str]:
    """Embed the EDID for every initramfs generator whose config exists. Returns what was touched."""
    runner, paths = host.runner, host.paths
    touched: list[str] = []
    dest = str(edid_dest)
    if host.exists(paths.mkinitcpio_conf):
        text = runner.read_text(paths.mkinitcpio_conf)
        new_text = add_to_mkinitcpio_files(text, dest)
        if new_text != text:
            runner.backup_once(paths.mkinitcpio_conf)
            runner.write_text(paths.mkinitcpio_conf, new_text)
        touched.append("mkinitcpio")
    if host.exists(paths.dracut_conf_dir):
        conf = paths.dracut_conf_dir / "99-crt-edid.conf"
        existing = runner.read_text(conf)
        new_text = dracut_conf_text(existing, dest)
        if new_text != existing:
            runner.write_text(conf, new_text)
        touched.append("dracut")
    # Require the config directory, not just the binary: a bare `update-initramfs` shim can exist
    # on hosts (e.g. Arch derivatives) that do not actually use initramfs-tools.
    if host.exists(paths.initramfs_hooks_dir.parent):
        runner.write_text(paths.initramfs_hooks_dir / "crt-edid", INITRAMFS_TOOLS_HOOK, mode=0o755)
        touched.append("initramfs-tools")
    return touched


def update_bootloaders(host: Host, conn: str, rel_fw: str, profile: str) -> list[str]:
    """Update every bootloader config present. Returns the paths that were rewritten.

    A config that cannot be read is skipped rather than overwritten blindly.
    """
    runner, paths = host.runner, host.paths
    updated: list[str] = []

    def rewrite(path: Path, key: str | None) -> None:
        text = runner.read_text(path)
        if not text.strip():
            runner.say(f"  -> Skipping {path}: empty or unreadable (refusing to overwrite blindly).")
            return
        if key is None:
            new_text = update_kernel_cmdline_text(text, conn, rel_fw, profile)
        else:
            new_text = update_cmdline_text(text, key, conn, rel_fw, profile)
        runner.backup_once(path)
        runner.write_text(path, new_text)
        updated.append(str(path))

    if host.exists(paths.default_limine):
        rewrite(paths.default_limine, "KERNEL_CMDLINE")
    if host.exists(paths.default_grub):
        rewrite(paths.default_grub, "GRUB_CMDLINE_LINUX_DEFAULT")
        cmd = grub_regen_command(host.which, host.exists, paths.grub_cfg_candidates)
        if cmd:
            runner.run(cmd, privileged=True)
        else:
            runner.say("  -> No GRUB config generator (update-grub/grub-mkconfig/grub2-mkconfig) found; regenerate manually.")
    if host.exists(paths.kernel_cmdline):
        rewrite(paths.kernel_cmdline, None)
    for entry_dir in loader_entry_dirs(host):
        for econf in runner.list_files(entry_dir) or []:
            rewrite(econf, "options")
    return updated


def sync_boot(host: Host) -> bool:
    """Rebuild the initramfs and, when GRUB is present, regenerate its config (post kernel install)."""
    rebuilt = rebuild_initramfs(host)
    if host.exists(host.paths.default_grub):
        cmd = grub_regen_command(host.which, host.exists, host.paths.grub_cfg_candidates)
        if cmd:
            host.runner.run(cmd, privileged=True)
        else:
            host.runner.say("  -> No GRUB config generator found; regenerate your GRUB config manually.")
    return rebuilt


def rebuild_initramfs(host: Host) -> bool:
    cmd = initramfs_command(host.which)
    if cmd is None:
        host.runner.say("  -> No initramfs generator found (limine-mkinitcpio/mkinitcpio/dracut/update-initramfs); skipping.")
        return False
    host.runner.run(cmd, privileged=True)
    return True
