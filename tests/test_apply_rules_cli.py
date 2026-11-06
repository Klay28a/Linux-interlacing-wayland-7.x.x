"""interlace_apply_rules CLI: profile resolution, dry-run, initramfs rebuild."""

import interlace_apply_rules
from conftest import LSPCI_GCN_ONLY, LSPCI_NV_AMD, add_connector, build_host


def test_print_profile_resolves_auto_without_changing_anything(sandbox, capsys):
    root, paths = sandbox
    add_connector(root, "VGA-1", "connected")
    host, runner = build_host(root, paths, lspci=LSPCI_GCN_ONLY)
    assert interlace_apply_rules.main(["--print-profile"], host=host) == 0
    assert capsys.readouterr().out.strip() == "gcn-single"
    assert runner.mutating == []


def test_dual_gpu_dry_run_prints_plan_only(sandbox):
    root, paths = sandbox
    host, runner = build_host(root, paths, lspci=LSPCI_NV_AMD, tools=("mkinitcpio",), dry_run=True)
    assert interlace_apply_rules.main(["--dry-run", "--gpu-profile", "auto"], host=host) == 0
    assert runner.mutating == []
    text = "\n".join(runner.messages)
    assert "dual-nvidia-amd" in text
    assert "[dry-run] would run: sudo -n udevadm control --reload-rules" in text
    assert "[dry-run] would run: sudo -n mkinitcpio -P" in text


def test_apply_rebuilds_initramfs_with_noninteractive_sudo(sandbox):
    root, paths = sandbox
    host, runner = build_host(root, paths, lspci=LSPCI_GCN_ONLY, tools=("dracut",))
    assert interlace_apply_rules.main(["--gpu-profile", "gcn-single"], host=host) == 0
    assert ["sudo", "-n", "dracut", "--regenerate-all", "--force"] in runner.executed
    assert str(paths.gpu_modprobe_conf) in runner.installed


def test_sync_only_rebuilds_initramfs_and_grub_without_writing_rules(sandbox):
    root, paths = sandbox
    paths.default_grub.parent.mkdir(parents=True)
    paths.default_grub.write_text('GRUB_CMDLINE_LINUX_DEFAULT=""\n')
    host, runner = build_host(root, paths, tools=("mkinitcpio", "grub2-mkconfig"))
    assert interlace_apply_rules.main(["--sync-only"], host=host) == 0
    assert ["sudo", "-n", "mkinitcpio", "-P"] in runner.executed
    assert any(c[:3] == ["sudo", "-n", "grub2-mkconfig"] for c in runner.executed)
    assert runner.installed == {}


def test_no_initramfs_flag(sandbox):
    root, paths = sandbox
    host, runner = build_host(root, paths, lspci=LSPCI_GCN_ONLY, tools=("dracut",))
    assert interlace_apply_rules.main(["--gpu-profile", "gcn-single", "--no-initramfs"], host=host) == 0
    assert not any("dracut" in c for c in runner.executed)
