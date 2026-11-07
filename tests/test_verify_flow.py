"""Badges follow the CURRENT selection: change a dropdown -> not applied; run the script -> applied."""

import json

from interlace_gpu import edid_file_name
from interlace_selection import Selection
from machine import Machine


def test_nothing_is_verified_on_a_fresh_machine(pc, tmp_path):
    m = Machine(pc, tmp_path)
    _, ver, _ = m.look(Selection())
    assert not ver.edid.ok
    assert not ver.kernel.ok
    assert {"EDID", "Kernel"} <= set(ver.pending)


def test_running_setup_turns_the_edid_badge_green(pc, tmp_path):
    m = Machine(pc, tmp_path)
    sel = Selection()
    m.run_setup(sel)
    res, ver, _ = m.look(sel)
    assert ver.edid.ok, ver.edid
    assert ver.edid.short == res.connector


def test_changing_the_adapter_dropdown_flips_edid_back_until_reapplied(pc, tmp_path):
    m = Machine(pc, tmp_path)
    m.run_setup(Selection())
    other = "hdmi-dac" if pc["expected"]["adapter"] != "hdmi-dac" else "dp-dac"
    changed = Selection(adapter_mode=other)
    assert not m.look(changed)[1].edid.ok, "an adapter that was never applied must not read as verified"
    m.run_setup(changed)
    assert m.look(changed)[1].edid.ok


def test_changing_the_gpu_profile_flips_edid_and_rules_until_reapplied(pc, tmp_path):
    m = Machine(pc, tmp_path)
    m.run_setup(Selection())
    m.apply_rules(Selection())
    assert m.look(Selection())[1].rules.ok
    other = "gcn-single" if pc["expected"]["gpu_profile"] != "gcn-single" else "rdna-single"
    changed = Selection(gpu_profile=other)
    _, ver, _ = m.look(changed)
    assert not ver.rules.ok
    assert not ver.edid.ok
    m.run_setup(changed)
    m.apply_rules(changed)
    _, ver, _ = m.look(changed)
    assert ver.rules.ok
    assert ver.edid.ok


def test_changing_the_port_needs_its_own_edid_and_leaves_the_first_one_intact(pc, tmp_path):
    m = Machine(pc, tmp_path)
    first = Selection()
    m.run_setup(first)
    other = Selection(connector="HDMI-A-2" if pc["expected"]["connector"] != "HDMI-A-2" else "DP-2")
    assert not m.look(other)[1].edid.ok
    m.run_setup(other)
    assert m.look(other)[1].edid.ok
    state = json.loads(m.paths.state_file.read_text())["connectors"]
    assert {pc["expected"]["connector"], other.connector} <= set(state), "both ports are recorded"


def test_a_wrong_edid_header_byte_is_caught(pc, tmp_path):
    m = Machine(pc, tmp_path)
    sel = Selection()
    m.run_setup(sel)
    res, _, _ = m.look(sel)
    edid = m.paths.firmware_edid_dir / edid_file_name(res.connector)
    data = bytearray(edid.read_bytes())
    data[20] = 0x00
    edid.write_bytes(bytes(data))
    check = m.look(sel)[1].edid
    assert not check.ok
    assert check.short == "Wrong adapter"


def test_selecting_a_custom_edid_is_pending_until_installed(pc, tmp_path):
    m = Machine(pc, tmp_path)
    m.run_setup(Selection())
    custom = tmp_path / "mine.bin"
    custom.write_bytes(b"\x00" * 256)
    assert m.look(Selection(custom_edid=str(custom)))[1].edid.short == "Custom EDID pending"


def test_the_state_file_records_what_was_applied(pc, tmp_path):
    m = Machine(pc, tmp_path)
    m.run_setup(Selection())
    exp = pc["expected"]
    record = json.loads(m.paths.state_file.read_text())["connectors"][exp["connector"]]
    assert (record["gpu_profile"], record["adapter_mode"]) == (exp["gpu_profile"], exp["adapter"])
