# Bundled tools

Third-party programs shipped inside the V83P Studio installer and used by the firmware wizard. They are not
modified. Each keeps its own license; see the source links.

| File | What it does | Source | License |
|---|---|---|---|
| `wb32-dfu-updater_cli.exe` | Reads and writes the keyboard's flash over the WB32 chip's built-in USB bootloader (`-U` backup, `-D` write). Never run with `-t`. | https://github.com/WestberryTech/wb32-dfu-updater | Apache-2.0 |
| `qmk_driver_installer.exe` | Installs the WinUSB driver for the bootloader (`342D:DFA0`), one time, with admin rights. Built on libwdi. | https://github.com/qmk/qmk_driver_installer | GPL-3.0 (libwdi: LGPL-3.0) |
| `drivers.txt` | The driver list given to the installer: only the WB32 bootloader line from QMK's list. | QMK MSYS | — |

Both executables were copied from a QMK MSYS install (`C:\QMK_MSYS`).
