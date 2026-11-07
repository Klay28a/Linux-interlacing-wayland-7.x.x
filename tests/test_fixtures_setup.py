"""The setup tool against every mock PC: right bootloader files, preserved lines, and a truthful --dry-run."""

from pathlib import Path
from typing import Any

import interlace_kernel
import interlace_setup
from test_fixtures_layouts import setup_pc

READ_ONLY = ("pacman", "uname", "bootctl")


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def test_setup_updates_the_right_bootloader_files(pc: dict[str, Any], tmp_path: Path) -> None:
    host, runner, paths = setup_pc(pc, tmp_path)
    exp = pc["expected"]
    assert interlace_setup.main(["--connector", exp["connector"]], host=host) == 0
    assert str(paths.firmware_edid_dir / exp["edid_file"]) in runner.installed
    boot_targets = {
        "limine_cmdline_contains": paths.default_limine,
        "grub_cmdline_contains": paths.default_grub,
        "kernel_cmdline_contains": paths.kernel_cmdline,
    }
    checked = 0
    for key, path in boot_targets.items():
        for needle in exp.get(key, []):
            checked += 1
            assert needle in runner.installed[str(path)].decode(), f"{needle!r} missing from {path.name}"
    assert checked > 0
    if "mkinitcpio_files_contains" in exp:
        assert exp["mkinitcpio_files_contains"] in runner.installed[str(paths.mkinitcpio_conf)].decode()
    if "dracut_conf_contains" in exp:
        conf = runner.installed[str(paths.dracut_conf_dir / "99-crt-edid.conf")].decode()
        assert exp["dracut_conf_contains"] in conf
    if "initramfs_hook" in exp:
        assert str(paths.initramfs_hooks_dir / exp["initramfs_hook"]) in runner.installed
    if "grub_regen_command" in exp:
        assert ["sudo", "-n", *exp["grub_regen_command"]] in runner.executed


def test_setup_preserves_unrelated_lines_in_existing_boot_files(pc: dict[str, Any], tmp_path: Path) -> None:
    host, runner, _ = setup_pc(pc, tmp_path)
    assert interlace_setup.main(["--connector", pc["expected"]["connector"]], host=host) == 0
    # Lines setup is *meant* to edit (kernel command lines, mkinitcpio's FILES=() array) may only grow:
    # every original token must survive. All other lines must be byte-for-byte unchanged.
    edited_prefixes = ("options", "KERNEL_CMDLINE", "GRUB_CMDLINE_LINUX_DEFAULT", "FILES=")
    whole_file_is_cmdline = ("etc/kernel/cmdline",)
    unchanged = grown = 0
    for rel, original in pc["files"].items():
        installed = runner.installed.get(str(tmp_path / rel))
        if installed is None:
            continue
        new_text = installed.decode()
        for line in original.splitlines():
            if line.startswith(edited_prefixes) or rel in whole_file_is_cmdline:
                grown += 1
                for token in line.replace('"', " ").replace("(", " ").replace(")", " ").split():
                    assert token in new_text, f"{rel}: lost token {token!r}"
            elif "=" in line:
                unchanged += 1
                assert line in new_text.splitlines(), f"{rel}: lost unrelated line {line!r}"
    assert grown > 0


def test_dry_run_changes_nothing_on_any_layout(pc: dict[str, Any], tmp_path: Path) -> None:
    host, runner, _ = setup_pc(pc, tmp_path, dry_run=True)
    before = _snapshot(tmp_path)
    assert interlace_kernel.main(["--config-only", "--dry-run"], host=host) == 0
    assert interlace_setup.main(["--dry-run", "--connector", pc["expected"]["connector"]], host=host) == 0
    assert [c for c in runner.mutating if c[0] not in READ_ONLY] == []
    assert runner.installed == {}
    assert _snapshot(tmp_path) == before
    assert "[dry-run]" in "\n".join(runner.messages)
