# V83P Studio firmware source

The firmware in `firmware/*.bin` is QMK for the Inland MK PRO V2 (`inland/v83p`), with the HFD wireless stack and the
per-key module (`mykeys.c` / `mykeys.h`). License: **GPL-2.0-or-later**, like QMK. Files keep their original
copyright headers (QMK, HFD / jonylee1986, JoyLee).

## Build
1. Clone HFD's QMK fork (it has the WB32 wireless code this port is based on) at the commit used for the releases:
   ```
   git clone https://github.com/jonylee1986/qmk_firmware_master.git qmk_mykeys
   cd qmk_mykeys
   git checkout 075891dea437b35c05475c3f2c53f6eb0754a46d
   qmk git-submodule
   ```
2. Copy `v83p_mykeys/` from here to `keyboards/inland/v83p_mykeys/`.
3. Copy HFD's precompiled wireless library into it (not included here, because it's HFD's binary):
   `cp keyboards/hfdkb/cx70/common/lib_bts.a keyboards/inland/v83p_mykeys/common/`
4. Build: `qmk compile -kb inland/v83p_mykeys -km via` (QMK MSYS on Windows, or any Linux / WSL with QMK installed).

   If Windows **Smart App Control** blocks QMK MSYS's compiler ("An Application Control policy has blocked this
   file"), build in WSL Ubuntu instead:
   ```
   sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi pipx git
   pipx install qmk
   ```
   Build inside the Linux file system (e.g. a copy of the tree in `~/qmk_mykeys`, without its `.build` folder):
   it's much faster than `/mnt/c`, and old Windows build files confuse the Linux build. Releases since 2.3.0 are built
   this way (GCC 14.2).

The release version is `device_version` in `keyboard.json` (2.4.0 → USB release 0x0240); the app checks it after an
install.
