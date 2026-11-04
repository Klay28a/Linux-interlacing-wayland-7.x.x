# Linux CRU (`install-linux-cru.sh`) — Feature & Update Report

**Repository:** `Klay28a/Linux-interlacing-wayland-7.x.x`  
**Updated File:** `install-linux-cru.sh`  

---

## 1. Overview
This update upgrades **Linux CRU (`linux-cru`)** from a basic approximated timing editor into a **ToastyX CRU-accurate timing & EDID utility** with full decimal frequency precision, one-click preset-to-Manual handoff, custom vertical resolution support in Standard Resolutions, `~/Documents/linux-cru` profile management, and an updated UI.

---

## 2. Feature Changes: Old Repo Version vs. New Version

### A. Timing Calculation Engine & Decimal Frequency Precision
| Feature | Old Repo Version (`v1.0.0`) | New Version (`v2.1.0`) |
| :--- | :--- | :--- |
| **Timing Presets** | Approximated formulas for `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `CVT Standard`, `CVT-RB`, `CVT-RB2`, `GTF Standard`, `Manual` | Ported **ToastyX CRU's exact `DetailedResolutionClass` engine**: `Manual`, `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `Exact`, `Exact CRT`, `CVT Standard`, `CVT-RB Standard`, `CVT-RB2 Standard`, `GTF Standard` |
| **Lookup Tables** | Only 4 hardcoded HDTV modes (`1080p/i`, `720p`, `2160p`, `480p/i`) | Full ToastyX lookup tables (`TOASTYX_AUTO_CRT`, `TOASTYX_AUTO_PC`, `TOASTYX_AUTO_HDTV`, `TOASTYX_NATIVE`, `TOASTYX_ASPECT_VSYNC`) with automatic two-pass fallback to `CVT Standard` or `CVT-RB Standard` |
| **Two-Pass Pixel Clock** | Single-pass floating-point approximation | Exact ToastyX two-pass integer calculation (`MinTimeCVT = 550000000`, `MinTimeCVTRB = 460000000`, `MinTimeGTF = 550000000`, `CPrime = 30`, `MPrime = 300`, 0.25 MHz / 0.01 MHz step quantization) |
| **Frequency Decimal Precision** | Refresh rate limited to 2 decimals; no editable H-Scan field | **3-decimal precision** for `Refresh Rate (Hz)` and `H-Scan Rate (kHz)`, **2-decimal precision** for `Pixel Clock (MHz)`, plus live `Actual: XXX.XXX Hz / kHz / MHz` readouts |

---

### B. Instant Preset → Manual Switching & Manual Anchors
| Feature | Old Repo Version | New Version |
| :--- | :--- | :--- |
| **Switch to Manual Workflow** | Selecting `Manual` required manual re-entry; no dedicated action button | Added **Switch to Manual (Keep Values)** button right next to the `Timing` dropdown (and selecting `Manual` from the dropdown also preserves values). Clicking it from `GTF Standard`, `CVT Standard`, `Automatic CRT`, etc. immediately unlocks all timing & frequency fields with the exact values calculated right before |
| **Manual Timing Anchors** | Fixed calculation order | Added ToastyX-style radio anchors for **Timing Parameters** (`Back Porch`, `Blanking`, or `Total`) and **Frequency Parameters** (`Refresh Rate`, `H-Scan Rate`, or `Pixel Clock`) so you control which field is computed when editing in `Manual` mode |

---

### C. Standard Resolutions, Port Selection, Profiles & Installer
| Feature | Old Repo Version | New Version |
| :--- | :--- | :--- |
| **Standard Resolutions (Vertical Height)** | Only allowed entering `Width` and `Aspect Ratio` (no vertical resolution input) | Supports both **Custom (By Aspect Ratio)** (auto-calculates height from width) and **Custom (`Width × Height`)** for direct vertical resolution editing |
| **Target Port Selection** | Flat list of ports; disconnected ports looked identical to active ones | Separates active connected ports (`── Connected Video Ports ──`) from disconnected and unlisted ports |
| **Profile Storage Location** | Hidden in `~/.config/linux-cru/profiles` | Saved in **`~/Documents/linux-cru/`** (auto-discovers & migrates `.bin` profiles from `~/Documents` and `~/.config/linux-cru/profiles`) so saved `.bin` files are in Documents and selectable in `EDID Profile` |
| **Installer (`install-linux-cru.sh`)** | Failed when `~/bin` did not exist and exited before creating shortcuts | Installs to `~/.local/bin/linux-cru` & `/usr/local/bin/linux-cru`, creates Start Menu & Desktop shortcuts, and skips redundant `pacman` prompts when `PyQt6` is already installed |
| **UI** | Basic layout | Updated UI |

