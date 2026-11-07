"""Linux CRU main window: every edit is saved, profiles are matched by real path, ports are selectable."""

import os
from pathlib import Path

import pytest

from interlace_edid import input_byte


def make_port(root: Path, name: str, status: str = "connected") -> dict:
    rel = "edid/crufile.bin" if name == "VGA-1" else f"edid/cru-{name.lower()}.bin"
    return {
        "port": name, "card": "card0", "sysfs_dir": "", "edid_path": "", "status": status, "has_edid": False,
        "rel_fw": rel, "fw_path": str(root / "firmware" / rel), "active_override": False,
    }


class Env:
    """A CRU window factory whose profile folders, config and ports all live inside ``tmp_path``."""

    def __init__(self, cru, root, monkeypatch):
        self.cru, self.root, self.monkeypatch = cru, root, monkeypatch
        self.docs = root / "home" / "Documents" / "linux-cru"
        self.legacy = root / "home" / ".config" / "linux-cru" / "profiles"
        self.ports = [make_port(root, "DP-1"), make_port(root, "VGA-1", "disconnected")]
        self.windows = []

    def window(self):
        win = self.cru.LinuxCRUWindow()
        self.windows.append(win)
        return win


@pytest.fixture
def env(cru, app, tmp_path, monkeypatch):
    e = Env(cru, tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cru, "DOCS_PROFILES_DIR", str(e.docs))
    monkeypatch.setattr(cru, "LEGACY_PROFILES_DIR", str(e.legacy))
    monkeypatch.setattr(cru, "CONFIG_DIR", str(tmp_path / "home" / ".config" / "linux-cru"))
    monkeypatch.setattr(cru, "CONFIG_FILE", str(tmp_path / "home" / ".config" / "linux-cru" / "config.json"))
    monkeypatch.setattr(cru, "scan_drm_ports", lambda: e.ports)
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(cru.QMessageBox, name, staticmethod(lambda *a, **_k: None))
    no = cru.QMessageBox.StandardButton.No
    monkeypatch.setattr(cru.QMessageBox, "question", staticmethod(lambda *a, **_k: no))
    yield e
    for win in e.windows:
        win.close()


def dtd(cru, width=1280, height=1024, hz=85.0, interlaced=False):
    return cru.calculate_timings("CVT Standard", width, height, hz, interlaced)


def stub_dialog(e, name, result):
    """Replace a modal dialog class so ``exec()`` accepts at once and returns ``result``."""

    class Fake:
        def __init__(self, *_args):
            pass

        def exec(self):
            return e.cru.QDialog.DialogCode.Accepted

        def get_result(self):
            return dict(result)

    e.monkeypatch.setattr(e.cru, name, Fake)


def profile_with_dtd(e, name="mine.bin", **kw):
    b = e.cru.create_blank_crt_edid("VGA-1")
    b[54:72] = e.cru.encode_dtd(dtd(e.cru, **kw))
    e.cru.update_checksum(b)
    e.docs.mkdir(parents=True, exist_ok=True)
    path = e.docs / name
    path.write_bytes(bytes(b))
    return path


def select_profile(win, path):
    for i, (kind, src) in enumerate(win.profile_sources):
        if kind == "file" and os.path.realpath(src) == os.path.realpath(path):
            win.profile_combo.setCurrentIndex(i)
            win.on_profile_selected(i)
            return
    raise AssertionError(f"{path} is not offered as a profile: {win.profile_sources}")


@pytest.fixture
def loaded(env):
    """(env, window, path) with the user's own Documents profile loaded."""
    path = profile_with_dtd(env)
    win = env.window()
    select_profile(win, path)
    return env, win, path


@pytest.mark.parametrize("port", ["VGA-1", "DVI-I-1", "DP-1", "DP-3", "HDMI-A-1", "eDP-1", "DVI-D-1"])
def test_blank_edid_input_byte_matches_the_port_type(cru, port):
    b = cru.create_blank_crt_edid(port)
    assert b[20] == input_byte("auto", port)
    assert (b[19] == 4) == (b[20] != 0x0E), "digital ports are EDID 1.4"
    assert sum(b[:128]) % 256 == 0


def test_blank_edid_defaults_to_analog(cru):
    assert cru.create_blank_crt_edid()[20] == 0x0E


def test_editing_a_dtd_saves_it_to_the_loaded_documents_profile(loaded):
    e, win, path = loaded
    stub_dialog(e, "DTDEditorDialog", dtd(e.cru, 1600, 1200, 85.0))
    win.table.selectRow(1)
    win.edit_selected_dtd()
    on_disk = path.read_bytes()
    assert on_disk[72:90] == bytes(win.edid_bytes[72:90])
    assert e.cru.decode_dtd(on_disk[72:90], on_disk)["hactive"] == 1600
    assert sum(on_disk[:128]) % 256 == 0
    assert win.current_path == str(path)


def test_the_loaded_profile_stays_selected_in_the_dropdown(loaded):
    e, win, path = loaded
    stub_dialog(e, "DTDEditorDialog", dtd(e.cru, 1600, 1200))
    win.edit_selected_dtd()
    kind, src = win.profile_sources[win.profile_combo.currentIndex()]
    assert kind == "file"
    assert os.path.realpath(src) == os.path.realpath(path)


def test_clearing_a_slot_saves_and_keeps_it_empty(loaded):
    _, win, path = loaded
    win.table.selectRow(3)
    win.clear_selected_dtd()
    empty = bytes([0, 0, 0, 0x10, 0] + [0] * 13)
    assert bytes(win.edid_bytes[108:126]) == empty
    assert path.read_bytes()[108:126] == empty


def test_a_slot_the_user_cleared_is_not_refilled_by_saving(loaded):
    """Slot 4 is user data: nothing may silently replace it with a range-limits descriptor."""
    e, win, path = loaded
    win.table.selectRow(3)
    win.clear_selected_dtd()
    empty = bytes([0, 0, 0, 0x10, 0] + [0] * 13)
    win._prepare_edid_for_save()
    assert bytes(win.edid_bytes[108:126]) == empty
    win.table.selectRow(1)
    stub_dialog(e, "DTDEditorDialog", dtd(e.cru, 1600, 1200))
    win.edit_selected_dtd()
    assert path.read_bytes()[108:126] == empty


def test_a_blank_profile_keeps_its_range_limits_descriptor(cru):
    b = cru.create_blank_crt_edid("VGA-1")
    assert bytes(b[108:112]) == b"\x00\x00\x00\xfd"
    assert b[117] >= 70, "max pixel clock (x10 MHz) allows 700 MHz"


def test_a_clock_over_655_mhz_is_saved_and_reloaded_exactly(loaded):
    """The real clock lives in the DisplayID extension; saving and reloading must not clamp it to 655.35."""
    e, win, path = loaded
    fast = dtd(e.cru, 3840, 2160, 144.0)
    assert fast["pclk_mhz"] > 655.35
    stub_dialog(e, "DTDEditorDialog", fast)
    win.table.selectRow(1)
    win.edit_selected_dtd()
    on_disk = path.read_bytes()
    assert len(on_disk) == 256 and on_disk[128] == 0x70
    assert e.cru.decode_dtd(on_disk[72:90], on_disk)["pclk_mhz"] == pytest.approx(fast["pclk_mhz"], abs=0.011)
    again = e.window()
    select_profile(again, path)
    assert again.table.item(1, 4).text() == f"{fast['pclk_mhz']:.2f} MHz"


def test_clear_all_saves(loaded):
    e, win, path = loaded
    win.clear_all_dtds()
    for off in e.cru.DTD_OFFSETS:
        assert path.read_bytes()[off:off + 2] == b"\x00\x00"


def test_standard_resolution_changes_are_saved(loaded):
    e, win, path = loaded
    res = {"w": 1280, "h": 960, "hz": 75, "ar_idx": 1, "ar_name": "4:3", "custom_h": False}
    stub_dialog(e, "StandardResDialog", res)
    win.add_std_res()
    assert e.cru.decode_std_timings(path.read_bytes())[0]["w"] == 1280
    win.std_list.setCurrentRow(0)
    win.del_std_res()
    assert e.cru.decode_std_timings(path.read_bytes()) == [None] * 8
    win.add_std_res()
    win.del_all_std_res()
    assert e.cru.decode_std_timings(path.read_bytes()) == [None] * 8


def test_editing_a_blank_creates_one_profile_for_the_port_and_keeps_reusing_it(env):
    win = env.window()
    win.new_blank_edid()
    stub_dialog(env, "DTDEditorDialog", dtd(env.cru))
    win.edit_selected_dtd()
    win.edit_selected_dtd()
    assert sorted(p.name for p in env.docs.glob("*.bin")) == ["DP-1.bin"]
    assert (env.docs / "DP-1.bin").read_bytes()[20] == 0xA5, "a DisplayPort blank is a digital EDID"
    assert win.current_path == str(env.docs / "DP-1.bin")


def test_an_edit_never_overwrites_an_unrelated_profile_with_the_same_name(env):
    env.docs.mkdir(parents=True)
    precious = bytes(env.cru.create_blank_crt_edid("DP-1"))
    (env.docs / "DP-1.bin").write_bytes(precious)
    win = env.window()
    win.new_blank_edid()
    stub_dialog(env, "DTDEditorDialog", dtd(env.cru))
    win.edit_selected_dtd()
    assert (env.docs / "DP-1.bin").read_bytes() == precious
    assert (env.docs / "DP-1-2.bin").is_file()
    assert win.current_path == str(env.docs / "DP-1-2.bin")


def test_an_edit_on_the_installed_firmware_file_never_writes_to_it(env):
    installed = Path(env.ports[0]["fw_path"])
    installed.parent.mkdir(parents=True)
    original = bytes(env.cru.create_blank_crt_edid("DP-1"))
    installed.write_bytes(original)
    win = env.window()
    assert win.profile_sources[0] == ("file", str(installed))
    stub_dialog(env, "DTDEditorDialog", dtd(env.cru))
    win.edit_selected_dtd()
    assert installed.read_bytes() == original
    assert (env.docs / "DP-1.bin").is_file()



def test_saving_under_the_installed_files_name_selects_the_new_profile_not_the_installed_one(env):
    installed = Path(env.ports[0]["fw_path"])
    installed.parent.mkdir(parents=True)
    installed.write_bytes(bytes(env.cru.create_blank_crt_edid("DP-1")))
    win = env.window()
    target = env.docs / "cru-dp-1.bin"
    env.monkeypatch.setattr(env.cru.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **_k: (str(target), "")))
    win.save_named_profile()
    _, src = win.profile_sources[win.profile_combo.currentIndex()]
    assert os.path.realpath(src) == os.path.realpath(target)
    assert os.path.realpath(src) != os.path.realpath(installed)


def test_a_failed_autosave_is_reported_and_does_not_raise(loaded):
    e, win, path = loaded
    stub_dialog(e, "DTDEditorDialog", dtd(e.cru, 1600, 1200))
    path.chmod(0o444)
    e.docs.chmod(0o555)
    try:
        if os.access(e.docs, os.W_OK):
            pytest.skip("running as a user that ignores directory permissions")
        win.edit_selected_dtd()
    finally:
        e.docs.chmod(0o755)
        path.chmod(0o644)
    assert "NOT saved" in win.path_label.text()


def test_range_limits_and_monitor_names_are_not_shown_as_empty(env):
    win = env.window()
    win.new_blank_edid()
    assert "Range" in win.table.item(3, 1).text()
    win.edid_bytes[72:90] = bytes([0, 0, 0, 0xFC, 0]) + b"CRT Test\n    "
    win.refresh_ui()
    assert "CRT Test" in win.table.item(1, 1).text()
    assert win.table.item(0, 1).text() == "(Empty)"


def test_disconnected_and_unlisted_ports_can_be_selected(env):
    win = env.window()
    model = win.port_combo.model()
    ports = {}
    for i in range(win.port_combo.count()):
        data = win.port_combo.itemData(i)
        if isinstance(data, dict):
            ports[data["port"]] = i
            assert model.item(i).isEnabled(), f"{data['port']} cannot be chosen"
    assert {"DP-1", "VGA-1", "HDMI-A-1"} <= set(ports)
    assert win.port_combo.currentData()["port"] == "DP-1", "a connected port is still the default"
    win.port_combo.setCurrentIndex(ports["HDMI-A-1"])
    assert win.current_port_info["port"] == "HDMI-A-1"


def test_importing_a_profile_with_the_same_name_keeps_both(env, tmp_path):
    cru = env.cru
    env.docs.mkdir(parents=True)
    mine = bytes(cru.create_blank_crt_edid("VGA-1"))
    (env.docs / "crt.bin").write_bytes(mine)
    other = bytearray(mine)
    other[54:72] = cru.encode_dtd(dtd(cru, 1024, 768, 100.0))
    cru.update_checksum(other)
    elsewhere = tmp_path / "usb" / "crt.bin"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(bytes(other))
    win = env.window()
    env.monkeypatch.setattr(cru.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **_k: (str(elsewhere), "")))
    win.open_bin()
    assert (env.docs / "crt.bin").read_bytes() == mine
    assert win.current_path == str(env.docs / "crt-2.bin")
    assert (env.docs / "crt-2.bin").read_bytes() == bytes(win.edid_bytes)


def test_stale_documents_copy_is_refreshed_from_a_newer_source_only(env):
    env.docs.mkdir(parents=True)
    env.legacy.mkdir(parents=True)
    old, new = bytes(env.cru.create_blank_crt_edid("DP-1")), bytes(env.cru.create_blank_crt_edid("VGA-1"))
    stale, fresh = env.docs / "stale.bin", env.docs / "fresh.bin"
    stale.write_bytes(old)
    fresh.write_bytes(new)
    (env.legacy / "stale.bin").write_bytes(new)
    (env.legacy / "fresh.bin").write_bytes(old)
    os.utime(stale, (1_000, 1_000))
    os.utime(env.legacy / "stale.bin", (2_000, 2_000))
    os.utime(fresh, (3_000, 3_000))
    os.utime(env.legacy / "fresh.bin", (2_000, 2_000))
    env.window()
    assert stale.read_bytes() == new, "an older copy is refreshed from the newer source"
    assert fresh.read_bytes() == new, "a copy edited since is never overwritten by an older source"

