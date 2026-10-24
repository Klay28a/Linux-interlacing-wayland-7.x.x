# Linux-interlacing-wayland-7.x.x

I used AI to create these scripts to get interlacing working on Linux Wayland. I am not an experienced scripter or coder — use these at your own risk.

-----------------------------------------------------------------------

**setup-interlace-env.sh**

*Compatibility: Arch / CachyOS, Debian / Ubuntu, Fedora, openSUSE (Supports Limine and GRUB bootloaders; mkinitcpio, dracut, and initramfs-tools).*

This script automates setting up your custom EDID file in `/usr/lib/firmware/edid/` and configuring your bootloader so the kernel loads it on boot.

- Detects your active analog video port (`VGA-1`, `DVI-I-1`, or a specified port), sets older GCN 1.0/1.1 AMD cards to use `amdgpu` instead of `radeon`, and configures Wayland multi-GPU environment rules if needed.
- Creates a default EDID `.bin` file in `/usr/lib/firmware/edid/` (or uses an existing `.bin` file you provide) and converts any Windows CRU half-field interlaced timings into Linux's full-frame format.
- Adds the EDID file to your initramfs config and updates your **Limine** (`/etc/default/limine`) or **GRUB** (`/etc/default/grub`) `CMDLINE` with the `amdgpu`, `radeon`, `drm.edid_firmware`, and `video` boot parameters, then rebuilds the initramfs.

If you want to manually add the `CMDLINE` boot configuration with the EDID file pointer, see the first comment by `u/raven2cz` on this Reddit thread:

https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/

Mine is set up like this:

```ini
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 radeon.cik_support=0 amdgpu.cik_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"
```

-----------------------------------------------------------------------

**fix-interlaced-kernel.sh**

*Compatibility: Arch Linux / CachyOS (`pacman` / `makepkg`).*

This script pulls the latest CachyOS kernel (`7.x.x`) and compiles it with the 15kHz and interlace patches from `D0023R/linux_kernel_15khz`. Use this whenever a kernel update overwrites your patched kernel and causes your interlaced resolutions to disappear.

- Pulls the latest `linux-cachyos` `PKGBUILD` and the corresponding 15kHz/interlace kernel patches (`01`–`05`, `07`–`09`) for AMD, Intel, and DRM modesetting.
- Compiles and installs the patched kernel with native CPU optimizations (and `nvidia-open` if installed), then updates Limine/GRUB.

For non-Arch distros (such as Debian/Ubuntu or Fedora), you can compile the patches from this repository manually:

https://github.com/D0023R/linux_kernel_15khz

-----------------------------------------------------------------------

**install-linux-cru.sh**

*Compatibility: Arch / CachyOS, Debian / Ubuntu, Fedora, openSUSE.*

This script installs **Linux CRU (`linux-cru`)** and adds a shortcut to your Start Menu. It is a native Linux version of ToastyX CRU built for Wayland/DRM.

- **Linux Full-Frame Interlaced Formatting:** Using Windows CRU through Wine exports interlaced resolutions with halved vertical lines (e.g. `2048x768i @ 320Hz`), because Linux DRM expects the full vertical resolution (`2048x1536i @ 160Hz`) with the interlace flag. `linux-cru` formats interlaced resolutions using full-frame vertical lines so they show up with the correct resolution and refresh rate in Linux Display Settings (and auto-converts Windows CRU `.bin` files on import).
- **Port & Profile Selection:** Lets you pick any video port on your system (`VGA-1`, `DVI-I-1`, `DP-1`, `HDMI-A-1`, etc.) and switch between the `Installed Custom EDID`, `Current Monitor EDID` (pulled straight from the display), or saved `.bin` profiles.
- **Apply Live or Install to Bootloader:** Can reload new EDID changes live into the kernel without rebooting (**Apply Live**), or write the EDID to `/usr/lib/firmware/edid/`, update your Limine/GRUB `CMDLINE`, and rebuild initramfs directly from the app.

<img width="2661" height="1580" alt="image" src="https://github.com/user-attachments/assets/a2a494d6-c874-46bb-8cda-1cb72e295ca2" />


