"""The CRU 'Detailed Resolution' dialog in Manual mode: real key events, ToastyX radio semantics.

ToastyX says the radio buttons show that only one field is needed to calculate the other two, so the selected
radio is the input and the other two fields of its group are calculated (and greyed out).
"""

import pytest

from gui_fixtures import click_radio, type_into


def test_typing_a_multi_digit_total_is_not_clamped_mid_keystroke(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.htotal_sb, "2200")
    assert dlg.htotal_sb.value() == 2200
    assert dlg.hblank_sb.value() == 2200 - dlg.hactive_sb.value()
    assert dlg.hback_sb.value() == dlg.hblank_sb.value() - dlg.hfront_sb.value() - dlg.hsync_sb.value()


def test_typing_a_multi_digit_back_porch_gives_exactly_that_value(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_back)
    type_into(app, dlg.hback_sb, "300")
    assert dlg.hback_sb.value() == 300
    assert dlg.hblank_sb.value() == dlg.hfront_sb.value() + dlg.hsync_sb.value() + 300
    assert dlg.htotal_sb.value() == dlg.hactive_sb.value() + dlg.hblank_sb.value()


def test_typing_blanking_gives_exactly_that_value(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_blank)
    type_into(app, dlg.hblank_sb, "640")
    assert dlg.hblank_sb.value() == 640
    assert dlg.htotal_sb.value() == dlg.hactive_sb.value() + 640


def test_vertical_total_can_be_typed_with_a_half_line(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.vtotal_sb, "1300.5")
    assert dlg.vtotal_sb.value() == 1300.5
    assert dlg.vblank_sb.value() == 1300.5 - dlg.vactive_sb.value()


def test_editing_a_field_never_flips_the_radio_buttons(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    click_radio(app, dlg.rb_rate_h)
    type_into(app, dlg.hfront_sb, "40")
    type_into(app, dlg.htotal_sb, "2300")
    type_into(app, dlg.hscan_sb, "100")
    assert dlg.rb_anchor_total.isChecked()
    assert dlg.rb_rate_h.isChecked()


def test_only_the_selected_radio_field_is_editable_in_each_group(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_blank)
    assert [w.isEnabled() for w in (dlg.hback_sb, dlg.hblank_sb, dlg.htotal_sb)] == [False, True, False]
    assert [w.isEnabled() for w in (dlg.vback_sb, dlg.vblank_sb, dlg.vtotal_sb)] == [False, True, False]
    # Refresh Rate is a real input whichever rate radio is selected; H-scan and pixel clock follow their radios.
    click_radio(app, dlg.rb_rate_v)
    assert [w.isEnabled() for w in (dlg.refresh_sb, dlg.hscan_sb, dlg.pclk_sb)] == [True, False, False]
    click_radio(app, dlg.rb_rate_h)
    assert [w.isEnabled() for w in (dlg.refresh_sb, dlg.hscan_sb, dlg.pclk_sb)] == [True, True, False]
    click_radio(app, dlg.rb_rate_pclk)
    assert [w.isEnabled() for w in (dlg.refresh_sb, dlg.hscan_sb, dlg.pclk_sb)] == [True, False, True]


def test_refresh_rate_can_be_typed_in_manual_whatever_radio_is_selected(app, make_dialog):
    """Refresh is never auto-locked: typing it makes it the input, and pixel clock follows."""
    dlg = make_dialog()
    assert dlg.rb_rate_pclk.isChecked() and dlg.refresh_sb.isEnabled()
    htot = dlg.hactive_sb.value() + dlg.hblank_sb.value()
    vtot = dlg.vactive_sb.value() + dlg.vblank_sb.value()
    type_into(app, dlg.refresh_sb, "90")
    assert dlg.refresh_sb.value() == 90.0, "the typed refresh rate is kept, not recalculated"
    assert dlg.rb_rate_v.isChecked()
    assert dlg.pclk_sb.value() == pytest.approx(90 * htot * vtot / 1e6, abs=0.01)
    assert not dlg.pclk_sb.isEnabled() and not dlg.hscan_sb.isEnabled()


def test_refresh_rate_stays_editable_in_every_preset_except_native(make_dialog):
    for preset in ("Manual", "Automatic CRT", "CVT Standard", "GTF Standard", "Exact"):
        assert make_dialog(preset=preset).refresh_sb.isEnabled(), preset
    assert not make_dialog(preset="Native PC").refresh_sb.isEnabled()


def test_pixel_clock_is_the_default_input_so_editing_a_dtd_never_re_rounds_it(app, make_dialog):
    dlg = make_dialog()
    assert dlg.rb_rate_pclk.isChecked()
    before = dlg.pclk_sb.value()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.htotal_sb, "2300")
    assert dlg.pclk_sb.value() == before


def test_refresh_input_recalculates_pixel_clock_and_hscan(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_rate_v)
    type_into(app, dlg.refresh_sb, "90")
    htot = dlg.hactive_sb.value() + dlg.hblank_sb.value()
    vtot = dlg.vactive_sb.value() + dlg.vblank_sb.value()
    assert dlg.pclk_sb.value() == pytest.approx(90 * htot * vtot / 1e6, abs=0.01)
    assert dlg.hscan_sb.value() == pytest.approx(dlg.pclk_sb.value() * 1000 / htot, abs=0.01)


def test_hscan_input_recalculates_pixel_clock(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_rate_h)
    type_into(app, dlg.hscan_sb, "100")
    htot = dlg.hactive_sb.value() + dlg.hblank_sb.value()
    assert dlg.pclk_sb.value() == pytest.approx(100 * htot / 1000, abs=0.01)


def test_pixel_clock_input_recalculates_refresh_and_hscan(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_rate_pclk)
    type_into(app, dlg.pclk_sb, "200")
    htot = dlg.hactive_sb.value() + dlg.hblank_sb.value()
    vtot = dlg.vactive_sb.value() + dlg.vblank_sb.value()
    assert dlg.pclk_sb.value() == 200.0
    assert dlg.refresh_sb.value() == pytest.approx(200e6 / (htot * vtot), abs=0.001)


def test_interlaced_refresh_counts_fields(app, make_dialog):
    dlg = make_dialog(width=1280, height=1024, hz=120.0, interlaced=True)
    click_radio(app, dlg.rb_rate_pclk)
    type_into(app, dlg.pclk_sb, "150")
    htot = dlg.hactive_sb.value() + dlg.hblank_sb.value()
    vtot = dlg.vactive_sb.value() + dlg.vblank_sb.value()
    assert dlg.refresh_sb.value() == pytest.approx(2 * 150e6 / (htot * vtot), abs=0.001)


def test_changing_active_size_keeps_the_selected_input_and_recomputes_the_rest(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_back)
    back = dlg.hback_sb.value()
    type_into(app, dlg.hactive_sb, "1280")
    assert dlg.hback_sb.value() == back
    assert dlg.htotal_sb.value() == 1280 + dlg.hfront_sb.value() + dlg.hsync_sb.value() + back


def test_porch_and_total_fields_step_by_one_pixel_in_manual(make_dialog):
    dlg = make_dialog()
    for sb in (dlg.hfront_sb, dlg.hsync_sb, dlg.hback_sb, dlg.hblank_sb, dlg.htotal_sb):
        assert sb.singleStep() == 1


def test_no_spinbox_updates_on_every_keystroke(make_dialog):
    dlg = make_dialog()
    boxes = (
        dlg.hactive_sb, dlg.vactive_sb, dlg.hfront_sb, dlg.hsync_sb, dlg.hback_sb, dlg.hblank_sb, dlg.htotal_sb,
        dlg.vfront_sb, dlg.vsync_sb, dlg.vback_sb, dlg.vblank_sb, dlg.vtotal_sb, dlg.refresh_sb, dlg.hscan_sb,
        dlg.pclk_sb,
    )
    assert [sb for sb in boxes if sb.keyboardTracking()] == []


def test_a_value_typed_but_not_yet_committed_is_used_when_saving(app, make_dialog):
    """Typing then pressing Save (no Tab/Enter) must not lose the typed number."""
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.htotal_sb, "2300", then_tab=False)
    dlg.ok_btn.click()
    assert dlg.result() == dlg.DialogCode.Accepted
    result = dlg.get_result()
    assert result["hactive"] + result["hblank"] == 2300


def test_presets_still_lock_every_derived_field(make_dialog):
    dlg = make_dialog(preset="CVT Standard")
    for sb in (dlg.hfront_sb, dlg.hback_sb, dlg.hblank_sb, dlg.htotal_sb, dlg.hscan_sb, dlg.pclk_sb):
        assert not sb.isEnabled()
    assert dlg.refresh_sb.isEnabled()


def test_switch_to_manual_keeps_values_and_unlocks_the_selected_inputs(make_dialog):
    dlg = make_dialog(preset="CVT Standard")
    before = (dlg.htotal_sb.value(), dlg.vtotal_sb.value(), dlg.pclk_sb.value())
    dlg.switch_to_manual_preserving_values()
    assert (dlg.htotal_sb.value(), dlg.vtotal_sb.value(), dlg.pclk_sb.value()) == before
    assert dlg.hback_sb.isEnabled() and not dlg.htotal_sb.isEnabled()
    assert dlg.pclk_sb.isEnabled() and dlg.refresh_sb.isEnabled()
    assert not dlg.hscan_sb.isEnabled()

