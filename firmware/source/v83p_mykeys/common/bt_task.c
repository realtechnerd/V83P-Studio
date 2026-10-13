/**
 * @file bt_task.c
 * @brief
 * @author JoyLee
 * @version 2.0.0
 * @date 2023-04-06
 *
 * @copyright Copyright (c) 2023 Westberry Technology Corp., Ltd
 */

#include QMK_KEYBOARD_H

#include "quantum.h"
#include "uart.h"
#include "report.h"
#include "usb_main.h"
#include "common/bt_task.h"
#include "lib/lib8tion/lib8tion.h"

#define NUM_LONG_PRESS_KEYS (sizeof(long_pressed_keys) / sizeof(long_pressed_keys_t))

#ifdef BT_DEBUG_MODE
#    define BT_DEBUG_INFO(fmt, ...) dprintf(fmt, ##__VA_ARGS__)
#else
#    define BT_DEBUG_INFO(fmt, ...)
#endif

typedef struct {
    uint32_t press_time;
    uint16_t keycode;
    void (*event_cb)(uint16_t);
} long_pressed_keys_t;

dev_info_t dev_info = {0};
bts_info_t bts_info = {
    .bt_name        = {MD_BT_NAME, MD_BT_NAME, MD_BT_NAME},
    .uart_init      = uart_init,
    .uart_read      = uart_read,
    .uart_transmit  = uart_transmit,
    .uart_receive   = uart_receive,
    .uart_available = uart_available,
    .timer_read32   = timer_read32,
};

enum indicator_states {
    INDICATOR_NONE = 0,
    INDICATOR_PAIRING,
    INDICATOR_RECONNECT,
    INDICATOR_PAIRED,
    INDICATOR_OFF,
};

static uint32_t bt_init_time = 0;
// static uint16_t wl_init_time = 0;

static uint32_t USB_switch_time = 0;
static uint8_t  USB_blink_cnt   = 0;

static uint32_t last_total_time = 0;

static uint8_t indicator_status          = INDICATOR_RECONNECT;
static uint8_t indicator_reset_last_time = false;

static uint8_t  EE_CLR_press_cnt  = 0;
static uint32_t EE_CLR_press_time = 0;
static uint8_t  EE_CLR1_press_cnt = 0;
static bool     EE_CLR_flag       = false;

static bool query_vol_flag = false;

static uint32_t key_press_time = 0;
static uint32_t close_rgb_time = 0;

static bool bak_rgb_toggle = false;
static bool sober          = true;
static bool kb_sleep_flag  = false;

static bool led_inited = false;

static const uint8_t rgb_index_table[]          = {LED_HOST_USB_INDEX, LED_HOST_BT1_INDEX, LED_HOST_BT2_INDEX, LED_HOST_BT3_INDEX, LED_HOST_BT4_INDEX, LED_HOST_BT5_INDEX, LED_HOST_2G4_INDEX};
static const uint8_t rgb_index_color_table[][3] = {
    LED_HOST_USB_COLOR, LED_HOST_BT1_COLOR, LED_HOST_BT2_COLOR, LED_HOST_BT3_COLOR, LED_HOST_BT4_COLOR, LED_HOST_BT5_COLOR, LED_HOST_2G4_COLOR,
};

static void long_pressed_keys_hook(void);
static void long_pressed_keys_cb(uint16_t keycode);
static bool process_record_other(uint16_t keycode, keyrecord_t *record);
static void bt_scan_mode(void);
static void bt_used_pin_init(void);

#ifdef RGB_MATRIX_ENABLE
static void open_rgb(void);
static void close_rgb(void);
#endif

// clang-format off
long_pressed_keys_t long_pressed_keys[] = {
  {.keycode = KC_BT1, .press_time = 0, .event_cb = long_pressed_keys_cb},
  {.keycode = KC_BT2, .press_time = 0, .event_cb = long_pressed_keys_cb},
  {.keycode = KC_BT3, .press_time = 0, .event_cb = long_pressed_keys_cb},
  {.keycode = KC_2G4, .press_time = 0, .event_cb = long_pressed_keys_cb},
  {.keycode = EE_CLR, .press_time = 0, .event_cb = long_pressed_keys_cb},
};
// clang-format on

bool get_kb_sleep_flag(void) {
    return kb_sleep_flag;
}

#include "command.h"

void register_mouse(uint8_t mouse_keycode, bool pressed);
/** \brief Utilities for actions. (FIXME: Needs better description)
 *
 * FIXME: Needs documentation.
 */
__attribute__((weak)) void register_code(uint8_t code) {
    if (dev_info.devs) {
        WL_PROCESS_KEYS(code, 1);
        bts_task(dev_info.devs);
        while (bts_is_busy()) {
            wait_ms(1);
        }
    } else {
        if (code == KC_NO) {
            return;

#ifdef LOCKING_SUPPORT_ENABLE
        } else if (KC_LOCKING_CAPS_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            // Resync: ignore if caps lock already is on
            if (host_keyboard_leds() & (1 << USB_LED_CAPS_LOCK)) return;
#    endif
            add_key(KC_CAPS_LOCK);
            send_keyboard_report();
            wait_ms(TAP_HOLD_CAPS_DELAY);
            del_key(KC_CAPS_LOCK);
            send_keyboard_report();

        } else if (KC_LOCKING_NUM_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            if (host_keyboard_leds() & (1 << USB_LED_NUM_LOCK)) return;
#    endif
            add_key(KC_NUM_LOCK);
            send_keyboard_report();
            wait_ms(100);
            del_key(KC_NUM_LOCK);
            send_keyboard_report();

        } else if (KC_LOCKING_SCROLL_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            if (host_keyboard_leds() & (1 << USB_LED_SCROLL_LOCK)) return;
#    endif
            add_key(KC_SCROLL_LOCK);
            send_keyboard_report();
            wait_ms(100);
            del_key(KC_SCROLL_LOCK);
            send_keyboard_report();
#endif

        } else if (IS_BASIC_KEYCODE(code)) {
            // TODO: should push command_proc out of this block?
            if (command_proc(code)) return;

            // Force a new key press if the key is already pressed
            // without this, keys with the same keycode, but different
            // modifiers will be reported incorrectly, see issue #1708
            if (is_key_pressed(code)) {
                del_key(code);
                send_keyboard_report();
            }
            add_key(code);
            send_keyboard_report();
        } else if (IS_MODIFIER_KEYCODE(code)) {
            add_mods(MOD_BIT(code));
            send_keyboard_report();

#ifdef EXTRAKEY_ENABLE
        } else if (IS_SYSTEM_KEYCODE(code)) {
            host_system_send(KEYCODE2SYSTEM(code));
        } else if (IS_CONSUMER_KEYCODE(code)) {
            host_consumer_send(KEYCODE2CONSUMER(code));
#endif

        } else if (IS_MOUSE_KEYCODE(code)) {
            register_mouse(code, true);
        }
    }
}

/** \brief Utilities for actions. (FIXME: Needs better description)
 *
 * FIXME: Needs documentation.
 */
__attribute__((weak)) void unregister_code(uint8_t code) {
    if (dev_info.devs) {
        WL_PROCESS_KEYS(code, 0);
        bts_task(dev_info.devs);
        while (bts_is_busy()) {
            wait_ms(1);
        }
    } else {
        if (code == KC_NO) {
            return;

#ifdef LOCKING_SUPPORT_ENABLE
        } else if (KC_LOCKING_CAPS_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            // Resync: ignore if caps lock already is off
            if (!(host_keyboard_leds() & (1 << USB_LED_CAPS_LOCK))) return;
#    endif
            add_key(KC_CAPS_LOCK);
            send_keyboard_report();
            del_key(KC_CAPS_LOCK);
            send_keyboard_report();

        } else if (KC_LOCKING_NUM_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            if (!(host_keyboard_leds() & (1 << USB_LED_NUM_LOCK))) return;
#    endif
            add_key(KC_NUM_LOCK);
            send_keyboard_report();
            del_key(KC_NUM_LOCK);
            send_keyboard_report();

        } else if (KC_LOCKING_SCROLL_LOCK == code) {
#    ifdef LOCKING_RESYNC_ENABLE
            if (!(host_keyboard_leds() & (1 << USB_LED_SCROLL_LOCK))) return;
#    endif
            add_key(KC_SCROLL_LOCK);
            send_keyboard_report();
            del_key(KC_SCROLL_LOCK);
            send_keyboard_report();
#endif

        } else if (IS_BASIC_KEYCODE(code)) {
            del_key(code);
            send_keyboard_report();
        } else if (IS_MODIFIER_KEYCODE(code)) {
            del_mods(MOD_BIT(code));
            send_keyboard_report();

#ifdef EXTRAKEY_ENABLE
        } else if (IS_SYSTEM_KEYCODE(code)) {
            host_system_send(0);
        } else if (IS_CONSUMER_KEYCODE(code)) {
            host_consumer_send(0);
#endif

        } else if (IS_MOUSE_KEYCODE(code)) {
            register_mouse(code, false);
        }
    }
}

extern void do_code16(uint16_t code, void (*f)(uint8_t));

__attribute__((weak)) void register_code16(uint16_t code) {
    if (dev_info.devs) {
        if (QK_MODS_GET_MODS(code) & 0x1) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RCTL, 1);
            else
                WL_PROCESS_KEYS(KC_LCTL, 1);
        }
        if (QK_MODS_GET_MODS(code) & 0x2) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RSFT, 1);
            else
                WL_PROCESS_KEYS(KC_LSFT, 1);
        }
        if (QK_MODS_GET_MODS(code) & 0x4) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RALT, 1);
            else
                WL_PROCESS_KEYS(KC_LALT, 1);
        }
        if (QK_MODS_GET_MODS(code) & 0x8) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RGUI, 1);
            else
                WL_PROCESS_KEYS(KC_LGUI, 1);
        }
        WL_PROCESS_KEYS(QK_MODS_GET_BASIC_KEYCODE(code), 1);
    } else {
        if (IS_MODIFIER_KEYCODE(code) || code == KC_NO) {
            do_code16(code, register_mods);
        } else {
            do_code16(code, register_weak_mods);
        }
        register_code(code);
    }
}

__attribute__((weak)) void unregister_code16(uint16_t code) {
    if (dev_info.devs) {
        if (QK_MODS_GET_MODS(code) & 0x1) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RCTL, 0);
            else
                WL_PROCESS_KEYS(KC_LCTL, 0);
        }
        if (QK_MODS_GET_MODS(code) & 0x2) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RSFT, 0);
            else
                WL_PROCESS_KEYS(KC_LSFT, 0);
        }
        if (QK_MODS_GET_MODS(code) & 0x4) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RALT, 0);
            else
                WL_PROCESS_KEYS(KC_LALT, 0);
        }
        if (QK_MODS_GET_MODS(code) & 0x8) {
            if (QK_MODS_GET_MODS(code) & 0x10)
                WL_PROCESS_KEYS(KC_RGUI, 0);
            else
                WL_PROCESS_KEYS(KC_LGUI, 0);
        }
        WL_PROCESS_KEYS(QK_MODS_GET_BASIC_KEYCODE(code), 0);
    } else {
        unregister_code(code);
        if (IS_MODIFIER_KEYCODE(code) || code == KC_NO) {
            do_code16(code, unregister_mods);
        } else {
            do_code16(code, unregister_weak_mods);
        }
    }
}

static THD_WORKING_AREA(waThread1, 128);
static THD_FUNCTION(Thread1, arg) {
    (void)arg;
    chRegSetThreadName("blinker");
    while (true) {
        bts_task(dev_info.devs);
        chThdSleepMilliseconds(1);
    }
}

/**
 * @brief bluetooth 初始化函数
 * @param None
 * @return None
 */
void bt_init(void) {
    bts_init(&bts_info);
    bt_used_pin_init();

    // Read the user config from EEPROM
    dev_info.raw = eeconfig_read_user();
    if (!dev_info.raw) {
        dev_info.devs      = DEVS_USB;
        dev_info.last_devs = DEVS_HOST1;
        eeconfig_update_user(dev_info.raw);
    }

    chThdCreateStatic(waThread1, sizeof(waThread1), HIGHPRIO, Thread1, NULL);

    if (dev_info.devs != DEVS_USB) {
        usbDisconnectBus(&USB_DRIVER);
        usbStop(&USB_DRIVER);
        // gpio_set_pin_high(A12);
    }

    gpio_set_pin_output(USB_POWER_EN_PIN);
    if (dev_info.devs != DEVS_USB) {
        gpio_write_pin_high(USB_POWER_EN_PIN);
    } else {
        gpio_write_pin_low(USB_POWER_EN_PIN);
    }

    bt_init_time = timer_read32();
    // wl_init_time = timer_read();
}

/**
 * @brief bluetooth交互任务
 * @param event 当前事件
 * @return None
 */
void bt_task(void) {
    static uint32_t last_time = 0;

    if ((bt_init_time != 0) && (timer_elapsed32(bt_init_time) >= 2000)) {
        bt_init_time = 0;

        bts_send_name(DEVS_HOST1);
        wait_ms(10);

        bts_send_vendor(v_en_sleep_bt);

        switch (dev_info.devs) {
            case DEVS_HOST1: {
                bts_send_vendor(v_host1);
            } break;
            case DEVS_HOST2: {
                bts_send_vendor(v_host2);
            } break;
            case DEVS_HOST3: {
                bts_send_vendor(v_host3);
            } break;
            case DEVS_2_4G: {
                bts_send_vendor(v_2_4g);
            } break;
            default: {
                bts_send_vendor(v_usb);
                dev_info.devs = DEVS_USB;
                eeconfig_update_user(dev_info.raw);
            } break;
        }
    }

    // if ((wl_init_time != 0) && (timer_elapsed(wl_init_time) >= 500)) {
    //     wl_init_time = 0;
    // }

    /* Execute every 1ms */
    if (timer_elapsed32(last_time) >= 1) {
        last_time = timer_read32();

        if (dev_info.devs != DEVS_USB) {
            uint8_t keyboard_led_state = 0;
            led_t  *kb_leds            = (led_t *)&keyboard_led_state;
            kb_leds->raw               = bts_info.bt_info.indictor_rgb_s;
            usb_device_state_set_leds(keyboard_led_state);

#ifdef RGB_MATRIX_ENABLE
            close_rgb();
#endif
        }
    }

    long_pressed_keys_hook();
    // if (!wl_init_time)
    bt_scan_mode();
}

static uint32_t pressed_time = 0;

bool process_record_bt(uint16_t keycode, keyrecord_t *record) {
    bool retval = true;
    // clang-format off
    if (record->event.pressed) {
        BT_DEBUG_INFO("\n\nkeycode = [0x%x], pressed time: [%d]\n\n", keycode, record->event.time);
        BT_DEBUG_INFO("\n devs     = [%d] \
                    \n sleeped       = [%d] \
                    \n low_vol       = [%d] \
                    \n low_vol_offed = [%d] \
                    \n normal_vol    = [%d] \
                    \n pairing       = [%d] \
                    \n paired        = [%d] \
                    \n come_back     = [%d] \
                    \n come_back_err = [%d] \
                    \n mode_switched = [%d] \
                    \n pvol          = [%d]\n\n\n",
                    dev_info.devs,
                    bts_info.bt_info.sleeped,
                    bts_info.bt_info.low_vol,
                    bts_info.bt_info.low_vol_offed,
                    bts_info.bt_info.normal_vol,
                    bts_info.bt_info.pairing,
                    bts_info.bt_info.paired,
                    bts_info.bt_info.come_back,
                    bts_info.bt_info.come_back_err,
                    bts_info.bt_info.mode_switched,
                    bts_info.bt_info.pvol);
        // clang-format on
        pressed_time = timer_read32();

        extern uint8_t indicator_status;
        if (indicator_status != 0) {
            last_total_time = timer_read32();
        }
    }

    retval = process_record_other(keycode, record);

    if (dev_info.devs != DEVS_USB) {
        if (retval != false) {
            while (bts_is_busy()) {
                wait_ms(1);
            }

            if ((keycode > QK_MODS) && (keycode <= QK_MODS_MAX)) {
                if (QK_MODS_GET_MODS(keycode) & 0x1) {
                    if (QK_MODS_GET_MODS(keycode) & 0x10)
                        WL_PROCESS_KEYS(KC_RCTL, record->event.pressed);
                    else
                        WL_PROCESS_KEYS(KC_LCTL, record->event.pressed);
                }
                if (QK_MODS_GET_MODS(keycode) & 0x2) {
                    if (QK_MODS_GET_MODS(keycode) & 0x10)
                        WL_PROCESS_KEYS(KC_RSFT, record->event.pressed);
                    else
                        WL_PROCESS_KEYS(KC_LSFT, record->event.pressed);
                }
                if (QK_MODS_GET_MODS(keycode) & 0x4) {
                    if (QK_MODS_GET_MODS(keycode) & 0x10)
                        WL_PROCESS_KEYS(KC_RALT, record->event.pressed);
                    else
                        WL_PROCESS_KEYS(KC_LALT, record->event.pressed);
                }
                if (QK_MODS_GET_MODS(keycode) & 0x8) {
                    if (QK_MODS_GET_MODS(keycode) & 0x10)
                        WL_PROCESS_KEYS(KC_RGUI, record->event.pressed);
                    else
                        WL_PROCESS_KEYS(KC_LGUI, record->event.pressed);
                }
                retval = WL_PROCESS_KEYS(QK_MODS_GET_BASIC_KEYCODE(keycode), record->event.pressed);
            } else if (IS_BASIC_KEYCODE(keycode)) {
                if (record->event.pressed) {
                    register_code(keycode);
                } else {
                    unregister_code(keycode);
                }
            } else {
                retval = WL_PROCESS_KEYS(keycode, record->event.pressed);
            }
        }
    }

#ifdef RGB_MATRIX_ENABLE
    open_rgb();
#endif

    return retval;
}

void bt_switch_mode(uint8_t last_mode, uint8_t now_mode, uint8_t reset) {
    bool usb_sws = !!last_mode ? !now_mode : !!now_mode;

    if (usb_sws) {
        if (!!now_mode) {
            usbDisconnectBus(&USB_DRIVER);
            usbStop(&USB_DRIVER);
        } else {
            init_usb_driver(&USB_DRIVER);
        }
    }

    dev_info.devs = now_mode;
    if ((dev_info.devs != DEVS_USB) && (dev_info.devs != DEVS_2_4G)) {
        dev_info.last_devs = dev_info.devs;
    } else if (dev_info.devs == DEVS_USB) {
        USB_switch_time = timer_read32();
        USB_blink_cnt   = 0;
    }

    bts_info.bt_info.pairing       = false;
    bts_info.bt_info.paired        = false;
    bts_info.bt_info.come_back     = false;
    bts_info.bt_info.come_back_err = false;
    bts_info.bt_info.mode_switched = false;

    if (dev_info.devs == DEVS_USB) {
        gpio_write_pin_low(USB_POWER_EN_PIN);
    } else {
        gpio_write_pin_high(USB_POWER_EN_PIN);
    }

    bts_info.bt_info.indictor_rgb_s = 0;
    eeconfig_update_user(dev_info.raw);

    switch (dev_info.devs) {
        case DEVS_HOST1: {
            if (reset != false) {
                indicator_status          = INDICATOR_PAIRING;
                indicator_reset_last_time = true;
                // bts_send_name(DEVS_HOST1);
                // bts_send_vendor(v_host1);
                bts_send_vendor(v_pair);
            } else {
                indicator_status          = INDICATOR_RECONNECT;
                indicator_reset_last_time = true;
                bts_send_vendor(v_host1);
            }
        } break;
        case DEVS_HOST2: {
            if (reset != false) {
                indicator_status          = INDICATOR_PAIRING;
                indicator_reset_last_time = true;
                // bts_send_name(DEVS_HOST2);
                // bts_send_vendor(v_host2);
                bts_send_vendor(v_pair);
            } else {
                indicator_status          = INDICATOR_RECONNECT;
                indicator_reset_last_time = true;
                bts_send_vendor(v_host2);
            }
        } break;
        case DEVS_HOST3: {
            if (reset != false) {
                indicator_status          = INDICATOR_PAIRING;
                indicator_reset_last_time = true;
                // bts_send_name(DEVS_HOST3);
                // bts_send_vendor(v_host3);
                bts_send_vendor(v_pair);
            } else {
                indicator_status          = INDICATOR_RECONNECT;
                indicator_reset_last_time = true;
                bts_send_vendor(v_host3);
            }
        } break;
        case DEVS_2_4G: {
            if (reset != false) {
                indicator_status          = INDICATOR_PAIRING;
                indicator_reset_last_time = true;
                // bts_send_name(DEVS_2_4G);
                // bts_send_vendor(v_2_4g);
                bts_send_vendor(v_pair);
            } else {
                indicator_status          = INDICATOR_RECONNECT;
                indicator_reset_last_time = true;
                bts_send_vendor(v_2_4g);
            }
        } break;
        case DEVS_USB: {
            bts_send_vendor(v_usb);
        } break;
        default:
            break;
    }
}

static bool process_record_other(uint16_t keycode, keyrecord_t *record) {
    for (uint8_t i = 0; i < NUM_LONG_PRESS_KEYS; i++) {
        if (keycode == long_pressed_keys[i].keycode) {
            if (record->event.pressed) {
                long_pressed_keys[i].press_time = timer_read32();
            } else {
                long_pressed_keys[i].press_time = 0;
            }
            break;
        }
    }

    switch (keycode) {
        case KC_BT1: {
            if (record->event.pressed) {
                if (dev_info.devs != DEVS_HOST1) {
                    bt_switch_mode(dev_info.devs, DEVS_HOST1, false);
                }
            }
        } break;
        case KC_BT2: {
            if (record->event.pressed) {
                if (dev_info.devs != DEVS_HOST2) {
                    bt_switch_mode(dev_info.devs, DEVS_HOST2, false);
                }
            }
        } break;
        case KC_BT3: {
            if (record->event.pressed) {
                if (dev_info.devs != DEVS_HOST3) {
                    bt_switch_mode(dev_info.devs, DEVS_HOST3, false);
                }
            }
        } break;
        case KC_2G4: {
            if (record->event.pressed) {
                if (dev_info.devs != DEVS_2_4G) {
                    bt_switch_mode(dev_info.devs, DEVS_2_4G, false);
                }
            }
        } break;
        case KC_USB: {
            if (record->event.pressed) {
                if (dev_info.devs != DEVS_USB) {
                    bt_switch_mode(dev_info.devs, DEVS_USB, false);
                }
            }
        } break;
        case BT_VOL: {
            if (record->event.pressed) {
                bts_send_vendor(v_query_vol);
                query_vol_flag = true;
            } else {
                query_vol_flag = false;
            }
        } break;
        case EE_CLR: {
            if (record->event.pressed) {
                EE_CLR1_press_cnt++;
                if (EE_CLR1_press_cnt >= 2) {
                    reset_keyboard();
                }
            } else {
                EE_CLR1_press_cnt = 0;
            }
        } break;

            break; // Skip all further processing of this key
        default:
            return true;
    }

    return false;
}

static void long_pressed_keys_cb(uint16_t keycode) {
    switch (keycode) {
        case KC_BT1: {
            if ((dev_info.devs != DEVS_USB) && (dev_info.devs != DEVS_2_4G)) {
                bt_switch_mode(dev_info.devs, DEVS_HOST1, true);
            }
        } break;
        case KC_BT2: {
            if ((dev_info.devs != DEVS_USB) && (dev_info.devs != DEVS_2_4G)) {
                bt_switch_mode(dev_info.devs, DEVS_HOST2, true);
            }
        } break;
        case KC_BT3: {
            if ((dev_info.devs != DEVS_USB) && (dev_info.devs != DEVS_2_4G)) {
                bt_switch_mode(dev_info.devs, DEVS_HOST3, true);
            }
        } break;
        case KC_2G4: {
            if (dev_info.devs == DEVS_2_4G) {
                bt_switch_mode(dev_info.devs, DEVS_2_4G, true);
            }
        } break;
        case EE_CLR: {
            if (!EE_CLR_flag) {
                EE_CLR_flag       = true;
                EE_CLR_press_time = timer_read32();
                EE_CLR_press_cnt  = 1;
            }
        } break;
        default:
            break;
    }
}

static void long_pressed_keys_hook(void) {
    for (uint8_t i = 0; i < NUM_LONG_PRESS_KEYS; i++) {
        if ((long_pressed_keys[i].press_time != 0) && (timer_elapsed32(long_pressed_keys[i].press_time) >= (3 * 1000))) {
            long_pressed_keys[i].event_cb(long_pressed_keys[i].keycode);
            long_pressed_keys[i].press_time = 0;
        }
    }
}

static void bt_used_pin_init(void) {
#ifdef LED_POWER_EN_PIN
    gpio_set_pin_output(LED_POWER_EN_PIN);
    gpio_write_pin_high(LED_POWER_EN_PIN);
    // gpio_set_pin_output_open_drain(LED_POWER_EN_PIN);
    // gpio_write_pin_low(LED_POWER_EN_PIN);
#endif

#ifdef WL_PWR_SW_PIN
    gpio_set_pin_input_high(WL_PWR_SW_PIN);
#endif

#ifdef BT_CABLE_PIN
    gpio_set_pin_input_high(BT_CABLE_PIN);
#endif

#ifdef BT_CHARGE_PIN
    gpio_set_pin_input(BT_CHARGE_PIN);
#endif

#ifdef BT_MODE_SW_PIN
    // V83P: plain inputs, driven high by the switch (as configured by the stock firmware)
    gpio_set_pin_input(BT_MODE_SW_PIN);
    gpio_set_pin_input(RF_MODE_SW_PIN);
#endif
}

/**
 * @brief 根据波动开关判断工作模式
 * @param None
 * @return None
 */
static void bt_scan_mode(void) {
#ifdef BT_MODE_SW_PIN
    // V83P 3-position switch, active high (decoded from the stock firmware):
    // BT pin high = Bluetooth, RF pin high = 2.4G, both low = USB.
    bool bt = gpio_read_pin(BT_MODE_SW_PIN), rf = gpio_read_pin(RF_MODE_SW_PIN);
    if (bt && !rf) {
        if ((dev_info.devs == DEVS_USB) || (dev_info.devs == DEVS_2_4G)) {
            bt_switch_mode(dev_info.devs, dev_info.last_devs, false); // BT mode
        }
    } else if (rf && !bt) {
        if (dev_info.devs != DEVS_2_4G) {
            bt_switch_mode(dev_info.devs, DEVS_2_4G, false); // 2_4G mode
        }
    } else if (!bt && !rf) {
        if (dev_info.devs != DEVS_USB) {
            bt_switch_mode(dev_info.devs, DEVS_USB, false); // usb mode
        }
    }
#endif
}

static void led_config_all(void) {
    if (!led_inited) {
        led_inited = true;
    }
}
static void led_deconfig_all(void) {
    if (led_inited) {
        led_inited = false;
    }
}

static void close_rgb(void) {
    if (!key_press_time) {
        key_press_time = timer_read32();
        return;
    }

    if (sober) {
        if (kb_sleep_flag || (timer_elapsed32(key_press_time) >= ENTRY_SLEEP_TIMEOUT)) {
            bak_rgb_toggle = rgb_matrix_config.enable;
            sober          = false;
            close_rgb_time = timer_read32();
            rgb_matrix_disable_noeeprom();
#ifdef LED_POWER_EN_PIN
            gpio_write_pin_low(LED_POWER_EN_PIN);
            // writePinHigh(LED_POWER_EN_PIN);
            // setPinOutputOpenDrain(LED_POWER_EN_PIN);
#endif
        }
    } else {
        if (!rgb_matrix_config.enable) {
            if (timer_elapsed32(close_rgb_time) >= ENTRY_STOP_TIMEOUT) {
                /* Turn off all indicators led */
                if (led_inited) {
                    led_deconfig_all();
                }

#ifdef ENTRY_STOP_MODE
                lp_system_sleep();
#endif
                extern void open_rgb(void);
                open_rgb();
            }
        }
    }
}

static void open_rgb(void) {
    key_press_time = timer_read32();

    if (!sober) {
#ifdef LED_POWER_EN_PIN
        gpio_write_pin_high(LED_POWER_EN_PIN);
        // gpio_set_pin_output(LED_POWER_EN_PIN);
        // gpio_write_pin_low(LED_POWER_EN_PIN);
#endif
        if (bak_rgb_toggle) {
            kb_sleep_flag = false;
            extern bool low_vol_offed_sleep;
            low_vol_offed_sleep = false;
            rgb_matrix_enable_noeeprom();
        }
        if (!led_inited) {
            led_config_all();
        }
        sober = true;
    }
}

static void bt_indicator_led(void) {
    if (dev_info.devs != DEVS_USB) {
        uint8_t         rgb_index      = rgb_index_table[dev_info.devs];
        static uint32_t last_time      = 0;
        static uint32_t last_long_time = 0;
        static uint8_t  last_status    = 0;
        static bool     rgb_flip       = false;
        static RGB      rgb            = {0};

        if (last_status != indicator_status) {
            last_status     = indicator_status;
            last_total_time = timer_read32();
        }

        if (indicator_reset_last_time != false) {
            indicator_reset_last_time = false;
            last_time                 = 0;
        }

        switch (indicator_status) {
            case INDICATOR_PAIRING: {
                if ((last_time == 0) || (timer_elapsed32(last_time) >= PAIRING_TIMER_INTERVAL)) {
                    last_time = timer_read32();
                    rgb_flip  = !rgb_flip;
                    if (rgb_flip) {
                        rgb.r = rgb_index_color_table[dev_info.devs][0];
                        rgb.g = rgb_index_color_table[dev_info.devs][1];
                        rgb.b = rgb_index_color_table[dev_info.devs][2];
                    } else {
                        rgb = (RGB){.r = 0, .g = 0, .b = 0};
                    }
                }

                if (bts_info.bt_info.paired) {
                    last_long_time   = timer_read32();
                    indicator_status = INDICATOR_PAIRED;
                    break;
                }

                if (timer_elapsed32(last_total_time) >= PAIRING_TIMER_TIMEOUT) {
                    indicator_status = INDICATOR_NONE;
                    kb_sleep_flag    = true;
                }
            } break;
            case INDICATOR_RECONNECT: {
                if ((last_time == 0) || (timer_elapsed32(last_time) >= RECONNECT_TIMER_INTERVAL)) {
                    last_time = timer_read32();
                    rgb_flip  = !rgb_flip;
                    if (rgb_flip) {
                        rgb.r = rgb_index_color_table[dev_info.devs][0];
                        rgb.g = rgb_index_color_table[dev_info.devs][1];
                        rgb.b = rgb_index_color_table[dev_info.devs][2];
                    } else {
                        rgb = (RGB){.r = 0, .g = 0, .b = 0};
                    }
                }
                if (bts_info.bt_info.paired) {
                    last_long_time   = timer_read32();
                    indicator_status = INDICATOR_PAIRED;
                    break;
                }

                if (timer_elapsed32(last_total_time) >= RECONNECT_TIMER_TIMEOUT) {
                    indicator_status = INDICATOR_NONE;
                    kb_sleep_flag    = true;
                }
            } break;
            case INDICATOR_PAIRED: {
                if ((timer_elapsed32(last_long_time) < (2 * 1000))) {
                    rgb.r = rgb_index_color_table[dev_info.devs][0];
                    rgb.g = rgb_index_color_table[dev_info.devs][1];
                    rgb.b = rgb_index_color_table[dev_info.devs][2];
                } else {
                    indicator_status = INDICATOR_NONE;
                }
            } break;
            case INDICATOR_OFF: {
                rgb = (RGB){.r = 0, .g = 0, .b = 0};
            } break;
            default:
                rgb_flip = false;
                if (!kb_sleep_flag) {
                    if (!bts_info.bt_info.paired) {
                        if (!bts_info.bt_info.pairing) {
                            indicator_status = INDICATOR_RECONNECT;
                            break;
                        }
                        indicator_status = INDICATOR_RECONNECT;
                        if (dev_info.devs == DEVS_2_4G)
                            bt_switch_mode(DEVS_USB, DEVS_2_4G, false);
                        else
                            bt_switch_mode(DEVS_USB, dev_info.last_devs, false);
                        break;
                    }
                }
        }

        if (indicator_status) rgb_matrix_set_color(rgb_index, rgb.r, rgb.g, rgb.b);
    } else {
        static uint32_t USB_blink_time = 0;
        static bool     USB_blink      = false;

        if ((USB_DRIVER.state != USB_ACTIVE)) {
            if (USB_blink_cnt <= 18) {
                if (timer_elapsed32(USB_blink_time) >= 500) {
                    USB_blink_cnt++;
                    USB_blink      = !USB_blink;
                    USB_blink_time = timer_read32();
                }
                if (USB_blink) {
                    rgb_matrix_set_color(rgb_index_table[DEVS_USB], rgb_index_color_table[DEVS_USB][0], rgb_index_color_table[DEVS_USB][1], rgb_index_color_table[DEVS_USB][2]);
                } else {
                    rgb_matrix_set_color(rgb_index_table[DEVS_USB], RGB_BLACK);
                }
            }
            USB_switch_time = timer_read32();
        } else {
            if (timer_elapsed32(USB_switch_time) < (2 * 1000)) {
                rgb_matrix_set_color(rgb_index_table[DEVS_USB], rgb_index_color_table[DEVS_USB][0], rgb_index_color_table[DEVS_USB][1], rgb_index_color_table[DEVS_USB][2]);
            }
        }
    }
}

static void factory_reset_ind(void) {
    if (EE_CLR_flag) {
        if (timer_elapsed32(EE_CLR_press_time) >= EE_CLR_press_cnt * 300) {
            EE_CLR_press_cnt++;
        }
        if (EE_CLR_press_cnt >= 7) {
            EE_CLR_press_time = 0;
            EE_CLR_press_cnt  = 0;
            EE_CLR_flag       = false;
            eeconfig_init();
            eeconfig_update_rgb_matrix_default();

            keymap_config.no_gui = false;
            eeconfig_update_keymap(&keymap_config);

            if ((dev_info.devs != DEVS_USB) && !bts_info.bt_info.paired) {
                if (dev_info.devs == DEVS_2_4G) {
                    bt_switch_mode(dev_info.last_devs, DEVS_2_4G, false);
                } else {
                    bt_switch_mode(dev_info.last_devs, dev_info.devs, false);
                }
            }
        }
        if (EE_CLR_press_cnt % 2) {
            rgb_matrix_set_color_all(100, 100, 100);
        } else {
            rgb_matrix_set_color_all(0, 0, 0);
        }
    }
}

static void bat_voltage_query(void) {
    if (dev_info.devs != DEVS_USB) {
        static uint32_t query_vol_time = 0;

        if (!bt_init_time && !kb_sleep_flag && (bts_info.bt_info.paired) && (timer_elapsed32(query_vol_time) > 4000)) {
            query_vol_time = timer_read32();
            bts_send_vendor(v_query_vol);
        }
    }
}

static void bat_voltage_check(void) {
    if (query_vol_flag) {
        uint8_t pvol = bts_info.bt_info.pvol;

        for (uint8_t i = 68; i <= 74; i++) {
            rgb_matrix_set_color(i, 0, 0, 0);
        }

        uint8_t query_index[] = {74, 73, 72, 71, 70, 69, 68};
        uint8_t led_count     = 0;

        if (pvol >= 95)
            led_count = 7;
        else if (pvol >= 80)
            led_count = 6;
        else if (pvol >= 60)
            led_count = 5;
        else if (pvol >= 40)
            led_count = 4;
        else if (pvol >= 20)
            led_count = 3;
        else if (pvol > 10)
            led_count = 2;
        else if (pvol > 0)
            led_count = 1;
        else
            led_count = 0;

        RGB color = (RGB){14, 14, 14};

        for (uint8_t i = 0; i < led_count; i++) {
            rgb_matrix_set_color(query_index[i], color.r, color.g, color.b);
        }
    }
}

static void bat_low_level_check(void) {
    if (dev_info.devs != DEVS_USB) {
        if (gpio_read_pin(BT_CABLE_PIN)) {
            if (bts_info.bt_info.low_vol_offed) {
                extern bool low_vol_offed_sleep;
                low_vol_offed_sleep = true;
                if (timer_elapsed32(pressed_time) > 2000) {
                    kb_sleep_flag = true;
                }
            }

            if (bts_info.bt_info.low_vol) {
                rgb_matrix_set_color_all(0, 0, 0);

                HSV     hsv        = {0, 255, 0};
                uint8_t time       = scale16by8(g_rgb_timer, qadd8(128 / 4, 1));
                uint8_t brightness = scale8(abs8(sin8(time / 2) - 128) * 2, RGB_MATRIX_DEFAULT_VAL / 2);
                hsv.v              = brightness;
                RGB rgb            = hsv_to_rgb(hsv);

                rgb_matrix_set_color(74, rgb.r, rgb.g, rgb.b);
            }
        }
    }
}

static void devices_state_ind(void) {
    if ((get_highest_layer(default_layer_state | layer_state) == 1) || (get_highest_layer(default_layer_state | layer_state) == 4)) {
        rgb_matrix_set_color(rgb_index_table[dev_info.devs], rgb_index_color_table[dev_info.devs][0], rgb_index_color_table[dev_info.devs][1], rgb_index_color_table[dev_info.devs][2]);
    }
}

bool bt_indicator_rgb(uint8_t led_min, uint8_t led_max) {
    bat_voltage_query();

    bat_low_level_check();

    bat_voltage_check();

    devices_state_ind();

    bt_indicator_led();

    factory_reset_ind();

    return true;
}
