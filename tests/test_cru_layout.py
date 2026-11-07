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


def std_columns(lst):
    """How many entries sit in each visual column of the standard list."""
    rects = [lst.visualItemRect(lst.item(i)) for i in range(lst.count())]
    lefts = sorted({r.left() for r in rects})
    return [sum(1 for r in rects if r.left() == left) for left in lefts]


def show_eight_standard(win, app):
    win.edid_bytes[38:54] = b"\x01\x01" * 8
    for i, w in enumerate((2048, 1920, 1600, 1152, 1024, 640, 800, 1280)):
        win.edid_bytes[38 + 2 * i] = w // 8 - 31
        win.edid_bytes[39 + 2 * i] = 0x40 | 25
    win.std_slots = win.cru_decode_std(win.edid_bytes)
    win.refresh_ui()
    app.processEvents()


@pytest.fixture
def eight_standard(cru, main_window, app):
    main_window.cru_decode_std = cru.decode_std_timings
    show_eight_standard(main_window, app)
    return main_window


def test_a_tall_window_shows_the_eight_standard_resolutions_in_one_column(eight_standard, app):
    win = eight_standard
    win.resize(680, 1100)
    app.processEvents()
    assert std_columns(win.std_list) == [8]
    assert win.std_list.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize("scale", SCALES)
def test_a_short_window_spills_the_standard_list_to_the_right_not_into_a_scroll_bar(eight_standard, app, scale):
    win = eight_standard
    win.apply_ui_scale(scale, save=False)
    width = round(680 * scale)  # text grows with the zoom, so the window must be wide enough for two columns
    win.resize(width, round(1100 * scale))
    app.processEvents()
    tall = win.std_list.height()
    win.resize(width, round(560 * scale))
    app.processEvents()
    cols = std_columns(win.std_list)
    assert win.std_list.height() < tall, "the list gives its height back"
    assert len(cols) >= 2 and sum(cols) == 8, f"entries did not move to the right: {cols}"
    assert win.std_list.verticalScrollBar().maximum() == 0, "no scroll bar inside the list"
    assert win.std_list.horizontalScrollBar().maximum() == 0
    assert win.std_list.horizontalScrollBarPolicy() == win.std_list.verticalScrollBarPolicy()


def test_columns_of_the_standard_list_never_overlap(eight_standard, app):
    win = eight_standard
    win.resize(680, 560)
    app.processEvents()
    rects = [win.std_list.visualItemRect(win.std_list.item(i)) for i in range(8)]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.intersects(b), (a, b)
    fm = win.std_list.fontMetrics()
    widest = max(fm.horizontalAdvance(win.std_list.item(i).text()) for i in range(8))
    assert all(r.width() >= widest for r in rects)


def test_the_standard_list_gets_taller_again_when_the_window_does(eight_standard, app):
    win = eight_standard
    win.resize(680, 560)
    app.processEvents()
    win.resize(680, 1100)
    app.processEvents()
    assert std_columns(win.std_list) == [8]


def test_the_frequency_rows_are_three_aligned_columns(make_dialog, app):
    """Radio | box | Actual, one row each: no 'Actual' row stacked between the boxes, same edges in every row."""
    dlg = make_dialog()
    for width in (500, 800):
        dlg.resize(width, 700)
        app.processEvents()
        rows = ((dlg.rb_rate_v, dlg.refresh_sb, dlg.actual_vrate_lbl),
                (dlg.rb_rate_h, dlg.hscan_sb, dlg.actual_hrate_lbl),
                (dlg.rb_rate_pclk, dlg.pclk_sb, dlg.actual_pclk_lbl))
        for radio, box, actual in rows:
            assert dlg.fgrid.indexOf(radio) >= 0 and dlg.fgrid.indexOf(box) >= 0 and dlg.fgrid.indexOf(actual) >= 0
            ry = radio.mapTo(dlg, radio.rect().center()).y()
            assert box.mapTo(dlg, box.rect().center()).y() == pytest.approx(ry, abs=3), "box beside its radio"
            assert actual.mapTo(dlg, actual.rect().center()).y() == pytest.approx(ry, abs=3), "actual beside its box"
        lefts = {box.mapTo(dlg, box.rect().topLeft()).x() for _, box, _ in rows}
        rights = {box.mapTo(dlg, box.rect().topRight()).x() for _, box, _ in rows}
        actual_lefts = {a.mapTo(dlg, a.rect().topLeft()).x() for _, _, a in rows}
        assert len(lefts) == 1 and len(rights) == 1, "the three boxes share their edges"
        assert len(actual_lefts) == 1, "every 'Actual' label starts at the same x"
        ys = [box.mapTo(dlg, box.rect().topLeft()).y() for _, box, _ in rows]
        assert ys == sorted(ys) and ys[1] - ys[0] <= dlg.pclk_sb.height() + 8, "rows are evenly stacked"


def test_the_refresh_box_is_in_the_frequency_group_not_the_top_block(make_dialog):
    dlg = make_dialog()
    assert dlg.fgrid.indexOf(dlg.refresh_sb) >= 0
    assert dlg.top_grid.indexOf(dlg.refresh_sb) < 0


def test_number_boxes_are_a_little_shorter_vertically(cru, app, scaled, make_dialog):
    """1-2 px less padding top and bottom than the previous round (29 px at 100%)."""
    scaled(1.0)
    dlg = make_dialog()
    assert dlg.hactive_sb.height() <= 27
    assert dlg.hactive_sb.height() >= 22
    sheet = cru.app_stylesheet(1.0)
    block = sheet[sheet.index("QSpinBox, QDoubleSpinBox {"):].split("}")[0]
    assert "padding: 1px 4px" in block, "vertical padding shrinks; horizontal padding stays"


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


def slots_visible(table):
    """True when Slot 1's top and Slot 4's bottom are both inside the viewport."""
    view = table.viewport().height()
    return (
        table.visualItemRect(table.item(0, 0)).top() >= 0
        and table.visualItemRect(table.item(3, 0)).bottom() < view
        and table.verticalScrollBar().value() == 0
    )


@pytest.mark.parametrize("scale", SCALES)
def test_all_four_detailed_slots_stay_visible_whatever_is_selected_or_pressed(main_window, app, scale):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    win = main_window
    win.apply_ui_scale(scale, save=False)
    win.resize(round(680 * scale), round(900 * scale))
    app.processEvents()
    table = win.table
    assert slots_visible(table)
    for row in (2, 3, 1, 0, 3):
        table.selectRow(row)
        app.processEvents()
        assert slots_visible(table), f"selecting slot {row + 1} hid a slot at zoom {scale}"
    for key in (Qt.Key.Key_Down, Qt.Key.Key_Down, Qt.Key.Key_End, Qt.Key.Key_PageDown):
        QTest.keyClick(table, key)
        app.processEvents()
        assert slots_visible(table), f"key {key} hid a slot"
    wheel = QWheelEvent(QPointF(40, 40), QPointF(40, 40), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(table.viewport(), wheel)
    app.processEvents()
    assert slots_visible(table), "the mouse wheel scrolled the 4-row table"


def test_the_table_regrows_when_its_header_gets_taller(main_window, app):
    """A taller header (bigger font, another theme) must not push the last slot out of view."""
    table = main_window.table
    assert slots_visible(table)
    table.horizontalHeader().setMinimumHeight(table.horizontalHeader().height() + 14)
    app.processEvents()
    app.processEvents()
    assert slots_visible(table)
    table.selectRow(3)
    app.processEvents()
    assert slots_visible(table), "selecting the last slot after the header grew scrolled Slot 1 away"
    assert table.height() >= table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(4))


def make_table_too_short(table):
    """Force the situation Qt would scroll in: the viewport is shorter than the rows (fitting is paused)."""
    table._fitting = True
    table.setFixedHeight(table.height() - 30)
    assert table.verticalScrollBar().maximum() > 0, "setup: the table must be scrollable for this test to mean anything"


def test_selecting_a_slot_never_scrolls_the_table_even_when_it_could(main_window, app):
    table = main_window.table
    make_table_too_short(table)
    for row in (3, 2, 3):
        table.selectRow(row)
        app.processEvents()
        assert table.verticalScrollBar().value() == 0, f"selecting slot {row + 1} scrolled Slot 1 away"
    assert table.visualItemRect(table.item(0, 0)).top() >= 0


def test_the_wheel_never_scrolls_the_table_even_when_it_could(main_window, app):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication

    table = main_window.table
    make_table_too_short(table)
    wheel = QWheelEvent(QPointF(40, 40), QPointF(40, 40), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(table.viewport(), wheel)
    app.processEvents()
    assert table.verticalScrollBar().value() == 0


def test_the_table_wheel_scrolls_the_page_not_the_table(main_window):
    table = main_window.table
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent

    wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    table.wheelEvent(wheel)
    assert not wheel.isAccepted(), "ignored, so the scroll area behind it gets the event"


def test_a_tall_window_does_not_float_the_table_inside_its_group(main_window, app):
    """Groups keep their natural height: extra window height becomes space at the bottom, not gaps in the groups."""
    win = main_window
    win.resize(680, 1000)
    app.processEvents()
    group = win.table.parentWidget()
    assert group.height() == group.sizeHint().height()
    assert win.table.geometry().top() < 45, "the table sits right under the group title"
    assert win.dtd_buttons[0].geometry().top() - win.table.geometry().bottom() < 16, "buttons sit right under the table"


def test_a_slot_without_a_timing_has_blank_cells_but_keeps_every_column_bar(main_window):
    """The text is cleared, the cells are not merged: merged cells would erase the bars between the columns."""
    win = main_window
    win.new_blank_edid()
    for slot in range(4):
        assert [win.table.columnSpan(slot, c) for c in range(6)] == [1] * 6, f"slot {slot + 1} has merged cells"
        assert [win.table.item(slot, c).text() for c in range(2, 6)] == ["", "", "", ""]
    assert win.table.item(0, 1).text() == "(Empty)"
    assert win.table.item(3, 1).text() == "Range Limits"


def test_a_monitor_name_slot_is_a_label_with_blank_cells(main_window):
    win = main_window
    win.new_blank_edid()
    win.edid_bytes[72:90] = bytes([0, 0, 0, 0xFC, 0]) + b"CRT Test\n    "
    win.refresh_ui()
    assert win.table.item(1, 1).text() == "Name: CRT Test"
    assert [win.table.item(1, c).text() for c in range(2, 6)] == ["", "", "", ""]
    assert win.table.columnSpan(1, 1) == 1


def test_the_detailed_table_never_shows_a_scroll_bar(main_window, app):
    for scale in (0.75, 1.0, 1.5):
        main_window.apply_ui_scale(scale, save=False)
        main_window.resize(680, 700)
        app.processEvents()
        bar = main_window.table.verticalScrollBar()
        assert bar.maximum() == 0 and not bar.isVisible(), f"scroll bar at zoom {scale}"
        assert main_window.table.height() >= main_window.table.horizontalHeader().height() + sum(
            main_window.table.rowHeight(r) for r in range(4)
        )


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
