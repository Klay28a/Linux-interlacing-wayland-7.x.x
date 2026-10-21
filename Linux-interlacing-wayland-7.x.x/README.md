# Linux-interlacing-wayland-7.x.x

I used AI to create these scripts to get interlacing working on linux wayland. I am not an experienced scripter or coder use these at your own risk.

#setup-interlace-env.sh
This script automates the process for creating the /usr/lib/firmware/edid/ bin file for the bootloader to read from. I believe that it is setup for limine or grub so it will update the boot config for either one after adding the radeon, amdgpu, videoport, and edid file into the CMDLINE. This should be compatible with most distros since its adding a pointer for the edid file.

If you want to manually add the CMDLINE boot conf with the EDID file pointer then go to this reddit page and the first comment should have the proper setup steps. The comment was made by u/raven2cz
https://www.reddit.com/r/archlinux/comments/1lpjz3p/help_setting_custom_edid_for_monitor/

Mine is setup like this
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=17b88c21-6079-4146-af74-bde4fe7209fe radeon.si_support=0 amdgpu.si_support=1 drm.edid_firmware=VGA-1:edid/crufile.bin video=VGA-1:e"

#-------------------------------------------------------------------

#fix-interlaced-kernel.sh
This script is intended to fix the interlacing after a major or recent update. Use this when the resolutions/interlaced resolutions disappear. This script will re-compile the 15khz linux patches 1-5 for 7.2.x kernel versions. 

This is for Arch based distros and it will patch the graphics drivers from amd, nvidia, and intel. Or atleast should. For other distros like debian based, you should be able to compile the 1-5 patches from this repo and possibly get the same result doing it on your own.
https://github.com/D0023R/linux_kernel_15khz



