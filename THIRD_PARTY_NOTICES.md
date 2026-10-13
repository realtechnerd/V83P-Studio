# Third-party software

V83P Studio is licensed under the **GNU GPL v3** (see `LICENSE`). It includes or uses the following. Their license
texts are in `licenses/` (and in the installed app's `resources/licenses` folder).

## Bundled programs (run by the firmware wizard, unmodified)
| Program | License | Source |
|---|---|---|
| `wb32-dfu-updater_cli.exe` (Westberry) | Apache-2.0 | https://github.com/WestberryTech/wb32-dfu-updater |
| `qmk_driver_installer.exe` (QMK) | GPL-3.0; built on libwdi, LGPL-3.0 | https://github.com/qmk/qmk_driver_installer, https://github.com/pbatard/libwdi |

## Firmware
| Part | License | Source |
|---|---|---|
| QMK Firmware | GPL-2.0-or-later | https://github.com/qmk/qmk_firmware |
| HFD WB32 keyboard + wireless code | GPL-2.0-or-later (sources); `lib_bts.a` is HFD's precompiled library | https://github.com/jonylee1986/qmk_firmware_master |
| Per-key module and board port | GPL-2.0-or-later | `firmware/source/` |

## App runtime
| Component | License |
|---|---|
| Electron / Chromium / Node.js | MIT / BSD-style and others (Electron's license files are included next to the app) |
| Python | PSF-2.0 |
| hidapi (Python) | BSD-3-Clause / GPL-3.0 (choice) |
| psutil, numpy, SoundCard, pycparser | BSD-3-Clause |
| Pillow | MIT-CMU |
| winrt (pywinrt), cffi | MIT |
| Geist and Geist Mono fonts (Vercel) | SIL OFL 1.1 |
