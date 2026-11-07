# Maintainer: kleien
pkgname=linux-interlace-suite
pkgver=1.0.0
pkgrel=1
pkgdesc="Linux CRT Interlacing & RDNA DP/HDMI DAC Adapter Suite (EDID, Multi-GPU & 15kHz Kernel Patcher GUI)"
arch=('any')
license=('MIT')
depends=('bash' 'python' 'python-pyqt6' 'pciutils')
optdepends=(
    'base-devel: Required for compiling patched 15kHz/interlaced kernels'
    'git: Required for fetching kernel PKGBUILD and 15kHz patches'
    'pacman-contrib: Package build utilities'
    'limine-mkinitcpio-hook: Limine bootloader initramfs integration'
)
source=(
    'linux-interlace-suite.py'
    'setup-interlace-env.sh'
    'fix-interlaced-kernel.sh'
    'install-linux-cru.sh'
    'install-interlace-suite.sh'
    '11_linux_rdna_dp_hdmi_interlace.patch'
    'linux-interlace-suite.desktop'
    'interlace_runner.py'
    'interlace_gpu.py'
    'interlace_edid.py'
    'interlace_cmdline.py'
    'interlace_boot.py'
    'interlace_rules.py'
    'interlace_state.py'
    'interlace_setup.py'
    'interlace_apply_rules.py'
    'interlace_pkgbuild.py'
    'interlace_rdna_patch.py'
    'interlace_apply_edid.py'
    'interlace_kernel.py'
    'interlace_manifest.py'
    'interlace_patches.py'
    'interlace_gui_tasks.py'
    'interlace_selection.py'
    'interlace_sysinfo.py'
    'interlace_verify.py'
    'linux_cru.py'
)
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP'
            'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP'
            'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')
# NOTE: keep one entry per source above (verified by tests/test_packaging.py).

package() {
    install -d "$pkgdir/usr/share/linux-interlace-suite"
    install -Dm755 "$srcdir/linux-interlace-suite.py" "$pkgdir/usr/share/linux-interlace-suite/linux-interlace-suite.py"
    install -Dm755 "$srcdir/setup-interlace-env.sh" "$pkgdir/usr/share/linux-interlace-suite/setup-interlace-env.sh"
    install -Dm755 "$srcdir/fix-interlaced-kernel.sh" "$pkgdir/usr/share/linux-interlace-suite/fix-interlaced-kernel.sh"
    install -Dm755 "$srcdir/install-linux-cru.sh" "$pkgdir/usr/share/linux-interlace-suite/install-linux-cru.sh"
    install -Dm755 "$srcdir/install-interlace-suite.sh" "$pkgdir/usr/share/linux-interlace-suite/install-interlace-suite.sh"
    install -Dm644 "$srcdir/11_linux_rdna_dp_hdmi_interlace.patch" "$pkgdir/usr/share/linux-interlace-suite/11_linux_rdna_dp_hdmi_interlace.patch"
    # install-linux-cru.sh installs this file, so it must ship next to the script.
    install -Dm755 "$srcdir/linux_cru.py" "$pkgdir/usr/share/linux-interlace-suite/linux_cru.py"

    local mod
    for mod in interlace_runner interlace_gpu interlace_edid interlace_cmdline interlace_boot \
               interlace_rules interlace_state interlace_setup interlace_apply_rules \
               interlace_pkgbuild interlace_rdna_patch interlace_apply_edid \
               interlace_kernel interlace_manifest interlace_patches interlace_gui_tasks \
               interlace_selection interlace_sysinfo interlace_verify; do
        install -Dm644 "$srcdir/$mod.py" "$pkgdir/usr/share/linux-interlace-suite/$mod.py"
    done

    install -d "$pkgdir/usr/bin"
    ln -s /usr/share/linux-interlace-suite/linux-interlace-suite.py "$pkgdir/usr/bin/linux-interlace-suite"

    install -Dm644 "$srcdir/linux-interlace-suite.desktop" "$pkgdir/usr/share/applications/linux-interlace-suite.desktop"
}
