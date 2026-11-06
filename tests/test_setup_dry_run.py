"""End-to-end behaviour of interlace_setup: --dry-run guarantees, sudo -n, no guessing, no root."""

import interlace_setup
from conftest import add_connector, build_host


def _setup_host(sandbox, **kw):
    root, paths = sandbox
    add_connector(root, "DP-1", "connected")
    paths.default_grub.parent.mkdir(parents=True, exist_ok=True)
    paths.default_grub.write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet"\n')
    return build_host(root, paths, tools=("grub-mkconfig", "mkinitcpio"), **kw)


def test_setup_dry_run_changes_nothing_and_prints_plan(sandbox):
    _, paths = sandbox
    host, runner = _setup_host(sandbox, dry_run=True)
    before = paths.default_grub.read_text()
    assert interlace_setup.main(["--dry-run", "--adapter-mode", "dp-dac"], host=host) == 0
    assert runner.mutating == [], runner.mutating
    assert paths.default_grub.read_text() == before
    assert not paths.firmware_edid_dir.exists()
    text = "\n".join(runner.messages)
    assert "[dry-run] would install" in text
    assert "[dry-run] would run: sudo -n mkinitcpio -P" in text


def test_setup_real_run_records_sudo_commands_and_state(sandbox):
    _, paths = sandbox
    host, runner = _setup_host(sandbox)
    assert interlace_setup.main(["--adapter-mode", "dp-dac"], host=host) == 0
    assert str(paths.firmware_edid_dir / "cru-dp-1.bin") in runner.installed
    assert str(paths.state_file) in runner.installed
    assert ["sudo", "-n", "mkinitcpio", "-P"] in runner.executed
    # every privileged call must be non-interactive (never hangs waiting for a password)
    assert all(c[1] == "-n" for c in runner.executed if c[0] == "sudo")


def test_setup_live_only_skips_boot_and_initramfs(sandbox):
    _, paths = sandbox
    host, runner = _setup_host(sandbox)
    assert interlace_setup.main(["--live-only", "--adapter-mode", "dp-dac"], host=host) == 0
    assert str(paths.default_grub) not in runner.installed
    assert ["sudo", "-n", "mkinitcpio", "-P"] not in runner.executed


def test_setup_without_connector_fails_instead_of_guessing(sandbox, capsys):
    root, paths = sandbox
    host, runner = build_host(root, paths)
    assert interlace_setup.main([], host=host) == 2
    assert "--connector" in capsys.readouterr().err
    assert runner.mutating == []


def test_explicit_missing_edid_source_is_an_error_not_a_silent_default(sandbox, capsys):
    """Regression: `--edid /typo.bin` used to silently install a generic default EDID."""
    _, paths = sandbox
    host, runner = _setup_host(sandbox)
    assert interlace_setup.main(["--edid", "/nonexistent/x.bin", "--adapter-mode", "dp-dac"], host=host) == 2
    assert "missing, unreadable or shorter" in capsys.readouterr().err
    assert runner.mutating == []
    assert str(paths.firmware_edid_dir / "cru-dp-1.bin") not in runner.installed


def test_explicit_truncated_edid_source_is_an_error(sandbox, tmp_path, capsys):
    short = tmp_path / "short.bin"
    short.write_bytes(b"\x00" * 64)
    host, runner = _setup_host(sandbox)
    assert interlace_setup.main(["--edid", str(short)], host=host) == 2
    assert runner.mutating == []


def test_unreadable_installed_edid_is_never_replaced_by_a_default(sandbox, capsys):
    """An installed EDID that exists but cannot be read must not be overwritten with a generic one."""
    _, paths = sandbox
    host, runner = _setup_host(sandbox)
    installed = paths.firmware_edid_dir / "cru-dp-1.bin"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"\x00" * 128)
    installed.chmod(0o000)
    try:
        if installed.read_bytes():  # running as root: permissions do not apply, nothing to test
            return
    except PermissionError:
        pass
    try:
        assert interlace_setup.main(["--adapter-mode", "dp-dac"], host=host) == 2
        assert "could not be read" in capsys.readouterr().err
        assert runner.mutating == []
    finally:
        installed.chmod(0o644)


def test_setup_rejects_bad_connector_name(sandbox, capsys):
    root, paths = sandbox
    host, runner = build_host(root, paths)
    assert interlace_setup.main(["--connector", "DP-1; rm -rf /"], host=host) == 2
    assert "Invalid connector" in capsys.readouterr().err
    assert runner.mutating == []


def test_setup_refuses_root_unless_dry_run(sandbox):
    root, paths = sandbox
    add_connector(root, "DP-1", "connected")
    host, _ = build_host(root, paths, is_root=True)
    assert interlace_setup.main([], host=host) == 1
