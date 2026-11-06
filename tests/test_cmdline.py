"""Pure text editors: bootloader/kernel cmdline, mkinitcpio, dracut, live param merge."""

import subprocess
from pathlib import Path

from interlace_cmdline import (
    add_to_mkinitcpio_files,
    dracut_conf_text,
    merge_edid_firmware_param,
    update_cmdline_text,
    update_kernel_cmdline_text,
)

GRUB = (
    "GRUB_TIMEOUT=5\n"
    'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
    "GRUB_DISABLE_OS_PROBER=false\n"
)


def test_grub_other_lines_preserved_and_args_added():
    out = update_cmdline_text(GRUB, "GRUB_CMDLINE_LINUX_DEFAULT", "DP-1", "edid/cru-dp-1.bin", "rdna-single")
    assert "GRUB_TIMEOUT=5\n" in out
    assert "GRUB_DISABLE_OS_PROBER=false\n" in out
    assert 'quiet splash drm.edid_firmware=DP-1:edid/cru-dp-1.bin video=DP-1:e"' in out
    assert "si_support" not in out  # rdna-single does not need radeon/amdgpu SI/CIK flags


def test_gcn_profile_adds_si_cik_flags():
    out = update_cmdline_text(GRUB, "GRUB_CMDLINE_LINUX_DEFAULT", "VGA-1", "edid/crufile.bin", "gcn-single")
    assert "radeon.si_support=0" in out
    assert "amdgpu.cik_support=1" in out


def test_existing_other_connector_edid_is_kept_and_update_is_idempotent():
    first = update_cmdline_text(GRUB, "GRUB_CMDLINE_LINUX_DEFAULT", "DP-1", "edid/a.bin", "rdna-single")
    second = update_cmdline_text(first, "GRUB_CMDLINE_LINUX_DEFAULT", "HDMI-A-1", "edid/b.bin", "rdna-single")
    assert "DP-1:edid/a.bin,HDMI-A-1:edid/b.bin" in second
    assert second.count("drm.edid_firmware=") == 1
    assert update_cmdline_text(second, "GRUB_CMDLINE_LINUX_DEFAULT", "HDMI-A-1", "edid/b.bin", "rdna-single") == second


def test_commented_key_is_ignored_and_line_appended():
    text = '#GRUB_CMDLINE_LINUX_DEFAULT="old"\nFOO=1\n'
    out = update_cmdline_text(text, "GRUB_CMDLINE_LINUX_DEFAULT", "DP-1", "edid/a.bin", "rdna-single")
    assert out.startswith(text)
    assert out.splitlines()[-1].startswith('GRUB_CMDLINE_LINUX_DEFAULT="drm.edid_firmware=DP-1:edid/a.bin')


def test_limine_missing_key_appends_kernel_cmdline_default():
    out = update_cmdline_text("TIMEOUT=5\n", "KERNEL_CMDLINE", "DP-1", "edid/a.bin", "rdna-single")
    assert 'KERNEL_CMDLINE[default]+="drm.edid_firmware=DP-1:edid/a.bin video=DP-1:e"' in out


def test_systemd_boot_entry_options_line():
    entry = "title Arch\nlinux /vmlinuz\noptions root=UUID=abc rw quiet\n"
    out = update_cmdline_text(entry, "options", "DP-1", "edid/a.bin", "rdna-single")
    assert out.startswith("title Arch\nlinux /vmlinuz\n")
    assert "options root=UUID=abc rw quiet drm.edid_firmware=DP-1:edid/a.bin video=DP-1:e" in out


def test_bare_kernel_cmdline_file():
    out = update_kernel_cmdline_text("root=UUID=abc rw quiet\n", "DP-1", "edid/a.bin", "rdna-single")
    assert out == "root=UUID=abc rw quiet drm.edid_firmware=DP-1:edid/a.bin video=DP-1:e\n"


def test_merge_live_param():
    assert merge_edid_firmware_param("", "DP-1", "edid/a.bin") == "DP-1:edid/a.bin"
    assert merge_edid_firmware_param("VGA-1:edid/x.bin\n", "DP-1", "edid/a.bin") == "VGA-1:edid/x.bin,DP-1:edid/a.bin"


def test_mkinitcpio_files_added_once():
    conf = "MODULES=()\nFILES=(/a.bin)\nHOOKS=(base)\n"
    out = add_to_mkinitcpio_files(conf, "/usr/lib/firmware/edid/x.bin")
    assert "FILES=(/usr/lib/firmware/edid/x.bin /a.bin)" in out
    assert add_to_mkinitcpio_files(out, "/usr/lib/firmware/edid/x.bin") == out
    assert "FILES=(/x)" in add_to_mkinitcpio_files("MODULES=()\n", "/x")


def test_dracut_conf_idempotent():
    out = dracut_conf_text("", "/x.bin")
    assert out == 'install_items+=" /x.bin "\n'
    assert dracut_conf_text(out, "/x.bin") == out


def test_regression_pipe_plus_heredoc_discards_stdin(tmp_path: Path):
    """The old bash `cat f | python3 - ... << EOF` fed the script an EMPTY stdin.

    This proves the failure mode that wiped bootloader files, and that the pure function
    (text passed as an argument) does not depend on stdin at all.
    """
    script = tmp_path / "repro.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"printf 'KEEP=1\\n' > {tmp_path}/work\n"
        f"cat {tmp_path}/work | python3 - << 'PYEOF'\n"
        "import sys\nprint(len(sys.stdin.readlines()))\nPYEOF\n",
        encoding="utf-8",
    )
    res = subprocess.run(["bash", str(script)], check=False, text=True, capture_output=True)
    assert res.stdout.strip() == "0"
    assert "KEEP=1\n" in update_cmdline_text("KEEP=1\n", "options", "DP-1", "edid/a.bin", "rdna-single")
