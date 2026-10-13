# Phase 1 findings: Inland MK PRO V2 (V83P)

## Hardware / firmware
- USB: `FFFE:001B`, product `V83P`, manufacturer `Inland`, device release `0x0108`.
- **It is real QMK.** The board is in upstream QMK as `keyboards/inland/v83p`:
  - MCU **WB32FQ95**, bootloader **wb32-dfu**. This is a ROM bootloader, so a bad flash
    can always be recovered.
  - RGB driver `snled27351`, **92 LEDs** (82 keys + 10 edge/underglow LEDs), max brightness 180.
  - Bootloader entry: hold top-left key (Esc) while plugging in, or short the BOOT pad under the space bar.
  - Upstream keyboard.json reports device version 1.0.3, but the stock board reports 0x0108.
    So the shipped firmware is a **vendor fork** that probably adds the 2.4G and Bluetooth
    code. Upstream QMK may support **wired only**.

## VIA probe (`tools/probe.py`, log in `probe_log.txt`)
| Query | Result |
|---|---|
| VIA protocol | **12** |
| Layers / macros | 4 / 16 |
| Lighting | rgb_matrix on **custom channel 3** (brightness=59, effect=3, speed=62, hue=218, sat=247) |
| Channels 1/2 (backlight, rgblight) | unhandled |
| SignalRGB per-key protocol (0x21–0x23) | **unhandled** |

## Stock firmware backup (2026-10-12)
- `backup/stock_v83p.bin`: read twice over WB32 DFU (`wb32-dfu-updater_cli -U … -Z 262144`).
  Both reads are identical, SHA-256 `1CCE12B4B144FA6A7B64859301AF0D8AA0CD2BB815DED7899D0CE9FCABAEBDA6`.
  Vector table SP=0x20000400, reset=0x080001B9. About 48 KB of code. USB strings "Inland"/"V83P".
  BT names "V83P-1/2/3". It is not read-protected.
- Restore: DFU (hold Esc + plug in) → `wb32-dfu-updater_cli -D backup/stock_v83p.bin`.
- Entering DFU with Esc (bootmagic) **resets EEPROM**: lighting, the Fn-layer knob and Fn+knob press.
  Restore from `backup/via_backup.json` (done once already).
- Inland's VIA JSON (from Micro Center, not included here): 18 effects (adds SOLID_REACTIVE_NEXUS=17, MULTISPLASH=18),
  custom keycodes CUSTOM(0..5) = BT_HOST1-3, BT_2_4G, BT_USB, BT_VOL. These are HFD's bt_task keycodes.

## Wireless pin map (from disassembling the stock image)
| Function | Pin | Evidence |
|---|---|---|
| UART1 to radio module | A9 TX / A10 RX (AF mode 0x382) | UART1 base 0x40003800 referenced |
| Cable detect / charge status | B8 / B9 (inputs) | init @0x08000C34. B8 is read where RKB68 reads BT_CABLE_PIN (@0x08001092); M90 has them swapped |
| LED driver SDB | A15 (output) | @0x08001740, same as M90 |
| USB_POWER_EN_PIN | A14 (output); high in BT/2.4G, low in USB | GPIOA BSRR writes @0x08000C8A–CBA; identical to HFD RKB68 |
| Mode switch (3-pos) | C10, C13 (inputs) | scan fn @0x08000BCC |
| Win/Mac DIP | C11 (pull-up) | |
| Encoder | A8 + B13 (pull-ups) | @0x08006500, matches upstream |

Mode-switch decode (devs: 0=USB, 1-3=BT hosts, 4=2.4G):
- C10=1, C13=0 → **Bluetooth** (last host)
- C13=1, C10=0 → **2.4G**
- C10=0, C13=0 → **USB**

The differences from M90 (`BT_MODE_SW_PIN` B10, single pin) are the 3-position switch and A14.
Both live in `bt_task.c`, which is source, so they can be adapted. `lib_bts.a` (the radio protocol)
is shared unchanged.

## What this means for per-key RGB
- **Stock firmware:** there's no per-key command. We can control brightness, effect, speed and
  hue/sat globally, live, through VIA channel 3. Whole-board reactive animations work by
  changing these values quickly; per-key colors don't.
- **True per-key + streamed animations** need a custom QMK build of `inland/v83p` with a small
  raw-HID handler (e.g. "set LED i to r,g,b" plus "stream frame"), keeping VIA working.
  Flashing is low risk because of the ROM DFU, but **the board may lose wireless**
  unless the vendor's wireless source can be found.
