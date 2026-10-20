// Copyright 2026 V83P Studio contributors
// SPDX-License-Identifier: GPL-2.0-or-later
//
// MyKeys per-key RGB protocol, carried over the VIA raw-HID interface (32-byte reports).
// Command IDs 0x40-0x46 are unused by VIA, so VIA keeps working alongside.
//
//   0x40 GET_INFO                    -> [0x40, proto, led_count, enabled, devs]
//   0x41 SET_LEDS  start count rgb*  -> up to 9 LEDs per report (r,g,b each); marks them as set
//   0x42 ENABLE    on                -> 1 = paint set LEDs over the effect, 0 = effect only
//   0x43 CLEAR                       -> unmark all LEDs (effect shows everywhere)
//   0x44 FILL      r g b             -> set every LED to one color
//   0x45 SAVE                        -> store map + enabled flag in EEPROM (survives replug)
//   0x46 LOAD                        -> reload the saved map
//   0x47 GET_LEDS  start count       -> [0x47, start, count, setmask, rgb*] for up to 8 LEDs (v2)
//   0x4F BOOTLOADER                  -> reply, then enter flash mode without wiping settings (v2)
//   0x48 LIVE      on                -> streaming frames (v3): if frames stop for 2 s or the keyboard leaves
//                                       USB mode, it reloads its saved per-key map by itself
//   0x49 UNSET     start count       -> unmark LEDs (the effect shows there again) without touching the rest (v4)
//   0x4A DIM       level             -> the effect at level/255 where no per-key color is set; 255 = normal (v4).
//                                       Not saved; back to 255 when a live session ends
// Any error answers with 0xFF in byte 0, like VIA's id_unhandled.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define MYKEYS_PROTOCOL 4

enum mykeys_command {
    MK_GET_INFO = 0x40,
    MK_SET_LEDS = 0x41,
    MK_ENABLE   = 0x42,
    MK_CLEAR    = 0x43,
    MK_FILL     = 0x44,
    MK_SAVE     = 0x45,
    MK_LOAD       = 0x46,
    MK_GET_LEDS   = 0x47,
    MK_LIVE       = 0x48,
    MK_UNSET      = 0x49,
    MK_DIM        = 0x4A,
    MK_BOOTLOADER = 0x4F,
};

void mykeys_init(void);
void mykeys_task(void);
void mykeys_render(uint8_t led_min, uint8_t led_max);
