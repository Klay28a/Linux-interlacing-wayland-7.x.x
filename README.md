# Linux-interlacing-wayland-7.x.x

I used AI to create these scripts to get interlacing working on Linux Wayland. I am not an experienced scripter or coder — use these at your own risk.

Each script in this repository is designed to work completely standalone on its own, or together with the other scripts without conflicting.

-----------------------------------------------------------------------

**setup-interlace-env.sh**

This script automates setting up the Linux environment and bootloader configuration required for CRT monitors, custom EDIDs, and interlaced resolutions on Wayland:

- **Auto-Detects Your Analog Output & Multi-GPU Setup:** Automatically detects your active analog connector (`VGA-1`, `DVI-I-1`, or a user-specified port), forces `amdgpu` instead of the legacy `radeon` driver on Southern Islands (GCN 1.0) and Sea Islands (GCN 1.1) cards, and configures KWin Wayland environment rules (including Dual-GPU Reverse PRIME udev rules when NVIDIA + AMD GPUs are paired).
- **Creates or Converts Your EDID `.bin` File:** Generates a clean Linux-formatted CRT EDID at `/usr/lib/firmware/edid/crufile.bin` (or validates an existing `.bin` file if you pass one in). If you import an EDID exported from Windows ToastyX CRU (which stores half-field vertical lines for interlaced modes), this script automatically converts those interlaced timings to Linux DRM's full-frame vertical format while leaving valid Linux modes untouched.
- **Embeds the EDID in Initramfs & Bootloader `CMDLINE`:** Adds the EDID binary to `/etc/mkinitcpio.conf` (`FILES=(...)`) or `dracut` so it loads during early boot, updates `/etc/default/limine` and/or `/etc/default/grub` with the required kernel parameters (while preserving any other ports' EDID overrides created by `linux-cru`), rebuilds the initramfs, and reloads the EDID live in the running kernel.

If you want to manually add the `CMDLINE` boot configuration with the EDID file pointer, see the first comment by `u/raven2cz` on this Reddit thread:

https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/

Mine is set up like this:

```ini
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"
```

-----------------------------------------------------------------------

**fix-interlaced-kernel.sh**

This script compiles and installs the CachyOS / Arch Linux kernel with the 15kHz and interlaced DRM display patches applied. Run this whenever a kernel update overwrites your patched kernel and causes your interlaced resolutions to disappear:

- **Automatic Kernel Series Matching (7.2.x / 7.3.x+):** Fetches the latest `linux-cachyos` `PKGBUILD` and pulls the matching kernel patch set from `D0023R/linux_kernel_15khz`.
- **Applies Full Interlace & 15kHz DRM Patches:** Copies and applies the official 15kHz and interlace kernel patches (`01`–`05`, `07`–`09`), fixing interlaced mode validation, DCE/DCN interlaced timing calculation, PLL clock limits, DDC probing, and even-field vertical rounding across AMD (`amdgpu`/`radeon`), Intel (`i915`), and DRM KMS drivers.
- **Preserves Custom EDIDs Across Rebuilds:** Compiles the kernel with native CPU optimizations, automatically enables `linux-cachyos-nvidia-open` if installed, ensures all `/usr/lib/firmware/edid/*.bin` files (from either `setup-interlace-env.sh` or `linux-cru`) remain embedded in `/etc/mkinitcpio.conf`, and syncs Limine/GRUB.

Patch source repository for other distributions (such as Debian/Ubuntu/Fedora) if compiling manually:

https://github.com/D0023R/linux_kernel_15khz

-----------------------------------------------------------------------

**install-linux-cru.sh**

This script installs **Linux CRU (`linux-cru`)**, a standalone PyQt6 Custom Resolution Utility for Linux Wayland/DRM modeled after ToastyX CRU, and adds a **Linux CRU** shortcut to your desktop Start Menu:

- **Proper Linux Full-Frame Interlaced Formatting:** When running Windows ToastyX CRU under Wine, interlaced resolutions are exported using half-field vertical lines (for example, `2048x768i` instead of `2048x1536i`), which causes Linux DRM to misread the vertical resolution and double the refresh rate (`2048x768i @ 320Hz`). `linux-cru` natively calculates and encodes full-frame vertical timings (`2048x1536i @ 160Hz`) so interlaced modes appear and work properly in Linux Display Settings. Also automatically converts Windows CRU `.bin` files on import.
- **Verified Timing Presets & Live Manual Calculator:** Includes `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `CVT Standard`, `CVT-RB`, `CVT-RB2`, `GTF Standard`, and full `Manual` editing for both **Detailed Resolutions (4 Slots)** and **Standard Resolutions (8 Slots)**, with live-updating Front/Sync/Back Porch, Blanking, Total, H-Scan (kHz), Refresh Rate (Hz), and Pixel Clock (MHz) calculations.
- **Multi-Port Selection & Per-Port Profiles:** Lets you select any video port across your GPUs (`VGA-1`, `DVI-I-1`, `DVI-D-1`, `DP-1`, `HDMI-A-1`, etc.), pull the `Current Monitor EDID` directly from the display via DRM, edit the `Installed Custom EDID`, or save/load custom `.bin` profiles.
- **Apply Live (No Reboot) & Standalone Bootloader Install:** Includes an **Apply Live (No Reboot)** button that reloads the new EDID into the kernel DRM driver and triggers a display hotplug refresh immediately without rebooting, plus an **Install & Rebuild Initramfs** button that creates the `/usr/lib/firmware/edid/` file, updates your Limine/GRUB `CMDLINE` and `mkinitcpio.conf`, and rebuilds the initramfs without requiring any of the other scripts.

<img width="2661" height="1580" alt="image" src="https://github.com/user-attachments/assets/a2a494d6-c874-46bb-8cda-1cb72e295ca2" />

