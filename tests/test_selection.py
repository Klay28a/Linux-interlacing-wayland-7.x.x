"""interlace_selection: dropdown choices -> resolved profile/adapter/port -> exact script arguments."""

import pytest

from conftest import make_paths, materialize_fixture
from interlace_selection import (
    Resolved,
    Selection,
    SelectionError,
    kernel_args,
    resolve,
    setup_args,
)
from interlace_sysinfo import SystemInfo, collect_system_info


def info_for(pc, tmp_path):
    paths = make_paths(tmp_path)
    materialize_fixture(pc, tmp_path)
    present = set(pc["which"])
    return collect_system_info(paths, pc["lspci"], lambda n: n if n in present else None, pc["uname_r"]), paths


def test_auto_resolves_to_the_fixtures_documented_facts(pc, tmp_path):
    info, _ = info_for(pc, tmp_path)
    res = resolve(Selection(), info)
    exp = pc["expected"]
    assert (res.profile, res.adapter, res.connector) == (exp["gpu_profile"], exp["adapter"], exp["connector"])


def test_explicit_choices_win_over_detection(pc, tmp_path):
    info, _ = info_for(pc, tmp_path)
    sel = Selection(gpu_profile="gcn-single", adapter_mode="hdmi-dac", connector="HDMI-A-1")
    assert resolve(sel, info) == Resolved("gcn-single", "hdmi-dac", "HDMI-A-1")


def test_adapter_follows_the_chosen_port_when_left_on_auto(pc, tmp_path):
    info, _ = info_for(pc, tmp_path)
    assert resolve(Selection(connector="DP-3"), info).adapter == "dp-dac"
    assert resolve(Selection(connector="HDMI-A-2"), info).adapter == "hdmi-dac"
    assert resolve(Selection(connector="VGA-1"), info).adapter == "analog-native"


def test_setup_button_passes_the_resolved_values_not_auto(pc, tmp_path):
    info, _ = info_for(pc, tmp_path)
    sel = Selection(custom_edid="/tmp/my.bin")
    res = resolve(sel, info)
    args = setup_args(sel, res)
    assert args == [
        "--gpu-profile", res.profile, "--adapter-mode", res.adapter, "--connector", res.connector,
        "--edid", "/tmp/my.bin",
    ]
    assert "auto" not in args


def test_reload_edid_is_the_same_command_plus_live_only(pc, tmp_path):
    info, _ = info_for(pc, tmp_path)
    sel = Selection()
    res = resolve(sel, info)
    assert setup_args(sel, res, live_only=True) == [*setup_args(sel, res), "--live-only"]


def test_setup_without_any_port_is_refused_before_running():
    info = SystemInfo((), (), (), "6.8.0", "Unknown", "Unknown", "", {}, False, "rdna-single")
    res = resolve(Selection(), info)
    assert res.connector == ""
    with pytest.raises(SelectionError, match="No video port"):
        setup_args(Selection(), res)


@pytest.mark.parametrize("kver", ["auto", "7.3", "7.2", "6.18", "6.12", "6.6", "6.1", "linux-next"])
def test_kernel_button_passes_the_selected_kernel_and_profile(kver):
    res = Resolved("dual-nvidia-amd", "analog-native", "VGA-1")
    args = kernel_args(Selection(kernel_version=kver), res)
    assert args == ["--gpu-profile", "dual-nvidia-amd", "--adapter-mode", "analog-native", "--kernel-version", kver]


def test_rdna_checkbox_maps_to_no_rdna_patch():
    res = Resolved("rdna-single", "dp-dac", "DP-1")
    assert "--no-rdna-patch" in kernel_args(Selection(rdna_patch=False), res)
    assert "--no-rdna-patch" not in kernel_args(Selection(rdna_patch=True), res)


def test_apply_gpu_rules_is_config_only_and_ignores_the_kernel_choice():
    res = Resolved("gcn-single", "analog-native", "VGA-1")
    args = kernel_args(Selection(kernel_version="6.1", rdna_patch=False), res, config_only=True)
    assert args == ["--gpu-profile", "gcn-single", "--adapter-mode", "analog-native", "--config-only"]
