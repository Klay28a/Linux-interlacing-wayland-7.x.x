"""GPU / connector discovery and EDID patching against mock inputs."""

import pytest

from conftest import LSPCI_GCN_ONLY, LSPCI_NV_AMD, LSPCI_RDNA_ONLY, add_connector
from interlace_edid import EDID_HEADER, default_crt_edid, patch_edid
from interlace_gpu import (
    Connector,
    edid_file_name,
    list_connectors,
    parse_lspci,
    pick_connector,
    resolve_adapter,
    resolve_gpu_profile,
)


def test_parse_lspci_filters_non_display_and_lowercases_ids():
    gpus = parse_lspci(LSPCI_NV_AMD)
    assert [(g.vendor, g.devid) for g in gpus] == [("10de", "2484"), ("1002", "6610")]
    assert gpus[0].pci == "0000:01:00.0"


@pytest.mark.parametrize(
    ("lspci", "connectors", "expected"),
    [
        (LSPCI_NV_AMD, ["VGA-1"], "dual-nvidia-amd"),
        (LSPCI_RDNA_ONLY, ["DP-1"], "rdna-single"),
        (LSPCI_GCN_ONLY, ["VGA-1", "HDMI-A-1"], "gcn-single"),
        (LSPCI_GCN_ONLY, ["DP-1"], "rdna-single"),  # no analog connector -> digital path
        ("0000:01:00.0 VGA compatible controller [0300]: NVIDIA [10de:2484]\n", ["DP-1"], "nvidia-single"),
        (
            "0000:03:00.0 VGA [0300]: AMD [1002:73df]\n0000:06:00.0 VGA [0300]: AMD [1002:6610]\n",
            ["DP-1"], "dual-amd-amd",
        ),
    ],
)
def test_auto_profile_resolution(lspci, connectors, expected):
    assert resolve_gpu_profile("auto", parse_lspci(lspci), connectors) == expected


def test_explicit_profile_is_not_overridden():
    assert resolve_gpu_profile("gcn-single", parse_lspci(LSPCI_RDNA_ONLY), ["DP-1"]) == "gcn-single"


def test_list_connectors_reads_mock_drm_tree(sandbox):
    root, paths = sandbox
    add_connector(root, "DP-1", "disconnected")
    add_connector(root, "HDMI-A-1", "connected", card="card1")
    (paths.drm_class / "card0").mkdir()  # not a connector, no status file
    assert list_connectors(paths.drm_class) == [Connector("DP-1", "disconnected"), Connector("HDMI-A-1", "connected")]


def test_pick_connector_prefers_connected_then_any_then_none():
    conns = [Connector("DP-1", "disconnected"), Connector("HDMI-A-1", "connected")]
    assert pick_connector("dp-dac", "rdna-single", conns) == "HDMI-A-1"
    assert pick_connector("dp-dac", "rdna-single", [Connector("DP-2", "disconnected")]) == "DP-2"
    assert pick_connector("analog-native", "gcn-single", conns) is None  # never guesses VGA-1


def test_adapter_and_names():
    assert resolve_adapter("auto", "DP-2") == "dp-dac"
    assert resolve_adapter("auto", "HDMI-A-1") == "hdmi-dac"
    assert resolve_adapter("auto", "VGA-1") == "analog-native"
    assert resolve_adapter("hdmi-dac", "DP-1") == "hdmi-dac"
    assert edid_file_name("VGA-1") == "crufile.bin"
    assert edid_file_name("DP-2") == "cru-dp-2.bin"


def _checksum_ok(b: bytes) -> bool:
    return sum(b[:128]) % 256 == 0 and (len(b) < 256 or sum(b[128:256]) % 256 == 0)


def test_default_edid_is_valid_and_analog_for_vga():
    data, log = patch_edid(None, "analog-native", "gcn-single", "VGA-1")
    assert data[:8] == EDID_HEADER
    assert data[20] == 0x0E
    assert _checksum_ok(data)
    assert any("Generated default CRT EDID" in line for line in log)


def test_digital_adapter_sets_input_byte_for_dp_and_hdmi():
    dp, _ = patch_edid(None, "dp-dac", "rdna-single", "DP-1")
    hdmi, _ = patch_edid(None, "hdmi-dac", "rdna-single", "HDMI-A-1")
    assert (dp[19], dp[20]) == (4, 0xA5)
    assert hdmi[20] == 0xA2
    assert _checksum_ok(dp) and _checksum_ok(hdmi)


def test_half_field_interlaced_dtd_is_converted_to_full_frame():
    b = default_crt_edid()
    # 1280 active, 240 vactive (half field), flags interlaced
    b[54:72] = bytes([0x5C, 0x92, 0x00, 0xD0, 0x82, 0x00, 0x9C, 0x60, 0x88, 0xE0, 0x68, 0x00, 0x96, 0x31, 0x11, 0x00, 0x00, 0x9C])
    b[56], b[58] = 0x00, 0x50  # hactive low/high -> 1280
    b[59], b[61] = 0xF0, 0x00  # vactive 240
    b[71] = 0x80 | 0x18
    data, log = patch_edid(bytes(b), "analog-native", "gcn-single", "VGA-1", "mock.bin")
    vact = data[59] | ((data[61] & 0xF0) << 4)
    assert vact == 480
    assert any("full-frame" in line for line in log)
    assert _checksum_ok(data)


def test_invalid_header_raises():
    with pytest.raises(ValueError, match="Invalid EDID header"):
        patch_edid(bytes(128), "analog-native", "gcn-single", "VGA-1", "bad.bin")


def test_patch_is_deterministic():
    a, _ = patch_edid(None, "dp-dac", "rdna-single", "DP-1")
    b, _ = patch_edid(a, "dp-dac", "rdna-single", "DP-1")
    assert a == b
