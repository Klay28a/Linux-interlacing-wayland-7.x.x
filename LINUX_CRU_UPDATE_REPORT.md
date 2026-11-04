# Linux CRU (`install-linux-cru.sh`) — Feature & Update Report

**Repository:** `Klay28a/Linux-interlacing-wayland-7.x.x`  
**Updated File:** `install-linux-cru.sh` (Commit `0bc829b`)  

---

## 1. Overview
This update upgrades **Linux CRU (`linux-cru`)** from a basic approximated timing editor into a **ToastyX CRU-accurate timing & EDID utility** with full decimal & half-line (`.5`) precision, one-click preset-to-Manual handoff, `~/Documents/linux-cru` profile management, and a responsive, zoomable UI inspired by **Safe & Secure Dual-Boot Virtual Monitor** and **Linux CRT Interlacing Suite**.

---

## 2. Feature Changes: Old Repo Version vs. New Version

### A. Timing Calculation Engine & Decimal / `.5` Precision
| Feature | Old Repo Version (`b100506`) | New Version (`0bc829b`) |
| :--- | :--- | :--- |
| **Timing Presets** | Approximated formulas for `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `CVT Standard`, `CVT-RB`, `CVT-RB2`, `GTF Standard`, `Manual` | Ported **ToastyX CRU's exact `DetailedResolutionClass` engine**: `Manual`, `Automatic CRT`, `Automatic PC`, `Automatic HDTV`, `Native PC`, `Native HDTV`, `Exact`, `Exact CRT`, `CVT Standard`, `CVT-RB Standard`, `CVT-RB2 Standard`, `GTF Standard` |
| **Lookup Tables** | Only 4 hardcoded HDTV modes (`1080p/i`, `720p`, `2160p`, `480p/i`) | Full ToastyX lookup tables (`TOASTYX_AUTO_CRT`, `TOASTYX_AUTO_PC`, `TOASTYX_AUTO_HDTV`, `TOASTYX_NATIVE`, `TOASTYX_ASPECT_VSYNC`) with automatic two-pass fallback to `CVT Standard` or `CVT-RB Standard` |
| **Two-Pass Pixel Clock** | Single-pass floating-point approximation | Exact ToastyX two-pass integer calculation (`MinTimeCVT = 550000000`, `MinTimeCVTRB = 460000000`, `MinTimeGTF = 550000000`, `CPrime = 30`, `MPrime = 300`, 0.25 MHz / 0.01 MHz step quantization) |
| **Interlaced `.5` Line Reduction** | Integer-only vertical spinboxes (`QSpinBox`), rounding away half-lines | **Preserves `.5` line reductions** (`NoWheelDoubleSpinBox` with `.5` step precision): in `CVT Standard`, `CVT-RB Standard`, and `GTF Standard`, interlaced `Vertical Back Porch` and `Vertical Blanking` / `Vertical Total` preserve their `.5` reduction alongside a live **ToastyX Per-Field** breakdown |
| **Frequency Decimal Precision** | Refresh rate limited to 2 decimals; no editable H-Scan field | **3-decimal precision** for `Refresh Rate (Hz)` and `H-Scan Rate (kHz)`, **2-decimal precision** for `Pixel Clock (MHz)`, plus live `Actual: XXX.XXX Hz / kHz / MHz` readouts |

---

### B. Instant Preset → Manual Switching & Manual Anchors
| Feature | Old Repo Version | New Version |
| :--- | :--- | :--- |
| **Switch to Manual Workflow** | Selecting `Manual` required manual re-entry; no dedicated action button | Added **`✎ Switch to Manual (Keep Values)`** button right next to the `Timing` dropdown (and selecting `Manual` from the dropdown also preserves values). Clicking it from `GTF Standard`, `CVT Standard`, `Automatic CRT`, etc. immediately unlocks all timing & frequency fields with the exact values calculated right before |
| **Manual Timing Anchors** | Fixed calculation order | Added ToastyX-style radio anchors for **Timing Parameters** (`Back Porch`, `Blanking`, or `Total`) and **Frequency Parameters** (`Refresh Rate`, `H-Scan Rate`, or `Pixel Clock`) so you control which field is computed when editing in `Manual` mode |

---

### C. Standard Resolution Editor (`StandardResDialog`)
| Feature | Old Repo Version | New Version |
| :--- | :--- | :--- |
| **Vertical Resolution (Height)** | No `Height` field at all; only allowed entering `Width` and `Aspect Ratio` | Side-by-side **`Resolution (H × V)`** (`Width px × Height px`) spinboxes with two Custom modes:<br>1. **`Custom (By Aspect Ratio)`**: Select `16:10`, `4:3`, `5:4`, or `16:9` and enter `Width`; `Vertical (Height)` auto-calculates and **greys out** to indicate aspect-ratio lock.<br>2. **`Custom (Width × Height)`**: Unlocks both `Width` and `Height` for direct editing (and offers adding non-standard aspect ratio resolutions to a Detailed Resolution slot) |
| **Popup Layout & Alignment** | Misaligned `QFormLayout` labels and clipped combo box text | Compact, non-scrolling `QGroupBox` grid where everything fits without cutoffs, unified font sizes across labels/inputs/dropdown popups, auto-widening dropdown menus, and a live resolution preview box |

---

### D. UI Scaling, Responsive Reflow & Port / Profile Management
| Feature | Old Repo Version | New Version |
| :--- | :--- | :--- |
| **Header & Title** | Unstyled window | Clean top header with **Title + `🔍 100%` Zoom Button** (no subtitle clutter) and a status banner card with port status badge |
| **Target Port Dropdown** | Flat list of ports; disconnected ports looked identical to active ones | **Suite-style segmented dropdown**: groups `── Connected Video Ports ──` (`● PORT (card, connected)`) at the top and greys out `── Disconnected Video Ports ──` and `── Pre-Configure / Unlisted Ports ──` (`○ PORT`) |
| **Profile Storage Location** | Hidden in `~/.config/linux-cru/profiles` | Saved in **`~/Documents/linux-cru/`** (auto-discovers & migrates `.bin` profiles from `~/Documents` and `~/.config/linux-cru/profiles`) so saved `.bin` files are in Documents and selectable in `EDID Profile` |
| **Window Resizing, Scroll Memory & Scaling** | Fixed layouts; text and spinboxes cut off when resized smaller; scroll position reset when resizing | `AnchoredScrollArea` viewports that **preserve your exact scroll position** when resizing windows taller and smaller again, `Ctrl + Scroll` / `Ctrl + +/-/0` UI zoom (`75%`–`165%`), and dynamic `resizeEvent` reflow so controls stack cleanly without clipping |
| **Installer (`install-linux-cru.sh`)** | Failed when `~/bin` did not exist and exited before creating shortcuts | Installs to `~/.local/bin/linux-cru` & `/usr/local/bin/linux-cru`, creates Start Menu & Desktop shortcuts, and skips redundant `pacman` prompts when `PyQt6` is already installed |
