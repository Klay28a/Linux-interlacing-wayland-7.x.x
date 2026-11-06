"""Runner: sudo selection, dry-run suppression and sudo-free user writes."""

from conftest import FakeRunner


def test_sudo_is_noninteractive_by_default():
    assert FakeRunner().sudo(["true"]) == ["sudo", "-n", "true"]


def test_sudo_uses_askpass_when_gui_provides_it():
    assert FakeRunner(environ={"SUDO_ASKPASS": "/tmp/x/askpass.sh"}).sudo(["true"]) == ["sudo", "-A", "true"]


def test_sudo_may_prompt_when_a_terminal_is_attached():
    assert FakeRunner(interactive=True).sudo(["true"]) == ["sudo", "true"]


def test_askpass_wins_over_interactive():
    r = FakeRunner(interactive=True, environ={"SUDO_ASKPASS": "/x"})
    assert r.sudo(["true"]) == ["sudo", "-A", "true"]


def test_no_sudo_when_already_root():
    assert FakeRunner(is_root=True).sudo(["true"]) == ["true"]


def test_dry_run_run_prints_exact_command_and_executes_nothing():
    r = FakeRunner(dry_run=True)
    r.run(["udevadm", "trigger"], privileged=True)
    assert r.executed == []
    assert r.messages == ["[dry-run] would run: sudo -n udevadm trigger"]


def test_dry_run_write_text_shows_content_and_writes_nothing(tmp_path):
    r = FakeRunner(dry_run=True)
    r.write_text(tmp_path / "x.conf", "a=1\nb=2\n")
    assert r.installed == {}
    assert any("would write 8 bytes" in m for m in r.messages)
    assert "[dry-run]   | b=2" in r.messages


def test_query_always_executes_even_in_dry_run():
    r = FakeRunner(dry_run=True, lspci="x")
    assert r.query(["lspci", "-D", "-nn"]).stdout == "x"
    assert r.executed == [["lspci", "-D", "-nn"]]


def test_write_sysfs_dry_run():
    r = FakeRunner(dry_run=True)
    from pathlib import Path
    r.write_sysfs(Path("/sys/x/status"), "detect")
    assert r.executed == []
    assert r.messages == ["[dry-run] would write 'detect' to /sys/x/status"]
