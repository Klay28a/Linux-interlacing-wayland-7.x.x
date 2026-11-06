# Linux-interlacing-wayland-7.x.x

I used AI to automate the processes that I have been doing for EDID configurations and installing the 15kHz patches for monitor interlacing. I am not an experienced coder or scripter. **_USE THESE AT YOUR OWN RISK_**.

Tested on CachyOS, `7.3` kernels, KDE Plasma Wayland, and an HP p1230 (2070sb rebadge) CRT monitor.

---

## Install

Everything else (EDID setup, GPU rules, kernel builds, installing Linux CRU) is done from the **Linux Interlacing Suite** app, so you only need to install the app.

**Arch / CachyOS** (builds and installs it as a package):
```bash
git clone https://github.com/Klay28a/Linux-interlacing-wayland-7.x.x.git
cd Linux-interlacing-wayland-7.x.x
makepkg -si
```

**Debian / Ubuntu, Fedora, openSUSE** (installs for your user; uses your package manager only if PyQt6 is missing):
```bash
git clone https://github.com/Klay28a/Linux-interlacing-wayland-7.x.x.git
cd Linux-interlacing-wayland-7.x.x
./install.sh
```

Then open **Linux Interlacing Suite** from your application menu, or run `linux-interlace-suite`. Add `--dry-run` to `./install.sh` to preview what it would do.

---

## 1. Linux CRT Interlacing Suite (`linux-interlace-suite`)

**Linux CRT Interlacing Suite** (`linux-interlace-suite`) is a unified graphical manager for configuring custom CRT EDIDs, Single-GPU & Dual-GPU rules (AMD RDNA 1–4, AMD GCN, NVIDIA), DisplayPort/HDMI DAC adapters, and 15kHz/interlaced kernel builds from one place without needing the terminal.

- **Auto-Detection & Hardware Verification:** Detects your GPUs, active DRM connectors, bootloader (`Limine` / `GRUB`), initramfs tool, and 15kHz kernel status with live `✓` verification badges.
- **One-Click Workflow:** Configure your GPU profile (`Single-GPU` or `Dual-GPU`), adapter mode (`DP DAC`, `HDMI DAC`, or `Native Analog`), and target kernel (`7.3`, `7.2`, `6.18 LTS`, `6.12 LTS`, `6.6 LTS`, `6.1 LTS`, `linux-next`), then run EDID setup, live EDID reloads, or kernel builds with a live progress bar.

<p align="center">
  <img height="400" alt="Linux CRT Interlacing Suite — Hardware & GPU Config" src="assets/linux-interlace-suite-1.png" />
  &nbsp;&nbsp;
  <img height="400" alt="Linux CRT Interlacing Suite — Step-by-Step Workflow" src="assets/linux-interlace-suite-2.png" />
</p>

---

## 2. Linux CRU (`linux-cru` / `install-linux-cru.sh`)

**Linux CRU (`linux-cru`)** is a standalone Linux alternative to ToastyX's Custom Resolution Utility (CRU). It calculates exact ToastyX timings (`CVT Standard`, `CVT-RB`, `CVT-RB2`, `GTF Standard`, `Automatic CRT/PC/HDTV`, `Exact`, `Manual`), formats interlaced resolutions using Linux full-frame vertical lines, stores user profiles in `~/Documents/linux-cru/`, and can apply EDID changes live without rebooting or install them to your initramfs/bootloader.

Install it with the **Install Linux CRU** button in the suite, or from a terminal in the cloned folder:

```bash
./install-linux-cru.sh
linux-cru
```

<p align="center">
  <img height="420" alt="Linux CRU Main Window" src="assets/linux-cru.png" />
</p>

---

## 3. Scripts

The suite runs these for you, but they can also be run from a terminal. Both support `--dry-run`, which prints every command and file write without changing anything. They never ask questions; privileged steps use `sudo`, which asks for your password in a terminal.

- **`setup-interlace-env.sh`**: Detects your target video connector (`VGA-*`, `DVI-I-*`, `DP-*`, `HDMI-A-*`), writes a Linux full-frame interlaced EDID to `/usr/lib/firmware/edid/`, embeds it in your initramfs (`mkinitcpio`, `dracut` or `initramfs-tools`), adds the matching parameters to your `Limine`, `GRUB` or `systemd-boot` kernel command line, and reloads the EDID live. If no connector can be detected it stops and asks you to pass `--connector`.
- **`fix-interlaced-kernel.sh`**: Fetches the CachyOS kernel `PKGBUILD`, applies the 15kHz and interlace patches from [`D0023R/linux_kernel_15khz`](https://github.com/D0023R/linux_kernel_15khz) (`01`–`05`, `07`–`09`) plus an RDNA 1–4 DCN interlacing and DP/HDMI DAC adapter unlock, applies your Single/Dual-GPU rules, then builds and installs the kernel. It needs an Arch-based system (`--config-only` applies just the GPU rules on any distribution) and builds with `-march=native` by default (change it with `--processor-opt`). `11_linux_rdna_dp_hdmi_interlace.patch` is kept in the repo as a reference diff against 7.3.

```bash
./setup-interlace-env.sh --dry-run
./fix-interlaced-kernel.sh --dry-run --kernel-version 7.3
```

For manual kernel command line setup, see `u/raven2cz`'s comment on [r/archlinux](https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/). Example `Limine` config:

```ini
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"
```
