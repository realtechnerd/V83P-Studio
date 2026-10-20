// Copyright 2026 V83P Studio contributors
// SPDX-License-Identifier: GPL-2.0-or-later
#include QMK_KEYBOARD_H
#include <string.h>
#include "lib/lib8tion/lib8tion.h"
#include "raw_hid.h"
#include "mykeys.h"
#include "common/bt_task.h"

#define MK_MAGIC 0x4B // 'K'
#define MK_MASK_BYTES ((RGB_MATRIX_LED_COUNT + 7) / 8)

typedef struct {
    uint8_t magic;
    uint8_t enabled;
    uint8_t mask[MK_MASK_BYTES];
    uint8_t rgb[RGB_MATRIX_LED_COUNT][3];
} mykeys_state_t;

_Static_assert(sizeof(mykeys_state_t) == EECONFIG_KB_DATA_SIZE, "update EECONFIG_KB_DATA_SIZE in config.h");

static mykeys_state_t mk;
static bool           jump_to_bootloader = false;

// Live session watchdog (protocol 3): while the app shows something temporary (music mode, the volume
// meter, a reaction), the overlay and the effect hold throwaway values. If the app goes quiet (closed,
// crashed, cable pulled, PC asleep) or the keyboard leaves USB mode (switched to 2.4G / Bluetooth), the app
// can't restore the user's lighting, so the keyboard does it itself: per-key colors and, since 2.3.0, the
// effect / brightness / color too, all as saved with "Save to keyboard".
#define MK_LIVE_TIMEOUT 2000 // ms without a frame
static bool     live      = false;
static uint32_t live_seen = 0;

static inline bool is_set(uint8_t i) {
    return mk.mask[i >> 3] & (1 << (i & 7));
}

static void load(void) {
    eeconfig_read_kb_datablock(&mk, 0, sizeof(mk));
    if (mk.magic != MK_MAGIC) {
        memset(&mk, 0, sizeof(mk));
        mk.magic = MK_MAGIC;
    }
}

void mykeys_init(void) {
    load();
}

void eeconfig_init_kb_datablock(void) {
    memset(&mk, 0, sizeof(mk));
    mk.magic = MK_MAGIC;
    eeconfig_update_kb_datablock(&mk, 0, sizeof(mk));
}

void mykeys_task(void) {
    if (live && (timer_elapsed32(live_seen) > MK_LIVE_TIMEOUT || dev_info.devs != DEVS_USB)) {
        live = false;
        load();                          // per-key colors as saved with "Save to keyboard"
        rgb_matrix_reload_from_eeprom(); // and the saved effect, brightness, speed and color (reads only)
    }
}

void mykeys_render(uint8_t led_min, uint8_t led_max) {
    mykeys_task();
    if (!mk.enabled) return;
    uint8_t val = rgb_matrix_get_val(); // global brightness still applies (and caps power)
    for (uint8_t i = led_min; i < led_max; i++) {
        if (is_set(i)) {
            rgb_matrix_set_color(i, scale8(mk.rgb[i][0], val), scale8(mk.rgb[i][1], val), scale8(mk.rgb[i][2], val));
        }
    }
}

static bool handle(uint8_t *data, uint8_t length) {
    switch (data[0]) {
        case MK_GET_INFO:
            data[1] = MYKEYS_PROTOCOL;
            data[2] = RGB_MATRIX_LED_COUNT;
            data[3] = mk.enabled;
            data[4] = dev_info.devs;
            return true;

        case MK_SET_LEDS: {
            uint8_t start = data[1], count = data[2];
            if (count > (length - 3) / 3 || start + count > RGB_MATRIX_LED_COUNT) break;
            for (uint8_t n = 0; n < count; n++) {
                uint8_t i = start + n;
                memcpy(mk.rgb[i], &data[3 + n * 3], 3);
                mk.mask[i >> 3] |= 1 << (i & 7);
            }
            live_seen = timer_read32();
            return true;
        }

        case MK_LIVE:
            live      = data[1] ? true : false;
            live_seen = timer_read32();
            return true;

        case MK_ENABLE:
            mk.enabled = data[1] ? 1 : 0;
            return true;

        case MK_CLEAR:
            memset(mk.mask, 0, sizeof(mk.mask));
            return true;

        case MK_FILL:
            for (uint8_t i = 0; i < RGB_MATRIX_LED_COUNT; i++) {
                memcpy(mk.rgb[i], &data[1], 3);
            }
            memset(mk.mask, 0xFF, sizeof(mk.mask));
            return true;

        case MK_SAVE:
            eeconfig_update_kb_datablock(&mk, 0, sizeof(mk));
            return true;

        case MK_LOAD:
            load();
            return true;

        case MK_GET_LEDS: {
            uint8_t start = data[1], count = data[2];
            if (count > 8 || start + count > RGB_MATRIX_LED_COUNT) break;
            uint8_t set = 0;
            for (uint8_t n = 0; n < count; n++) {
                uint8_t i = start + n;
                if (is_set(i)) set |= 1 << n;
                memcpy(&data[4 + n * 3], mk.rgb[i], 3);
            }
            data[3] = set;
            return true;
        }

        case MK_BOOTLOADER:
            jump_to_bootloader = true; // after the reply is sent
            return true;

        default:
            return false; // not ours: let VIA handle it
    }
    data[0] = 0xFF; // bad arguments
    return true;
}

bool via_command_kb(uint8_t *data, uint8_t length) {
    if (!handle(data, length)) return false;
    raw_hid_send(data, length); // VIA expects handled commands to send their own reply
    if (jump_to_bootloader) {
        wait_ms(50);
        reset_keyboard(); // flash mode without the Esc+plug bootmagic (which wipes settings)
    }
    return true;
}
