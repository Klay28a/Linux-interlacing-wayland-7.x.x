"""RDNA kernel-source transforms against mock C snippets (no kernel tree needed)."""

from pathlib import Path

import interlace_rdna_patch as rp


def test_dongle_caps_checks_are_neutralised():
    src = (
        "if (get_tmds_output_pixel_clock_100hz(timing) > (dongle_caps->dp_hdmi_max_pixel_clk_in_khz * 10))\n"
        "    return false;\n"
        "if (dongle_caps->dfp_cap_ext.max_video_h_active_width < timing->h_addressable)\n    return false;\n"
        "if (max_pix_clk != 0 && get_tmds_output_pixel_clock_100hz(timing) > max_pix_clk)\n"
        "    return DC_EXCEED_DONGLE_CAP;\n"
        "if (!dp_active_dongle_validate_timing(timing, dpcd_caps))\n    return DC_EXCEED_DONGLE_CAP;\n"
    )
    out = rp.unlock_dongle_caps(src)
    assert "return false" not in out
    assert "DC_EXCEED_DONGLE_CAP" not in out
    assert "(void)get_tmds_output_pixel_clock_100hz(timing);" in out
    assert "(void)dp_active_dongle_validate_timing(timing, dpcd_caps);" in out


def test_link_encoder_lifts_hdmi_clock_cap_and_min_clock():
    src = (
        "max_pixel_clock = enc10->base.features.max_hdmi_pixel_clock;\n"
        "if (crtc_timing->pix_clk_100hz < (TMDS_MIN_PIXEL_CLOCK * 10))\n    return false;\n"
    )
    out = rp.unlock_dcn10_link_enc(src)
    assert "600000U" in out
    assert "TMDS_MIN_PIXEL_CLOCK" not in out


def test_dm_connector_is_idempotent():
    src = (
        "if (normalized_clk <= info->max_tmds_clock) {\n"
        "timing_out->flags.VSYNC_POSITIVE_POLARITY = old_stream->timing.flags.VSYNC_POSITIVE_POLARITY;\n"
    )
    once = rp.unlock_dm_connector(src)
    assert "!info->max_tmds_clock ||" in once
    assert "timing_out->flags.INTERLACE = 1;" in once
    assert rp.unlock_dm_connector(once) == once


def test_interleave_en_added_once():
    src = "pipe_ctx->plane_res.scl_data.lb_params.alpha_en = plane_state->per_pixel_alpha;\n"
    once = rp.unlock_dc_resource(src)
    assert "interleave_en = timing->flags.INTERLACE ? 1 : 0;" in once
    assert rp.unlock_dc_resource(once) == once


def test_optc_and_dscl_idempotent():
    optc = "timing->v_total = (timing->v_total + 1) & ~1;\n"
    line = "timing->v_sync_width = (timing->v_sync_width + 1) & ~1;"
    assert rp.unlock_dcn10_optc(rp.unlock_dcn10_optc(optc)).count(line) == 1
    dscl = "dpp1_dscl_set_lb(dpp, &scl_data->lb_params, lb_config);\n"
    assert rp.unlock_dcn10_dscl(rp.unlock_dcn10_dscl(dscl)).count("set_manual_ratio_init") == 1


def _tree(tmp_path: Path) -> Path:
    f = tmp_path / rp.PATCHES[5][0]  # dc_resource.c
    f.parent.mkdir(parents=True)
    f.write_text("pipe_ctx->plane_res.scl_data.lb_params.alpha_en = plane_state->per_pixel_alpha;\n")
    return tmp_path


def test_apply_dry_run_reports_but_does_not_write(tmp_path: Path):
    tree = _tree(tmp_path)
    before = (tree / rp.PATCHES[5][0]).read_text()
    msgs: list[str] = []
    assert rp.apply(tree, dry_run=True, say=msgs.append) == [rp.PATCHES[5][0]]
    assert (tree / rp.PATCHES[5][0]).read_text() == before
    assert msgs == [f"[dry-run] would patch {rp.PATCHES[5][0]}"]


def test_apply_writes_and_missing_files_are_skipped(tmp_path: Path):
    tree = _tree(tmp_path)
    assert rp.apply(tree, say=lambda _m: None) == [rp.PATCHES[5][0]]
    assert "interleave_en" in (tree / rp.PATCHES[5][0]).read_text()
    assert rp.apply(tree, say=lambda _m: None) == []  # second run changes nothing
