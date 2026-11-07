"""What each click launches: the dropdown mix reaches the script as explicit, resolved arguments."""

from gui_fixtures import ROOT


def test_setup_button_launches_the_script_with_the_resolved_selection(window, pc):
    window.run_setup_btn.click()
    _, cmd = window.launched[-1]
    exp = pc["expected"]
    assert cmd[:2] == ["bash", str(ROOT / "setup-interlace-env.sh")]
    assert cmd[2:] == [
        "--gpu-profile", exp["gpu_profile"], "--adapter-mode", exp["adapter"], "--connector", exp["connector"],
    ]


def test_reload_button_is_the_same_command_plus_live_only(window):
    window.run_setup_btn.click()
    plain = window.launched[-1][1]
    window.reload_btn.click()
    assert window.launched[-1][1] == [*plain, "--live-only"]


def test_kernel_button_passes_every_dropdown_value(window, gui_module):
    for index, (key, _label) in enumerate(gui_module.KERNEL_VERSIONS):
        window.kernel_combo.setCurrentIndex(index)
        window.run_kernel_btn.click()
        cmd = window.launched[-1][1]
        assert cmd[1] == str(ROOT / "fix-interlaced-kernel.sh")
        assert cmd[cmd.index("--kernel-version") + 1] == key
        assert "--config-only" not in cmd


def test_rules_button_is_config_only_and_ignores_the_kernel_choice(window):
    window.kernel_combo.setCurrentIndex(3)
    window.rules_btn.click()
    cmd = window.launched[-1][1]
    assert cmd[-1] == "--config-only"
    assert "--kernel-version" not in cmd


def test_rdna_checkbox_reaches_the_kernel_command(window):
    window.rdna_chk.setChecked(False)
    window.run_kernel_btn.click()
    assert "--no-rdna-patch" in window.launched[-1][1]
    window.rdna_chk.setChecked(True)
    window.run_kernel_btn.click()
    assert "--no-rdna-patch" not in window.launched[-1][1]


def test_dropdowns_change_what_the_buttons_pass(window):
    window.gpu_combo.setCurrentIndex(window.gpu_combo.findData("gcn-single"))
    window.adapter_combo.setCurrentIndex(window.adapter_combo.findData("hdmi-dac"))
    window.conn_combo.setCurrentIndex(window.conn_combo.findData("HDMI-A-2"))
    window.run_setup_btn.click()
    cmd = window.launched[-1][1]
    assert cmd[cmd.index("--gpu-profile") + 1] == "gcn-single"
    assert cmd[cmd.index("--adapter-mode") + 1] == "hdmi-dac"
    assert cmd[cmd.index("--connector") + 1] == "HDMI-A-2"


def test_install_cru_button_runs_its_script(window):
    window.install_cru_btn.click()
    assert window.launched[-1][1] == ["bash", str(ROOT / "install-linux-cru.sh")]


def test_disconnected_ports_are_selectable_for_pre_configuring(window):
    items = [window.conn_combo.model().item(i) for i in range(window.conn_combo.count())]
    assert all(item.isEnabled() for item in items)
    assert window.conn_combo.findData("DP-2") >= 0 or window.conn_combo.findData("HDMI-A-2") >= 0


def test_saved_selection_is_restored_on_the_next_launch(window, gui_module, qapp):
    window.gpu_combo.setCurrentIndex(window.gpu_combo.findData("gcn-single"))
    window.kernel_combo.setCurrentIndex(window.kernel_combo.findData("6.12"))
    window.rdna_chk.setChecked(False)
    second = gui_module.InterlaceSuiteWindow(probe=window._probe)
    try:
        assert second.gpu_combo.currentData() == "gcn-single"
        assert second.kernel_combo.currentData() == "6.12"
        assert not second.rdna_chk.isChecked()
    finally:
        second.close()
