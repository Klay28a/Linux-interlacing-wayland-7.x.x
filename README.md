# Linux-interlacing-wayland-7.x.x

I used AI to create these scripts to get interlacing working on Linux Wayland. I am not an experienced scripter or coder — use these at your own risk.

### Getting Started (Download the Scripts)

Open a terminal and run these commands to download the repo, enter the folder with the scripts, and make them executable:

```bash
git clone https://github.com/Klay28a/Linux-interlacing-wayland-7.x.x.git
cd Linux-interlacing-wayland-7.x.x/Linux-interlacing-wayland-7.x.x
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

-----------------------------------------------------------------------

**fix-interlaced-kernel.sh**

*Compatibility: Arch Linux / CachyOS (`pacman` / `makepkg`).*  
*Affects: Linux kernel (`linux-cachyos`), kernel GPU drivers (`amdgpu`, `radeon`, `i915`, `nouveau`), and GPU module/Wayland config files (`/etc/modprobe.d/`, `~/.config/environment.d/`).*

This script pulls the latest CachyOS kernel (`7.x.x`) and compiles it with the 15kHz and interlace patches from `D0023R/linux_kernel_15khz` for GPUs capable of interlacing. Run this whenever a kernel update overwrites your patched kernel and causes your interlaced resolutions to disappear.

- Pulls the latest `linux-cachyos` `PKGBUILD` and applies the 15kHz/interlace patches (`01`–`05`, `07`–`09`) so the kernel and GPU drivers allow interlaced modes.
- Configures older GCN 1.0/1.1 AMD cards to use `amdgpu` instead of `radeon`, sets up multi-GPU Wayland rules if needed, and enables `nvidia-open` if installed.
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
*Affects: Installs `/usr/local/bin/linux-cru` and a Start Menu shortcut (`~/.local/share/applications/linux-cru.desktop`). Using the app's install/apply buttons affects `/usr/lib/firmware/edid/`, live DRM EDID state, and bootloader/initramfs configs.*

This script installs **Linux CRU (`linux-cru`)**, a native Linux version of ToastyX CRU built for Wayland/DRM.

- **Linux Full-Frame Interlaced Formatting:** Using Windows CRU through Wine exports interlaced resolutions with halved vertical lines (e.g. `2048x768i @ 320Hz`), because Linux DRM expects the full vertical resolution (`2048x1536i @ 160Hz`) with the interlace flag. `linux-cru` formats interlaced resolutions using full-frame vertical lines so they show up with the correct resolution and refresh rate in Linux Display Settings (and auto-converts Windows CRU `.bin` files on import).
- **Port & Profile Selection:** Lets you pick any video port (`VGA-1`, `DVI-I-1`, `DP-1`, `HDMI-A-1`, etc.) and switch between the `Installed Custom EDID`, `Current Monitor EDID` (pulled straight from the display), or saved `.bin` profiles.
- **Apply Live or Install to Bootloader:** Can reload new EDID changes live into the kernel without rebooting (**Apply Live**), or write the EDID to firmware, update your bootloader `CMDLINE`, and rebuild initramfs directly from the app.

**Usage:**

Install the app and create the Start Menu shortcut:
```bash
./install-linux-cru.sh
```

Once installed, open **Linux CRU** from your Start Menu or launch it from any terminal with:
```bash
linux-cru
```

<p align="center">
  <img height="460" alt="Linux CRU Detailed Resolution" src="https://github.com/user-attachments/assets/71e6cabe-7dda-4d9b-9511-ea985bc1bb25" />
  &nbsp;&nbsp;
  <img height="460" alt="Linux CRU Main Window" src="https://github.com/user-attachments/assets/0bb7ed51-2293-4027-aacc-d4b914f4a164" />
</p>


