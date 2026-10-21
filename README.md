# Linux-interlacing-wayland-7.x.x

I used AI to create these scripts to get interlacing working on linux wayland. I am not an experienced scripter or coder use these at your own risk.

-----------------------------------------------------------------------

**setup-interlace-env.sh**

This script automates the process for creating the /usr/lib/firmware/edid/ bin file for the bootloader to read from. I believe that this will setup for limine and/or grub so it will update the boot config for either one after adding the radeon, amdgpu, videoport, and edid file into the CMDLINE boot config. This should be compatible with most distros since its adding a pointer for the edid file.

If you want to manually add the CMDLINE boot conf with the EDID file pointer then go to this reddit page and the first comment should have the proper setup steps. The comment was made by u/raven2cz

https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/

Mine is setup like this

KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"

-----------------------------------------------------------------------

**fix-interlaced-kernel.sh**

This script is intended to compile the patches for the interlacing and will most likely be used to fix your interlacing after a major or recent update. Use this when the resolutions/interlaced resolutions disappear. This script will re-compile the 15khz linux patches 1-5 for 7.2.x kernel versions. 

This is for Arch based distros and it will patch the graphics drivers from amd, nvidia, and intel. Or atleast should. For other distros like debian based, you should be able to compile the 1-5 patches from this repo and possibly get the same result doing it on your own.

https://github.com/D0023R/linux_kernel_15khz

-----------------------------------------------------------------------

**install-linux-cru.sh**

This installs a basic version of the CRU software but for wayland linux. It can pretty much just make detailed resolutions but it formats interlaced resolutions properly in linux. I found that using CRU with wine, it was creating them like this: 2048x768 I @320hz so i believe it was adding the interlace flag to the already formatted interlace res and then it ends up doubling the vertical refreshrate. This app formats it with the full size of 2048x1536 and then applies the interlace flag. I don't entirely get it but after modifying the vertical resolution it and refresh rate it showed up in in the settings.
 
<img width="2661" height="1580" alt="image" src="https://github.com/user-attachments/assets/a2a494d6-c874-46bb-8cda-1cb72e295ca2" />
