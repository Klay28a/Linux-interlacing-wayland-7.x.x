"""interlace_apply_edid: the tool Linux CRU's pkexec buttons call."""

from pathlib import Path

import pytest

import interlace_apply_edid
from conftest import add_connector, build_host
from interlace_edid import patch_edid


@pytest.fixture
def edid_file(tmp_path: Path) -> Path:
    data, _ = patch_edid(None, "dp-dac", "rdna-single", "DP-1")
    f = tmp_path / "in.bin"
    f.write_bytes(data)
    return f


def _host(sandbox, **kw):
    root, paths = sandbox
    add_connector(root, "DP-1", "connected")
    return build_host(root, paths, tools=("mkinitcpio",), **kw)


def test_live_only_installs_edid_unmodified_and_reprobes(sandbox, edid_file):
    _, paths = sandbox
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1"], host=host) == 0
    dest = str(paths.firmware_edid_dir / "cru-dp-1.bin")
    assert runner.installed[dest] == edid_file.read_bytes()  # NOT re-patched
    assert not any("mkinitcpio" in c for c in runner.executed)  # no boot work without --boot
    assert str(paths.default_grub) not in runner.installed


def test_boot_flag_updates_bootloader_and_initramfs(sandbox, edid_file):
    _, paths = sandbox
    paths.default_grub.parent.mkdir(parents=True)
    paths.default_grub.write_text('GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1", "--boot"], host=host) == 0
    written = runner.installed[str(paths.default_grub)].decode()
    assert "GRUB_TIMEOUT=5" in written
    assert "drm.edid_firmware=DP-1:edid/cru-dp-1.bin" in written
    assert ["sudo", "-n", "mkinitcpio", "-P"] in runner.executed


def test_apply_records_the_connector_in_the_suite_state(sandbox, edid_file):
    """Without this the suite's EDID badge never learns that Linux CRU installed something."""
    import json

    _, paths = sandbox
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1", "--boot"], host=host) == 0
    record = json.loads(runner.installed[str(paths.state_file)].decode())["connectors"]["DP-1"]
    assert record["edid_file"] == "edid/cru-dp-1.bin"
    assert record["adapter_mode"] == "dp-dac"
    assert record["live_only"] is False
    assert record["source_edid"] == str(edid_file)


def test_live_apply_is_recorded_as_live_only(sandbox, edid_file):
    import json

    _, paths = sandbox
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1"], host=host) == 0
    assert json.loads(runner.installed[str(paths.state_file)].decode())["connectors"]["DP-1"]["live_only"] is True


def test_apply_keeps_the_adapter_the_user_chose_in_the_suite(sandbox, edid_file):
    import json

    _, paths = sandbox
    paths.state_file.parent.mkdir(parents=True)
    paths.state_file.write_text(json.dumps({"adapter_mode": "dp-dac", "gpu_profile": "gcn-single", "connectors": {
        "VGA-1": {"edid_file": "edid/crufile.bin", "adapter_mode": "dp-dac"}}}))
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1"], host=host) == 0
    data = json.loads(runner.installed[str(paths.state_file)].decode())
    assert data["connectors"]["DP-1"]["adapter_mode"] == "dp-dac"
    assert "VGA-1" in data["connectors"], "other ports' records survive"


def test_debugfs_override_written_when_node_exists(sandbox, edid_file):
    _, paths = sandbox
    node = paths.debugfs_dri / "0" / "DP-1" / "edid_override"
    node.parent.mkdir(parents=True)
    node.write_text("")
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1"], host=host) == 0
    assert runner.installed[str(node)] == edid_file.read_bytes()


def test_dry_run_changes_nothing(sandbox, edid_file):
    host, runner = _host(sandbox, dry_run=True)
    assert interlace_apply_edid.main([str(edid_file), "--connector", "DP-1", "--boot", "--dry-run"], host=host) == 0
    assert runner.mutating == []
    assert any("[dry-run] would install" in m for m in runner.messages)


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["--connector", "DP-1; rm -rf /"], "Invalid connector"),
        (["--connector", "DP-1", "--rel-fw", "../../etc/passwd"], "Invalid firmware name"),
    ],
)
def test_rejects_unsafe_names(sandbox, edid_file, capsys, args, needle):
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(edid_file), *args], host=host) == 2
    assert needle in capsys.readouterr().err
    assert runner.mutating == []


def test_rejects_invalid_edid(sandbox, tmp_path, capsys):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(128))
    host, runner = _host(sandbox)
    assert interlace_apply_edid.main([str(bad), "--connector", "DP-1"], host=host) == 2
    assert "not a valid EDID" in capsys.readouterr().err
    assert runner.mutating == []


def test_missing_file_is_reported(sandbox, tmp_path, capsys):
    host, _ = _host(sandbox)
    assert interlace_apply_edid.main([str(tmp_path / "nope.bin"), "--connector", "DP-1"], host=host) == 2
    assert "Cannot read EDID" in capsys.readouterr().err
