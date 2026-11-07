"""Individual checks: rules content, the kernel build record, Linux CRU, and the no-port case."""

import json

from conftest import make_paths
from interlace_selection import Selection, resolve
from interlace_sysinfo import collect_system_info
from interlace_verify import check_cru, check_edid, check_kernel, check_rules
from machine import Machine


def test_rules_check_requires_exact_content_and_no_stale_files(pc, tmp_path):
    m = Machine(pc, tmp_path)
    sel = Selection()
    m.apply_rules(sel)
    res, _, info = m.look(sel)
    assert check_rules(res, info, m.paths).ok
    (m.paths.user_env_dir / "kwin-cursor.conf").write_text("something else\n")
    assert not check_rules(res, info, m.paths).ok


def test_a_file_the_profile_must_not_have_makes_the_rules_unapplied(tmp_path):
    paths = make_paths(tmp_path)
    info = collect_system_info(paths, "0000:03:00.0 VGA compatible controller [0300]: AMD Navi 22 [1002:73df]", lambda _n: None, "6.8")
    res = resolve(Selection(gpu_profile="rdna-single"), info)
    (paths.user_env_dir).mkdir(parents=True)
    (paths.user_env_dir / "kwin-cursor.conf").write_text("KWIN_FORCE_SW_CURSOR=1\n")
    assert check_rules(res, info, paths).ok
    paths.modprobe_dir.mkdir(parents=True)
    paths.gpu_modprobe_conf.write_text("options amdgpu si_support=1\n")
    stale = check_rules(res, info, paths)
    assert not stale.ok
    assert "amdgpu-crt.conf should not exist" in stale.detail


def test_kernel_check_tracks_the_build_record_the_running_kernel_and_the_selection(tmp_path):
    paths = make_paths(tmp_path)
    info = collect_system_info(paths, "", lambda _n: None, "7.3.1-1-cachyos")
    assert check_kernel(Selection(), info, paths).short == "Not built"
    paths.kernel_state_file.parent.mkdir(parents=True)

    def record(**kw):
        base = {"series": "7.3", "pkgver": "7.3.1", "pkgrel": "1", "rdna": True, "patches": []}
        paths.kernel_state_file.write_text(json.dumps({**base, **kw}))

    record()
    assert check_kernel(Selection(), info, paths).ok
    assert check_kernel(Selection(kernel_version="7.3"), info, paths).ok
    assert check_kernel(Selection(kernel_version="6.12"), info, paths).short == "Selected 6.12"
    assert check_kernel(Selection(rdna_patch=False), info, paths).short == "RDNA unlock differs"
    record(pkgver="7.4.0")
    assert check_kernel(Selection(), info, paths).short == "Reboot to load"


def test_cru_check_follows_the_install(tmp_path):
    paths = make_paths(tmp_path)
    assert not check_cru(collect_system_info(paths, "", lambda _n: None, "6.8")).ok
    exe = paths.home / ".local" / "bin" / "linux-cru"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    assert check_cru(collect_system_info(paths, "", lambda _n: None, "6.8")).ok


def test_check_edid_without_a_port_never_crashes(tmp_path):
    paths = make_paths(tmp_path)
    info = collect_system_info(paths, "", lambda _n: None, "6.8")
    assert check_edid(Selection(), resolve(Selection(), info), info, paths).short == "No port"


def test_sysinfo_matches_each_fixtures_documented_boot_stack(pc, tmp_path):
    info = Machine(pc, tmp_path).info()
    exp = pc["expected"]
    assert info.bootloader.lower().replace("-", "") == exp["bootloaders"][0].replace("-", "")
    assert info.recommended_profile == exp["gpu_profile"]
    assert [p.name for p in info.ports if p.status == "connected"] == [exp["connector"]]
