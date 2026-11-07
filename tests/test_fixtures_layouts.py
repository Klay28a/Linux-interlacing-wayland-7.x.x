"""Every mock PC layout (CachyOS/Limine dual-GPU, Fedora/systemd-boot RDNA, Ubuntu/GRUB GCN) end to end.

All inputs are JSON fixtures materialised in a temp directory: no real hardware, /etc, /boot or
/sys path is ever consulted, and ``assert_sandboxed`` proves it.
"""

from pathlib import Path
from typing import Any

import interlace_apply_rules
import interlace_boot
import interlace_kernel
from conftest import (
    FIXTURE_NAMES,
    assert_sandboxed,
    build_fixture_host,
    load_fixture,
    make_paths,
    materialize_fixture,
)
from interlace_gpu import (
    edid_file_name,
    list_connectors,
    parse_lspci,
    pick_connector,
    resolve_adapter,
)


def setup_pc(pc: dict[str, Any], tmp_path: Path, *, dry_run: bool = False):
    paths = make_paths(tmp_path)
    assert_sandboxed(paths, tmp_path)
    materialize_fixture(pc, tmp_path)
    host, runner = build_fixture_host(pc, tmp_path, paths, dry_run=dry_run)
    return host, runner, paths


def test_three_distinct_layouts_exist() -> None:
    fixtures = [load_fixture(n) for n in FIXTURE_NAMES]
    assert len(fixtures) == 3
    assert {f["expected"]["package_manager"] for f in fixtures} == {"pacman", "dnf", "apt-get"}
    assert {tuple(f["expected"]["bootloaders"]) for f in fixtures} == {("limine",), ("systemd-boot",), ("grub",)}
    assert {f["expected"]["gpu_profile"] for f in fixtures} == {"dual-nvidia-amd", "rdna-single", "gcn-single"}
    assert {f["lsblk"]["blockdevices"][0]["tran"] for f in fixtures} == {"nvme", "sata"}


def test_fixtures_reference_disks_by_stable_id() -> None:
    """Rule 1: disks are identified by id-link, never by a host's /dev/sdX name."""
    for name in FIXTURE_NAMES:
        for disk in load_fixture(name)["lsblk"]["blockdevices"]:
            assert disk["id-link"], f"{name}: disk {disk['name']} has no stable by-id link"


def test_gpu_profile_and_connector_resolution(pc: dict[str, Any], tmp_path: Path) -> None:
    host, _, paths = setup_pc(pc, tmp_path)
    exp = pc["expected"]
    profile, gpus = interlace_apply_rules.resolve_profile(host, "auto")
    assert profile == exp["gpu_profile"]
    assert len(gpus) == len(parse_lspci(pc["lspci"]))
    conn = pick_connector("auto", profile, list_connectors(paths.drm_class))
    assert conn == exp["connector"]
    assert resolve_adapter("auto", conn) == exp["adapter"]
    assert edid_file_name(conn) == exp["edid_file"]


def test_bootloader_and_initramfs_detection(pc: dict[str, Any], tmp_path: Path) -> None:
    host, _, _ = setup_pc(pc, tmp_path)
    exp = pc["expected"]
    assert interlace_boot.detect_bootloaders(host) == exp["bootloaders"]
    assert interlace_boot.initramfs_command(host.which) == exp["initramfs_command"]


def test_kernel_target_resolution_from_uname(pc: dict[str, Any]) -> None:
    target = interlace_kernel.resolve_kernel_target("auto", pc["uname_r"])
    exp = pc["expected"]["kernel_target"]
    assert (target.kver, target.subdir, target.commit, target.patch_series) == (
        exp["kver"], exp["subdir"], exp["commit"], exp["patch_series"],
    )


def test_config_only_applies_rules_and_rebuilds_initramfs(pc: dict[str, Any], tmp_path: Path) -> None:
    host, runner, paths = setup_pc(pc, tmp_path)
    assert interlace_kernel.main(["--config-only"], host=host) == 0
    exp = pc["expected"]
    for item in exp["environment_files"]:
        absent = item.endswith("-absent")
        name = item[: -len("-absent")] if absent else item
        assert (str(paths.user_env_dir / name) in runner.installed) is not absent, item
    udev = runner.installed.get(str(paths.gpu_udev_rules), b"").decode()
    for link in exp["udev_rule_links"]:
        assert link in udev
    assert (not exp["udev_rule_links"]) == (str(paths.gpu_udev_rules) not in runner.installed)
    assert ["sudo", "-n", *exp["initramfs_command"]] in runner.executed
    assert all(c[1] == "-n" for c in runner.executed if c[0] == "sudo"), "privileged calls must never prompt"
    assert "==> [1/1]" in "\n".join(runner.messages)


def test_kernel_build_is_refused_cleanly_without_pacman(pc: dict[str, Any], tmp_path: Path, capsys) -> None:
    host, runner, _ = setup_pc(pc, tmp_path)
    code = interlace_kernel.main(["--build-root", str(tmp_path / "kb")], host=host, suite_dir=tmp_path)
    err = capsys.readouterr().err
    if pc["expected"]["can_build_kernel"]:
        assert "Arch-based" not in err
    else:
        assert code == 1
        assert "Arch-based" in err
        assert "--config-only" in err
        assert not any(c[0] == "git" for c in runner.executed), "must not clone anything on an unsupported distro"
