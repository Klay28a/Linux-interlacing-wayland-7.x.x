"""Compact, non-overlapping layout; square number boxes; clean descriptor rows; red instead of silent clamping."""

import pytest
from PyQt6.QtWidgets import QWidget

from gui_fixtures import click_radio, discard, type_into

SCALES = (0.75, 1.0, 1.5)


def sibling_overlaps(root):
    """Pairs of visible sibling widgets whose rectangles intersect (a layout bug when they do)."""
    bad = []
    for parent in [root, *root.findChildren(QWidget)]:
        kids = [c for c in parent.children() if isinstance(c, QWidget) and c.isVisible() and not c.isWindow()]
        for i, a in enumerate(kids):
            for b in kids[i + 1:]:
                inter = a.geometry().intersected(b.geometry())
                if inter.width() > 1 and inter.height() > 1:
                    bad.append((type(a).__name__, type(b).__name__, inter.getRect()))
    return bad


@pytest.fixture
def scaled(cru, app):
    """Apply the real application stylesheet at a zoom level (restored afterwards)."""

    def apply(scale):
        app.setStyleSheet(cru.app_stylesheet(scale))
        app.processEvents()

    yield apply
    app.setStyleSheet("")


@pytest.mark.parametrize("scale", SCALES)
def test_standard_resolution_dialog_never_overlaps(cru, app, scaled, scale):
    scaled(scale)
    dlg = cru.StandardResDialog(None)
    for size in ((500, 315), (1, 1)):  # the roomy size, then the smallest the layout allows
        dlg.resize(*size)
        dlg.show()
        app.processEvents()
        assert sibling_overlaps(dlg) == [], f"overlap at {dlg.width()}x{dlg.height()} zoom {scale}"
    discard(app, dlg)


@pytest.mark.parametrize("scale", SCALES)
def test_detailed_resolution_dialog_never_overlaps(cru, app, scaled, make_dialog, scale):
    scaled(scale)
    dlg = make_dialog()
    for size in ((620, 680), (1, 1)):
        dlg.resize(*size)
        app.processEvents()
        assert sibling_overlaps(dlg) == [], f"overlap at {dlg.width()}x{dlg.height()} zoom {scale}"


@pytest.mark.parametrize("scale", SCALES)
def test_nothing_is_clipped_at_the_dialogs_smallest_size(cru, app, scaled, make_dialog, scale):
    """The dialog refuses to be narrower than its content, so no box or button runs past the right edge."""
    scaled(scale)
    dlg = make_dialog()
    dlg.resize(1, 1)
    app.processEvents()
    view = dlg._scroll.viewport()
    right = view.width()
    for w in dlg._content.findChildren(QWidget):
        if w.isVisible() and not w.objectName().startswith("qt_"):
            edge = w.mapTo(view, w.rect().topRight()).x()
            assert edge <= right + 1, f"{type(w).__name__} {w.objectName()!r} ends at {edge} > {right} (zoom {scale})"


def squeezed_boxes(dlg):
    """Spin boxes painted shorter than their own natural height (rows then run into each other)."""
    return [
        (name, getattr(dlg, name).height(), getattr(dlg, name).sizeHint().height())
        for name in ("hactive_sb", "hfront_sb", "hsync_sb", "hback_sb", "hblank_sb", "htotal_sb", "vtotal_sb", "pclk_sb")
        if getattr(dlg, name).height() < getattr(dlg, name).sizeHint().height()
    ]


@pytest.mark.parametrize("scale", SCALES)
def test_rows_are_never_squeezed_when_the_dialog_is_made_small(cru, app, scaled, make_dialog, scale):
    """Shrinking a big dialog must keep every row at full height: it scrolls instead of squashing the boxes."""
    scaled(scale)
    dlg = make_dialog()
    for size in ((620, 680), (1, 1), (620, 680), (1, 1), (560, 300)):
        dlg.resize(*size)
        app.processEvents()
        dlg.grab()
        assert squeezed_boxes(dlg) == [], f"squeezed at {dlg.width()}x{dlg.height()} zoom {scale}"
        assert dlg._content.height() >= dlg._content.minimumSizeHint().height()
        assert sibling_overlaps(dlg) == []


@pytest.mark.parametrize("scale", SCALES)
def test_rows_are_full_height_on_the_very_first_frame_after_shrinking(cru, app, main_window, scale):
    """Exactly ONE event-loop turn: the first frame the user sees after shrinking must already be right.

    Opened from the main window like the real thing (its zoom stylesheet, a parent window).
    """
    main_window.apply_ui_scale(scale, save=False)
    # Same order as a real session: size it BEFORE the first show, show, paint once, then shrink.
    dlg = cru.DTDEditorDialog(main_window, cru.calculate_timings("CVT Standard", 1600, 1200, 85.0, False))
    dlg.preset_combo.setCurrentText("Manual")
    dlg.resize(620, 680)
    dlg.show()
    app.processEvents()
    dlg.grab()
    dlg.resize(1, 1)
    dlg.show()
    app.processEvents()
    try:
        assert squeezed_boxes(dlg) == [], f"first frame squeezed at zoom {scale}"
    finally:
        discard(app, dlg)
        app.setStyleSheet("")


def test_rows_are_not_squeezed_after_the_main_window_restyles(cru, app, main_window, make_dialog):
    """The real order of events: the main window applies its zoom stylesheet, then a dialog opens and is resized."""
    main_window.apply_ui_scale(1.0, save=False)
    dlg = make_dialog()
    dlg.resize(1, 1)
    app.processEvents()
    dlg.grab()
    assert squeezed_boxes(dlg) == []
    assert dlg._content.height() >= dlg._content.minimumSizeHint().height()


def test_the_standard_list_is_sized_to_its_eight_entries(main_window):
    lst = main_window.std_list
    main_window.resize(680, 900)
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    assert lst.height() <= (lst.fontMetrics().height() + 6) * 8 + 12


def test_number_boxes_fit_their_text_instead_of_stretching(cru, app, scaled, make_dialog):
    scaled(1.0)
    dlg = make_dialog()
    dlg.resize(900, 700)
    app.processEvents()
    for name in ("hactive_sb", "hfront_sb", "htotal_sb", "vtotal_sb", "pclk_sb", "refresh_sb", "hscan_sb"):
        box = getattr(dlg, name)
        assert box.width() <= 150, f"{name} is {box.width()}px wide"
        assert box.height() <= 32, f"{name} is {box.height()}px tall"


def test_number_boxes_have_square_corners(cru, app, scaled, make_dialog):
    scaled(1.0)
    sheet = cru.app_stylesheet(1.0)
    spin_block = sheet[sheet.index("QSpinBox, QDoubleSpinBox {"):].split("}")[0]
    assert "border-radius: 0px" in spin_block


def test_standard_resolution_boxes_are_packed_not_spread(cru, app, scaled):
    scaled(1.0)
    dlg = cru.StandardResDialog(None)
    dlg.resize(700, 400)
    dlg.show()
    app.processEvents()
    assert dlg.width_sb.width() <= 150 and dlg.height_sb.width() <= 150 and dlg.hz_sb.width() <= 150
    assert dlg.height_sb.geometry().left() - dlg.width_sb.geometry().right() < 40, "W x H sit side by side"
    discard(app, dlg)


@pytest.fixture
def main_window(cru, app, tmp_path, monkeypatch, scaled):
    """The real CRU window on two mock ports, with its profile folders inside ``tmp_path``."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cru, "DOCS_PROFILES_DIR", str(home / "Documents" / "linux-cru"))
    monkeypatch.setattr(cru, "LEGACY_PROFILES_DIR", str(home / ".config" / "linux-cru" / "profiles"))
    monkeypatch.setattr(cru, "CONFIG_DIR", str(home / ".config" / "linux-cru"))
    monkeypatch.setattr(cru, "CONFIG_FILE", str(home / ".config" / "linux-cru" / "config.json"))
    ports = [
        {"port": name, "card": "card0", "sysfs_dir": "", "edid_path": "", "status": "connected", "has_edid": False,
         "rel_fw": f"edid/cru-{name.lower()}.bin", "fw_path": str(tmp_path / f"{name}.bin"), "active_override": False}
        for name in ("VGA-1", "DP-1")
    ]
    monkeypatch.setattr(cru, "scan_drm_ports", lambda: ports)
    win = cru.LinuxCRUWindow()
    win.show()
    app.processEvents()
    yield win
    discard(app, win)


def test_a_slot_without_a_timing_has_no_empty_boxes(main_window):
    """An empty or descriptor slot is one line of text across the row, not a row of '-' or blank cells."""
    win = main_window
    win.new_blank_edid()
    for slot in (0, 1, 2):
        assert win.table.columnSpan(slot, 1) == 5
        assert [win.table.item(slot, c).text() for c in range(2, 6)] == ["", "", "", ""]
    assert win.table.item(0, 1).text() == "(Empty)"
    assert win.table.columnSpan(3, 1) == 5
    text = win.table.item(3, 1).text()
    assert text.startswith("Range Limits:") and "30–200 Hz" in text and "700 MHz" in text
    assert [win.table.item(3, c).text() for c in range(2, 6)] == ["", "", "", ""]


def test_a_slot_with_a_timing_still_fills_every_column(cru, main_window):
    win = main_window
    win.new_blank_edid()
    win.edid_bytes[54:72] = cru.encode_dtd(cru.calculate_timings("CVT Standard", 1280, 1024, 85.0, False))
    win.refresh_ui()
    assert win.table.columnSpan(0, 1) == 1
    assert all(win.table.item(0, c).text() for c in range(6))


def test_the_detailed_table_is_exactly_as_tall_as_its_rows(main_window):
    table = main_window.table
    rows = sum(table.rowHeight(r) for r in range(4))
    assert table.height() <= table.horizontalHeader().height() + rows + 8


def test_main_window_has_no_overlaps_and_fits_a_small_window(main_window, app):
    for size in ((680, 600), (420, 420)):
        main_window.resize(*size)
        app.processEvents()
        assert sibling_overlaps(main_window) == [], f"overlap at {size}"


# ---------------------------------------------------------------- red instead of silently clamping


def invalid(box):
    return bool(box.property("invalid"))


def test_a_total_that_leaves_no_back_porch_is_kept_and_shown_red(app, make_dialog):
    """HActive+HFront+HSync = 1896, so a total of 1700 is impossible: keep what was typed, mark it, block Save."""
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.htotal_sb, "1700")
    assert dlg.htotal_sb.value() == 1700, "the typed value is not auto-corrected"
    assert dlg.hblank_sb.value() == 100
    assert dlg.hback_sb.value() == 100 - dlg.hfront_sb.value() - dlg.hsync_sb.value() < 1
    assert invalid(dlg.hback_sb)
    assert not dlg.ok_btn.isEnabled()
    assert "HBack" in dlg.stats_label.text() and "CANNOT SAVE" in dlg.stats_label.text()


def test_the_red_clears_and_save_returns_once_the_value_is_valid(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.htotal_sb, "1700")
    type_into(app, dlg.htotal_sb, "2200")
    assert not any(invalid(b) for b in dlg._timing_boxes)
    assert dlg.ok_btn.isEnabled()
    assert "CANNOT SAVE" not in dlg.stats_label.text()


def test_an_out_of_range_front_porch_is_red(app, make_dialog):
    dlg = make_dialog()
    type_into(app, dlg.hfront_sb, "2000")
    assert dlg.hfront_sb.value() == 2000
    assert invalid(dlg.hfront_sb) and not dlg.ok_btn.isEnabled()


def test_a_vertical_back_porch_below_half_a_line_is_red(app, make_dialog):
    dlg = make_dialog()
    click_radio(app, dlg.rb_anchor_total)
    type_into(app, dlg.vtotal_sb, f"{dlg.vactive_sb.value() + 5}")
    assert invalid(dlg.vback_sb) and invalid(dlg.vtotal_sb)
    assert not dlg.ok_btn.isEnabled()


def test_an_odd_interlaced_active_height_is_flagged_not_rewritten(app, make_dialog):
    dlg = make_dialog(width=1280, height=1024, hz=120.0, interlaced=True)
    type_into(app, dlg.vactive_sb, "1025")
    assert dlg.vactive_sb.value() == 1025
    assert invalid(dlg.vactive_sb) and not dlg.ok_btn.isEnabled()
    assert "even" in dlg.stats_label.text()


def test_a_valid_preset_is_never_red(app, make_dialog):
    dlg = make_dialog(preset="CVT Standard")
    assert not any(invalid(b) for b in dlg._timing_boxes)
    assert dlg.ok_btn.isEnabled()


def test_invalid_boxes_are_styled_red_in_the_stylesheet(cru):
    sheet = cru.app_stylesheet(1.0)
    block = sheet[sheet.index('QSpinBox[invalid="true"]'):].split("}")[0]
    assert "#f85149" in block and "#3d1a1f" in block
