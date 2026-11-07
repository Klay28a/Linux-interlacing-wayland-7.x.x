"""Button naming, ordering and styling: the same shape in every step, and stable whatever the status."""

from gui_fixtures import SCRIPT_NAMES


def script_buttons(window):
    return (window.run_setup_btn, window.run_kernel_btn, window.install_cru_btn)


def row_buttons(script_button):
    """The buttons in the same horizontal row as ``script_button``, left to right."""
    parent = script_button.parentWidget().layout()
    for i in range(parent.count()):
        row = parent.itemAt(i).layout()
        if row is not None and any(row.itemAt(j).widget() is script_button for j in range(row.count())):
            return [row.itemAt(j).widget() for j in range(row.count())]
    raise AssertionError("row not found")


def test_script_buttons_are_named_after_their_scripts_and_share_one_style(window):
    assert tuple(b.text() for b in script_buttons(window)) == SCRIPT_NAMES
    assert {b.objectName() for b in script_buttons(window)} == {"scriptBtn"}


def test_every_step_has_the_script_button_first_and_a_small_helper_second(window):
    pairs = (
        (window.run_setup_btn, window.reload_btn),
        (window.run_kernel_btn, window.rules_btn),
        (window.install_cru_btn, window.launch_cru_btn),
    )
    for script, helper in pairs:
        assert row_buttons(script) == [script, helper]
        assert helper.objectName() == "subBtn"
        assert 1 <= len(helper.text().split()) <= 5, helper.text()


def test_steps_run_in_the_order_setup_kernel_cru(window):
    window.show()
    ys = [b.mapTo(window, b.rect().topLeft()).y() for b in script_buttons(window)]
    assert ys == sorted(ys)


def test_button_text_and_style_never_change_when_status_changes(window):
    before = {b: (b.text(), b.objectName()) for b in script_buttons(window)}
    window.gpu_combo.setCurrentIndex(2)
    window.adapter_combo.setCurrentIndex(1)
    window.refresh_status()
    assert {b: (b.text(), b.objectName()) for b in before} == before


def test_every_button_stays_enabled_when_a_step_is_verified(window):
    """There is no 'unlock' checkbox: a verified step can always be re-run."""
    assert not hasattr(window, "force_rerun_chk")
    for b in (*script_buttons(window), window.reload_btn, window.rules_btn, window.launch_cru_btn):
        assert b.isEnabled()


def test_status_cells_use_few_words(window):
    for cell in (window.cell_profile, window.cell_boot, window.cell_edid, window.cell_rules, window.cell_kernel):
        assert len(cell[2].text().split()) <= 5, cell[2].text()
