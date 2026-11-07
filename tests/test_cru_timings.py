"""calculate_timings: every preset, progressive and interlaced, must give self-consistent, encodable timings."""

import pytest

from interlace_edid import adapter_from_edid

PRESETS = (
    "Automatic CRT", "Automatic PC", "Automatic HDTV", "Native PC", "Native HDTV", "Exact", "Exact CRT",
    "CVT Standard", "CVT-RB Standard", "CVT-RB2 Standard", "GTF Standard",
)
MODES = ((640, 480, 60.0), (1024, 768, 85.0), (1280, 1024, 75.0), (1600, 1200, 85.0), (1920, 1080, 60.0),
         (2048, 1536, 80.0), (3840, 2160, 60.0))
CASES = [(p, w, h, hz, il) for p in PRESETS for (w, h, hz) in MODES for il in (False, True)]


def ids(case):
    p, w, h, hz, il = case
    return f"{p}-{w}x{h}@{hz:g}{'i' if il else 'p'}"


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_timings_are_self_consistent(cru, case):
    preset, w, h, hz, il = case
    t = cru.calculate_timings(preset, w, h, hz, il)
    assert t["hactive"] == w
    assert t["htotal"] == t["hactive"] + t["hblank"]
    assert t["hblank"] == t["hfront"] + t["hsync"] + t["hback"]
    assert t["hfront"] >= 1 and t["hsync"] >= 1 and t["hback"] >= 1
    assert t["interlaced"] is il
    assert t["pclk_mhz"] > 0
    assert t["vblank_dec"] == pytest.approx(t["vfront_dec"] + t["vsync_dec"] + t["vback_dec"], abs=0.51)
    assert t["vtotal_dec"] == pytest.approx(t["vactive"] + t["vblank_dec"], abs=0.01)
    vtotal = t["vtotal_dec"]
    shown = t["pclk_mhz"] * 1e6 * (2 if il else 1) / (t["htotal"] * vtotal)
    assert shown == pytest.approx(t["vrefresh"], rel=0.002), "the reported refresh is the real one"


@pytest.mark.parametrize("case", [c for c in CASES if c[0] in ("CVT Standard", "CVT-RB Standard", "GTF Standard")], ids=ids)
def test_standards_hit_the_requested_refresh(cru, case):
    preset, w, h, hz, il = case
    t = cru.calculate_timings(preset, w, h, hz, il)
    assert t["vrefresh"] == pytest.approx(hz, rel=0.01)


@pytest.mark.parametrize("case", [c for c in CASES if c[0] == "CVT Standard" and not c[4]], ids=ids)
def test_a_dtd_survives_encode_and_decode(cru, case):
    """Clocks up to 655.35 MHz fit the 16-bit DTD field; above that the DisplayID test below applies."""
    preset, w, h, hz, il = case
    t = cru.calculate_timings(preset, w, h, hz, il)
    if t["pclk_mhz"] > 655.35:
        pytest.skip("needs a DisplayID extension: see test_a_clock_over_655_mhz_goes_into_a_displayid_extension")
    back = cru.decode_dtd(bytes(cru.encode_dtd(t)))
    assert (back["hactive"], back["hblank"], back["vactive"], back["interlaced"]) == (
        t["hactive"], t["hblank"], t["vactive"], il,
    )
    assert back["pclk_mhz"] == pytest.approx(t["pclk_mhz"], abs=0.011)
    assert back["hfront"] == t["hfront"]
    assert back["hsync"] == t["hsync"]


def test_a_clock_over_655_mhz_goes_into_a_displayid_extension(cru):
    t = cru.calculate_timings("CVT Standard", 3840, 2160, 144.0, False)
    assert t["pclk_mhz"] > 655.35
    b = cru.create_blank_crt_edid("DP-1")
    b[54:72] = cru.encode_dtd(t)
    assert cru.decode_dtd(bytes(b[54:72]))["pclk_mhz"] == 655.35, "the DTD field itself is clamped"
    cru.sync_700mhz_and_displayid(b, [t], True)
    assert len(b) == 256 and b[128] == 0x70
    back = cru.decode_dtd(bytes(b[54:72]), bytes(b))
    assert back["pclk_mhz"] == pytest.approx(t["pclk_mhz"], abs=0.011)
    assert sum(b[:128]) % 256 == 0 and sum(b[128:256]) % 256 == 0


@pytest.mark.parametrize(
    ("port", "adapter"),
    [("VGA-1", "analog-native"), ("DP-1", "dp-dac"), ("HDMI-A-1", "hdmi-dac"), ("DVI-I-1", "analog-native")],
)
def test_a_blank_edid_reads_back_as_the_adapter_it_was_made_for(cru, port, adapter):
    assert adapter_from_edid(bytes(cru.create_blank_crt_edid(port))) == adapter


def test_adapter_from_edid_handles_garbage():
    assert adapter_from_edid(b"") == "analog-native"
    assert adapter_from_edid(bytes(20)) == "analog-native"
