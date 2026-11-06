"""Bootloader / initramfs detection and GPU rules against a sandboxed Host."""

from pathlib import Path

from conftest import LSPCI_GCN_ONLY, LSPCI_NV_AMD, LSPCI_RDNA_ONLY, build_host
from interlace_boot import (
    detect_bootloaders,
    embed_edid_in_initramfs,
    grub_regen_command,
    initramfs_command,
    loader_entry_dirs,
    update_bootloaders,
)
from interlace_gpu import parse_lspci
from interlace_rules import apply_gpu_rules, render_gpu_rules


def _exists(p: Path) -> bool:
    return p.exists()


def _which(*names: str):
    return lambda n: f"/usr/bin/{n}" if n in names else None


def test_initramfs_generator_detection_order():
    assert initramfs_command(_which("limine-mkinitcpio", "mkinitcpio")) == ["limine-mkinitcpio"]
    assert initramfs_command(_which("mkinitcpio")) == ["mkinitcpio", "-P"]
    assert initramfs_command(_which("dracut")) == ["dracut", "--regenerate-all", "--force"]
    assert initramfs_command(_which("update-initramfs")) == ["update-initramfs", "-u", "-k", "all"]
    assert initramfs_command(_which()) is None


def test_grub_regen_supports_debian_arch_and_fedora(tmp_path: Path):
    cands = (tmp_path / "boot/grub/grub.cfg", tmp_path / "boot/grub2/grub.cfg")
    cands[1].parent.mkdir(parents=True)
    cands[1].write_text("x")
    assert grub_regen_command(_which("update-grub"), _exists, cands) == ["update-grub"]
    assert grub_regen_command(_which("grub2-mkconfig"), _exists, cands) == ["grub2-mkconfig", "-o", str(cands[1])]
    assert grub_regen_command(_which("grub-mkconfig"), _exists, cands)[:2] == ["grub-mkconfig", "-o"]
    assert grub_regen_command(_which(), _exists, cands) is None


def test_bootloader_detection(sandbox):
    root, paths = sandbox
    host, _ = build_host(root, paths)
    assert detect_bootloaders(host) == []
    paths.default_grub.parent.mkdir(parents=True)
    paths.default_grub.write_text('GRUB_CMDLINE_LINUX_DEFAULT=""\n')
    host, _ = build_host(root, paths, tools=("bootctl",))
    assert detect_bootloaders(host) == ["grub", "systemd-boot"]


def test_bootctl_paths_extend_loader_dirs(sandbox):
    root, paths = sandbox
    host, runner = build_host(root, paths, tools=("bootctl",))
    runner.queries_ok["--print-esp-path"] = "/mnt/esp\n"
    assert Path("/mnt/esp/loader/entries") in loader_entry_dirs(host)


def test_initramfs_tools_hook_needs_config_dir_not_just_binary(sandbox):
    """Regression: a bare `update-initramfs` shim on an Arch host must not create /etc/initramfs-tools."""
    root, paths = sandbox
    host, runner = build_host(root, paths, tools=("update-initramfs",))
    assert embed_edid_in_initramfs(host, paths.firmware_edid_dir / "x.bin") == []
    assert runner.installed == {}

    paths.initramfs_hooks_dir.parent.mkdir(parents=True)
    host, runner = build_host(root, paths, tools=("update-initramfs",))
    assert embed_edid_in_initramfs(host, paths.firmware_edid_dir / "x.bin") == ["initramfs-tools"]
    assert str(paths.initramfs_hooks_dir / "crt-edid") in runner.installed


def test_update_bootloaders_rewrites_grub_preserving_other_lines(sandbox):
    root, paths = sandbox
    paths.default_grub.parent.mkdir(parents=True)
    paths.default_grub.write_text('GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
    host, runner = build_host(root, paths, tools=("grub2-mkconfig",))
    updated = update_bootloaders(host, "DP-1", "edid/cru-dp-1.bin", "rdna-single")
    assert updated == [str(paths.default_grub)]
    written = runner.installed[str(paths.default_grub)].decode()
    assert "GRUB_TIMEOUT=5" in written
    assert "drm.edid_firmware=DP-1:edid/cru-dp-1.bin" in written
    assert any(c[:2] == ["sudo", "-n"] and "grub2-mkconfig" in c for c in runner.executed)


def test_unreadable_bootloader_file_is_never_overwritten(sandbox):
    root, paths = sandbox
    paths.default_limine.parent.mkdir(parents=True)
    paths.default_limine.write_text("")
    host, runner = build_host(root, paths)
    assert update_bootloaders(host, "DP-1", "edid/a.bin", "rdna-single") == []
    assert str(paths.default_limine) not in runner.installed


def test_gpu_rules_dual_nvidia_amd_and_single_cleanup(sandbox):
    _, paths = sandbox
    plan = render_gpu_rules("dual-nvidia-amd", parse_lspci(LSPCI_NV_AMD), paths, _exists)
    rules = plan.write[paths.gpu_udev_rules]
    assert "0x2484" in rules
    assert "primary-nvidia" in rules
    assert "0x6610" in rules
    assert "secondary-amd" in rules
    assert paths.gpu_modprobe_conf in plan.write
    assert plan.reload_udev

    paths.gpu_udev_rules.parent.mkdir(parents=True)
    paths.gpu_udev_rules.write_text("old")
    single = render_gpu_rules("rdna-single", parse_lspci(LSPCI_RDNA_ONLY), paths, _exists)
    assert single.remove == [paths.gpu_udev_rules]
    assert single.reload_udev


def test_gpu_rules_can_skip_desktop_env_files(sandbox):
    _, paths = sandbox
    plan = render_gpu_rules("gcn-single", parse_lspci(LSPCI_GCN_ONLY), paths, _exists, desktop_env=False)
    assert not any(p.name == "kwin-cursor.conf" for p in plan.write)


def test_apply_gpu_rules_user_files_do_not_use_sudo(sandbox):
    root, paths = sandbox
    host, runner = build_host(root, paths)
    apply_gpu_rules(host, render_gpu_rules("gcn-single", parse_lspci(LSPCI_GCN_ONLY), paths, _exists))
    user_writes = [c for c in runner.executed if c[0] == "INSTALL" and "home/tester" in c[1]]
    assert user_writes
    assert all(c[3] == "user" for c in user_writes)
