#!/usr/bin/env python3
"""
Version-independent RDNA DCN & DP/HDMI DAC interlace unlock patcher (Linux 6.1 - 7.3+).

Previously a heredoc inside ``fix-interlaced-kernel.sh`` (unreachable by ruff/pytest). Each
``unlock_*`` function is a pure ``str -> str`` transform of a kernel C source file, so tests feed
mock C snippets. ``apply(tree, dry_run)`` patches a kernel source tree; with ``dry_run`` it only
reports which files would change.

Usage: interlace_rdna_patch.py [--dry-run] [KERNEL_SRC_DIR]   (default: current directory)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

INTERLEAVE = "pipe_ctx->plane_res.scl_data.lb_params.interleave_en"


def unlock_dongle_caps(txt: str) -> str:
    """Unlock DP/HDMI active & passive dongle caps (link_validation.c or dc_link.c)."""
    txt = re.sub(
        r"if\s*\(\s*get_tmds_output_pixel_clock_100hz\s*\(\s*timing\s*\)\s*>\s*\(\s*dongle_caps->dp_hdmi_max_pixel_clk_in_khz\s*\*\s*10\s*\)\s*\)\s*return\s+false\s*;",
        "(void)get_tmds_output_pixel_clock_100hz(timing);",
        txt,
    )
    for field in ("max_pixel_rate_in_mps", "max_video_h_active_width", "max_video_v_active_height"):
        txt = re.sub(rf"if\s*\(\s*dongle_caps->dfp_cap_ext\.{field}\s*<[^;]+?\)\s*return\s+false\s*;", "", txt)
    txt = re.sub(
        r"if\s*\(\s*max_pix_clk\s*!=\s*0\s*&&\s*get_tmds_output_pixel_clock_100hz\s*\(\s*timing\s*\)\s*>\s*max_pix_clk\s*\)\s*return\s+DC_EXCEED_DONGLE_CAP\s*;",
        "(void)max_pix_clk;",
        txt,
    )
    return re.sub(
        r"if\s*\(\s*!dp_active_dongle_validate_timing\s*\(\s*timing\s*,\s*dpcd_caps\s*\)\s*\)\s*return\s+DC_EXCEED_DONGLE_CAP\s*;",
        "(void)dp_active_dongle_validate_timing(timing, dpcd_caps);",
        txt,
    )


def unlock_dcn10_link_enc(txt: str) -> str:
    """Unlock 15kHz low-dotclock (<25 MHz) and high-clock (>165 MHz) HDMI/DVI validation."""
    txt = txt.replace(
        "max_pixel_clock = enc10->base.features.max_hdmi_pixel_clock;",
        "max_pixel_clock = max_t(uint32_t, enc10->base.features.max_hdmi_pixel_clock, 600000U);",
    )
    txt = re.sub(
        r"if\s*\(\s*\(\s*connector_signal\s*==\s*SIGNAL_TYPE_DVI_SINGLE_LINK[\s\S]*?crtc_timing->pix_clk_100hz\s*>\s*\(\s*TMDS_MAX_PIXEL_CLOCK\s*\*\s*10\s*\)\s*\)\s*return\s+false\s*;",
        "", txt,
    )
    txt = re.sub(
        r"if\s*\(\s*crtc_timing->pix_clk_100hz\s*<\s*\(\s*TMDS_MIN_PIXEL_CLOCK\s*\*\s*10\s*\)\s*\)\s*return\s+false\s*;",
        "", txt,
    )
    txt = re.sub(
        r"if\s*\(\s*edid_caps->max_tmds_clk_mhz\s*!=\s*0\s*&&\s*(?:adjusted_)?pix_clk_100hz\s*>\s*edid_caps->max_tmds_clk_mhz\s*\*\s*10000\s*\)\s*return\s+false\s*;",
        "(void)edid_caps;", txt,
    )
    txt = re.sub(
        r"if\s*\(\s*(?:adjusted_)?pix_clk_100hz\s*<\s*\(\s*TMDS_MIN_PIXEL_CLOCK\s*\*\s*10\s*\)\s*\)\s*return\s+false\s*;",
        "", txt,
    )
    return re.sub(
        r"if\s*\(\s*(\(?\s*(?:adjusted_)?pix_clk_100hz\s*==\s*0\s*\)?\s*\|\|\s*\(?\s*)?((?:adjusted_)?pix_clk_100hz)\s*>\s*\(\s*enc10->base\.features\.max_hdmi_pixel_clock\s*\*\s*10\s*\)",
        r"if (\1\2 > (max_t(uint32_t, enc10->base.features.max_hdmi_pixel_clock, 600000U) * 10)",
        txt,
    )


def unlock_dm_connector(txt: str) -> str:
    """Allow max_tmds_clock == 0 and preserve the INTERLACE flag when old_stream != NULL."""
    txt = txt.replace(
        "if (normalized_clk <= info->max_tmds_clock) {",
        "if (!info->max_tmds_clock || normalized_clk <= info->max_tmds_clock) {",
    )
    old_pol = "timing_out->flags.VSYNC_POSITIVE_POLARITY = old_stream->timing.flags.VSYNC_POSITIVE_POLARITY;"
    new_pol = old_pol + "\n\t\tif (mode_in->flags & DRM_MODE_FLAG_INTERLACE)\n\t\t\ttiming_out->flags.INTERLACE = 1;"
    if old_pol in txt and new_pol not in txt:
        txt = txt.replace(old_pol, new_pol, 1)
    return txt


def _add_after(txt: str, target: str, addition: str) -> str:
    return re.sub(re.escape(target) + r"(?!\s*" + re.escape(INTERLEAVE) + ")", lambda _m: addition, txt)


def unlock_dc_resource(txt: str) -> str:
    """Set lb_params.interleave_en in resource_build_scaling_params (dc_resource.c)."""
    target = "pipe_ctx->plane_res.scl_data.lb_params.alpha_en = plane_state->per_pixel_alpha;"
    return _add_after(txt, target, target + f"\n\t\t{INTERLEAVE} = timing->flags.INTERLACE ? 1 : 0;")


def unlock_dcn401_hwseq(txt: str) -> str:
    """Set lb_params.interleave_en in dcn401_hwseq.c (Linux 6.11+)."""
    target = "pipe_ctx->plane_res.scl_data.lb_params.alpha_en = pipe_ctx->plane_state->per_pixel_alpha;"
    return _add_after(txt, target, target + f"\n\t\t{INTERLEAVE} = pipe_ctx->stream->timing.flags.INTERLACE ? 1 : 0;")


def unlock_dcn10_optc(txt: str) -> str:
    """Align v_sync_width to even values in apply_front_porch_workaround (dcn10_optc.c)."""
    target = "timing->v_total = (timing->v_total + 1) & ~1;"
    line = "timing->v_sync_width = (timing->v_sync_width + 1) & ~1;"
    if target in txt and line not in txt:
        txt = txt.replace(target, target + "\n\t\t" + line, 1)
    return txt


def unlock_dcn10_dscl(txt: str) -> str:
    """Program SCL_VERT_FILTER_INIT even in 444 bypass mode when interlaced (dcn10_dpp_dscl.c)."""
    target = "dpp1_dscl_set_lb(dpp, &scl_data->lb_params, lb_config);"
    addition = target + "\n\n\tif (scl_data->lb_params.interleave_en)\n\t\tdpp1_dscl_set_manual_ratio_init(dpp, scl_data);"
    if target in txt and "if (scl_data->lb_params.interleave_en)" not in txt:
        txt = txt.replace(target, addition, 1)
    return txt


DC = "drivers/gpu/drm/amd/display/dc"
DM = "drivers/gpu/drm/amd/display/amdgpu_dm"
PATCHES: tuple[tuple[str, Callable[[str], str]], ...] = (
    (f"{DC}/link/link_validation.c", unlock_dongle_caps),
    (f"{DC}/core/dc_link.c", unlock_dongle_caps),
    (f"{DC}/dio/dcn10/dcn10_link_encoder.c", unlock_dcn10_link_enc),
    (f"{DM}/amdgpu_dm_connector.c", unlock_dm_connector),
    (f"{DM}/amdgpu_dm.c", unlock_dm_connector),
    (f"{DC}/core/dc_resource.c", unlock_dc_resource),
    (f"{DC}/hwss/dcn401/dcn401_hwseq.c", unlock_dcn401_hwseq),
    (f"{DC}/optc/dcn10/dcn10_optc.c", unlock_dcn10_optc),
    (f"{DC}/dpp/dcn10/dcn10_dpp_dscl.c", unlock_dcn10_dscl),
)


def apply(tree: Path, dry_run: bool = False, say: Callable[[str], None] = print) -> list[str]:
    """Patch the files under ``tree``. Returns the relative paths that changed (or would change)."""
    changed: list[str] = []
    for rel, transform in PATCHES:
        path = tree / rel
        if not path.exists():
            continue
        orig = path.read_text(encoding="utf-8", errors="ignore")
        updated = transform(orig)
        if updated == orig:
            continue
        changed.append(rel)
        if dry_run:
            say(f"[dry-run] would patch {rel}")
        else:
            path.write_text(updated, encoding="utf-8")
            say(f"  -> [RDNA/DAC Unlock] Patched {rel}")
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RDNA DCN & DP/HDMI DAC interlace unlock patcher")
    p.add_argument("tree", nargs="?", default=".", help="kernel source directory (default: .)")
    p.add_argument("--dry-run", action="store_true", help="report which files would change; write nothing")
    args = p.parse_args(argv)
    apply(Path(args.tree), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

