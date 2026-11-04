# Linux-interlacing-wayland-7.x.x

I used AI to automate the processes that I have been doing for EDID configurations and installing the 15khz patches for monitor interlacing. I am not an experienced coder or scripter. **_USE THESE AT YOUR OWN RISK_**.

These were tested on a fresh install of the latest CachyOS, 7.3 kernels, KDE 6.8, Wayland. Monitor used was an HP p1230 (2070sb rebadge).

### Getting Started (Download the Scripts)

Open a terminal and run these commands to download the repo, enter the folder with the scripts, and make them executable:

```bash
git clone https://github.com/Klay28a/Linux-interlacing-wayland-7.x.x.git
cd Linux-interlacing-wayland-7.x.x
chmod +x *.sh
```

-----------------------------------------------------------------------

**setup-interlace-env.sh**

*Compatibility: Arch / CachyOS, Debian / Ubuntu, Fedora, openSUSE.*  

*Affects: `/usr/lib/firmware/edid/`, initramfs config (`mkinitcpio`, `dracut`, or `initramfs-tools`), and bootloader `CMDLINE` configs (**Limine** or **GRUB**).*

This script sets up your custom EDID file and configures your bootloader to load it on startup.

- Detects your active analog video port (`VGA-1`, `DVI-I-1`, or a specified port).
- Creates a default EDID `.bin` file (or uses one you provide) and converts any Windows CRU half-field interlaced timings into Linux's full-frame format.
- Adds the EDID file to your initramfs, adds the `drm.edid_firmware`, `video`, and `amdgpu`/`radeon` parameters to your bootloader `CMDLINE`, and rebuilds the initramfs.

**Usage:**

Run with automatic port detection and default EDID setup (recommended):
```bash
./setup-interlace-env.sh
```

Or specify your own `.bin` file and/or a specific video port:
```bash
./setup-interlace-env.sh ~/my-edid.bin auto
./setup-interlace-env.sh ~/my-edid.bin DVI-I-1
```

If you want to manually add the `CMDLINE` boot configuration with the EDID file pointer, see the first comment by `u/raven2cz` on this Reddit thread:

https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/

Mine is set up like this:

```ini
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"
```
These parameters: 'radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1' help when using the AMD Rx 200 and 300 Series by preventing them from using legacy drivers. (GCN 1.0 and 1.1) Unsure if this is still needed now because the latest 7.3 kernels has added more support for older cards. These parameters were being used when I was on 7.2.x kernels.

-----------------------------------------------------------------------

**fix-interlaced-kernel.sh**

*Compatibility: Arch Linux / CachyOS (`pacman` / `makepkg`).*  

*Affects: Linux kernel (`linux-cachyos`), kernel GPU drivers (`amdgpu`, `radeon`, `i915`, `nouveau`), and GPU module/Wayland config files (`/etc/modprobe.d/`, `~/.config/environment.d/`).*

This script pulls the latest CachyOS kernel (`7.x.x`) and compiles it with the 15kHz and interlace patches from `D0023R/linux_kernel_15khz` for GPUs capable of interlacing. Run this whenever a kernel update overwrites your patched kernel and causes your interlaced resolutions to disappear.

- Pulls the latest `linux-cachyos` `PKGBUILD` and applies the 15kHz/interlace patches (`01`–`05`, `07`–`09`) so the kernel and GPU drivers allow interlaced modes.
- The 15khz patches will affect amd, nvidia, and intel graphics drivers.
- Compiles and installs the patched kernel.

**Usage:**

Run the script as your normal user (do not use `sudo` — it will prompt you when needed):
```bash
./fix-interlaced-kernel.sh
```

For non-Arch distros (such as Debian/Ubuntu or Fedora), you can compile the patches from this repository manually:

https://github.com/D0023R/linux_kernel_15khz

-----------------------------------------------------------------------

**install-linux-cru.sh**

*Compatibility: Arch / CachyOS, Debian / Ubuntu, Fedora, openSUSE.*  

This script installs **Linux CRU (`linux-cru`)** and adds an application shortcut. Intended to be a linux alternative to Toastyx's CRU.

**Linux Full-Frame Interlaced Formatting:** Using Windows CRU through Wine exports interlaced resolutions with halved vertical lines (e.g. `2048x768i @ 320Hz`), because Linux DRM expects the full vertical resolution (`2048x1536i @ 160Hz`) with the interlace flag. `linux-cru` formats interlaced resolutions using full-frame vertical lines so they show up with the correct resolution and refresh rate in Linux Display Settings (and auto-converts Windows CRU `.bin` files on import).
- **Port & Profile Selection:** Should be able to create new profiles to switch. Two defaults should be the /usr/lib/firmware/edid/edid.bin file and the other should be the active DRM EDID. So if you haven't applied the changes yet they should be different.
- **Apply Live or Install to Bootloader:** Can reload new EDID changes live into the kernel without rebooting (**Apply Live**), or write the EDID to firmware, update your bootloader `CMDLINE`, and rebuild initramfs directly from the app, If the app freezes just wait and you will get a pop-up saying it was completed.

**Usage:**

Install the app, it will create a application manager shortcut:
```bash
./install-linux-cru.sh
```

Once installed, open **Linux CRU** from your Start Menu or launch it from any terminal with:
```bash
linux-cru
```

### Feature Comparison Table (Old Repo Version vs. New Version)

| Category | Old Repo Version (`v1.0.0`) | New Version (`v2.1.0`) |
| :--- | :--- | :--- |
| **Timing Engine** | Single-pass float approximations for `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `CVT Standard`, `CVT-RB`, `CVT-RB2`, `GTF Standard`, `Manual` | Ported **ToastyX CRU's exact `DetailedResolutionClass` engine**: two-pass pixel clock & refresh refinement (`MinTimeCVT = 550000000`, `MinTimeCVTRB = 460000000`, `MinTimeGTF = 550000000`, `CPrime = 30`, `MPrime = 300`, 0.25 MHz / 0.01 MHz step quantization) plus `Exact` & `Exact CRT` and full ToastyX lookup tables |
| **Interlaced `.5` Line Precision** | Integer-only vertical spinboxes (`QSpinBox`), rounding away half-lines | **Preserves `.5` line reductions** (`NoWheelDoubleSpinBox` with `.5` step precision): in `CVT Standard`, `CVT-RB Standard`, and `GTF Standard`, interlaced `Vertical Back Porch` and `Vertical Blanking` / `Vertical Total` preserve their `.5` reduction alongside a live **ToastyX Per-Field** breakdown |
| **Decimal Frequency Precision** | Refresh rate limited to 2 decimals; no editable H-Scan field | **3-decimal precision** for `Refresh Rate (Hz)` and `H-Scan Rate (kHz)`, **2-decimal precision** for `Pixel Clock (MHz)`, plus live `Actual: XXX.XXX Hz / kHz / MHz` readouts |
| **Switch Preset → Manual** | No quick switch button; manual re-entry required | **`✎ Switch to Manual (Keep Values)`** button (and dropdown switch) immediately unlocks all Horizontal, Vertical (including `.5` values), Polarity, Refresh Rate, H-Scan, and Pixel Clock fields with the exact values calculated right before |
| **Manual Mode Anchors** | Fixed calculation order | Radio button anchors for **Timing** (`Back Porch`, `Blanking`, `Total`) and **Frequency** (`Refresh Rate`, `H-Scan Rate`, `Pixel Clock`) |
| **Standard Resolution Popup** | Misaligned `QFormLayout`, clipped dropdown text, no `Height` field | Compact non-scrolling `QGroupBox` grid with side-by-side **`Resolution (H × V)`** (`Width px × Height px`), auto-widening dropdown menus, unified font sizes, automatic vertical grey-out when an aspect ratio (`4:3`, `16:10`, `5:4`, `16:9`) is selected, and **Custom (Width × Height)** manual vertical unlocking |
| **Target Port Dropdown** | Flat list; disconnected ports looked identical to connected ports | Segmented into `── Connected Video Ports ──` (enabled) and `── Disconnected Video Ports ──` / `── Pre-Configure ──` (greyed out) |
| **Profile Folder** | Hidden in `~/.config/linux-cru/profiles` | Stored in **`~/Documents/linux-cru/`** (auto-migrates/discovers `.bin` files from `~/Documents` and `~/.config/linux-cru/profiles`) |
| **UI Scaling, Resize Reflow & Scroll Memory** | Fixed window; clipped text and spinboxes on smaller windows; scroll position reset on resize | `AnchoredScrollArea` viewports that **preserve your exact scroll position** when resizing windows taller and smaller again, `Ctrl + Scroll` / `Ctrl + +/-/0` UI zoom (`75%`–`165%`), and dynamic `resizeEvent` reflow |
| **Installer (`install-linux-cru.sh`)** | Failed when `~/bin` did not exist and exited before creating desktop shortcuts | Installs to `~/.local/bin/linux-cru` & `/usr/local/bin/linux-cru`, creates Start Menu & Desktop shortcuts, and skips redundant `pacman` prompts when `PyQt6` is already installed |

<p align="center">
  <img height="480" alt="Linux CRU Detailed Resolution" src="https://github.com/user-attachments/assets/71e6cabe-7dda-4d9b-9511-ea985bc1bb25" />
  &nbsp;&nbsp;
  <img height="480" alt="Linux CRU Main Window" src="https://github.com/user-attachments/assets/0bb7ed51-2293-4027-aacc-d4b914f4a164" />
</p>

-----------------------------------------------------------------------

## Application Version Catalog & Recent Changes

### Current Application Versions
| Application / Script | Current Version | Description |
| :--- | :--- | :--- |
| **Linux CRU (`install-linux-cru.sh` / `linux-cru`)** | **`v2.1.0`** | Standalone ToastyX-accurate Custom Resolution Utility for Linux with `.5`-line interlaced precision, instant preset-to-Manual handoff, `~/Documents/linux-cru` profile management, and responsive UI scaling |
| **Environment & EDID Setup (`setup-interlace-env.sh`)** | **`v2.0.0`** | Standalone & CLI/GUI-compatible custom EDID firmware, initramfs (`mkinitcpio`, `dracut`, `initramfs-tools`), bootloader (`Limine`, `GRUB`), and live DRM hotplug configurator |
| **15kHz & RDNA Interlace Kernel Patcher (`fix-interlaced-kernel.sh`)** | **`v2.0.0`** | CachyOS / Arch kernel builder with `D0023R/linux_kernel_15khz` patches (`01`–`05`, `07`–`09`) + `11_linux_rdna_dp_hdmi_interlace.patch` and multi-kernel selector (`7.3`, `7.2`, `6.18`, `6.12`, `6.6`, `6.1`, `linux-next`) |

### Recent Changes Log
- **Linux CRU `v2.1.0` (`install-linux-cru.sh`):**
  - Ported ToastyX CRU's exact `DetailedResolutionClass` two-pass timing calculation engine (`CVT Standard`, `CVT-RB Standard`, `CVT-RB2 Standard`, `GTF Standard`, `Automatic CRT/PC/HDTV`, `Native PC/HDTV`, `Exact`, `Exact CRT`, `Manual`).
  - Added `.5`-line vertical timing precision for interlaced modes and 3-decimal frequency precision (`Hz` / `kHz`).
  - Added one-click **`✎ Switch to Manual (Keep Values)`** button and ToastyX-style manual calculation anchors (`Back Porch` / `Blanking` / `Total` and `Refresh Rate` / `H-Scan Rate` / `Pixel Clock`).
  - Redesigned the **Standard Resolution** editor with side-by-side `Horizontal × Vertical` inputs, automatic vertical grey-out when an aspect ratio (`4:3`, `16:10`, `5:4`, `16:9`) is selected, unified font sizing, and full custom `Width × Height` support.
  - Added `AnchoredScrollArea` scroll-position memory across window resizes, `Ctrl + Scroll` UI zoom scaling, segmented `Target Port` dropdowns (connected vs. greyed-out disconnected ports), and `~/Documents/linux-cru` profile storage.
  - Fixed installer failure when `~/bin` is missing and added automatic Start Menu & Desktop launcher creation.
- **Linux Interlacing Suite `v1.0.0` & RDNA DP/HDMI DAC Patch (`11_linux_rdna_dp_hdmi_interlace.patch`):**
  - Added standalone GUI suite (`linux-interlace-suite.py`) with live hardware/kernel/EDID verification cells, Single-GPU vs. Dual-GPU profile selector, DP/HDMI DAC adapter mode selector, and kernel compilation progress tracking.
  - Added `11_linux_rdna_dp_hdmi_interlace.patch` to unlock DP/HDMI DAC dongle timing caps, low/high dotclock HDMI encoder limits, and DCN line-buffer `interleave_en` programming on AMD RDNA 1 / 2 / 3 / 4 GPUs.


