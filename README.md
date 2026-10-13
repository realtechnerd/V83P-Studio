# V83P Studio

Lighting, keys, macros, music mode and more for the **Inland MK PRO V2** keyboard, without VIA.

## Install
1. Download `V83P-Studio-Setup-<version>.exe` from Releases and run it. Windows SmartScreen may say "Windows protected
   your PC" because the installer isn't code-signed yet: click **More info → Run anyway**.
2. Plug the keyboard in with the cable (switch on **wired**) and open **V83P Studio**.
3. For per-key colors, music mode and reactions: **Device → Firmware → Install firmware**. The wizard backs up your
   keyboard's original firmware first, installs the flash driver if needed (Windows asks once), and walks you through
   the Esc + plug-in step. **Restore a backup** puts the original back at any time.

No Python or other tools needed: everything is in the installer. Your settings, profiles and firmware backups are kept
in `%APPDATA%\V83P Studio`.

## Supported keyboards
| | |
|---|---|
| **Supported** | **Inland MK PRO V2 75%**, in the **Matcha** and **Mint** colorways (QMK board `inland/v83p`, USB ID `FFFE:001B`) |
| **Full features** | Need the V83P Studio firmware (installed from the app): per-key Static / Animated / Off, music mode, reactions, live preview of your real colors |
| **Stock firmware** | Effects, brightness, speed, keymap, macros, knob and profiles work; per-key colors and music mode don't |
| **Not supported** | Any other keyboard, including other Inland models. Razer / Logitech / Corsair and other non-QMK brands won't be: see [OpenRGB](https://openrgb.org) |
| **OS** | Windows 10 / 11 |

The firmware was developed and tested on **one** Matcha unit, so use it at your own risk. The wizard always backs up
the original firmware before the first install.

### Adding a keyboard (for contributors)
Everything board-specific lives in one folder, `mykeys/boards/<board>/`:
- `board.json`: name, USB IDs, layers, RGB effects, music zones, firmware file
- `layout.json`: key and LED positions (generate with `tools/gen_layout.py` from the board's QMK definition)
- `colorways.json`: keycap colors for the on-screen keyboard

That's enough for effects, keymap, macros and knob on a QMK/VIA board. Per-key colors and music mode also need a
firmware port with the per-key module (`mykeys.c` / `mykeys.h`). Close relatives of this board (same maker, same
WB32 chip) such as HFD's M90 and RKB68 are the easiest candidates.

## The app
Closing the window keeps it in the tray. Use the tray menu to switch profiles, toggle music mode, pause, start with
Windows, or quit. Pages: Lighting, Keys, Macros, Knob, Music, Reactions, Profiles and Device; each has a **?** with
how-to help. Editing needs the cable with the switch on **wired**. Everything you save works on 2.4G and Bluetooth too.

## Building from source
- Run it: `pip install -r requirements.txt`, then `cd electron && npm install && npm start` (uses the project folder
  for data).
- Installer: `pip install pyinstaller`, then `cd electron && npm run dist`. This freezes the Python backend into
  `dist/backend` (`tools/build_backend.py`) and builds `dist/installer/V83P-Studio-Setup-<version>.exe`.
- Bundled third-party tools are listed in `vendor/README.md`.

## Command line (from source)
Lighting control for the **Inland MK PRO V2** (QMK `inland/v83p`, USB `FFFE:001B`), without VIA.
It talks to the keyboard over VIA raw HID. Close VIA while this runs.

```
pip install -r requirements.txt
python -m mykeys info                      # current lighting
python -m mykeys set --effect solid_color --color "#ff0000" --brightness 200
python -m mykeys set --effect cycle_spiral --speed 200 --save   # --save writes to the keyboard
python -m mykeys effects --cycle           # step through effects to confirm their names
python -m mykeys play pulse '{"color": "#0080ff", "period": 1.5}' --seconds 5
python -m mykeys run -v                    # reactive service (Ctrl+C restores lighting)
python -m mykeys tray                      # same, with a tray icon
```

Live changes stay in RAM; only `--save` persists them. Lighting returns to its saved state after a replug.

## Reactive rules: `config/rules.json`
- `base`: the lighting while nothing is triggered.
- `app_launch`: a matching process starts → animation plays until it shows a window
  (or `timeout`), then the optional `on_ready` animation plays.
- `foreground`: the animation plays while a matching app is focused.

Animation types: `static`, `firmware` (built-in effect + speed/color), `pulse`, `flash`,
`hue_sweep`, `fade`. Higher `priority` wins when several are active.

## Layout
- `mykeys/device.py`: HID transport (destructive VIA commands are blocked)
- `mykeys/via.py`: rgb_matrix get/set/save (VIA channel 3)
- `mykeys/animations.py`, `mykeys/engine.py`: animation engine
- `mykeys/triggers.py`: app-launch and foreground triggers
- `tools/probe.py`: read-only firmware probe. See `docs/findings.md`.

## Per-key RGB
The stock firmware has no per-key command, so it needs a custom QMK build. See `docs/findings.md`.

## License
V83P Studio is free software under the **GNU General Public License v3.0 or later** (`LICENSE`). The keyboard firmware
is **GPL-2.0-or-later** like QMK, with its source in `firmware/source/`. Bundled third-party tools and libraries keep
their own licenses: see `THIRD_PARTY_NOTICES.md` and `licenses/`.
