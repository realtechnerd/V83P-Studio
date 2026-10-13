// Copyright 2023 jonylee@hfd (@jonylee1986)
// SPDX-License-Identifier: GPL-2.0-or-later
//
// MyKeys port: inland/v83p + HFD wireless stack (from hfdkb/rkb68).
// Wireless pins come from disassembling the stock V83P firmware (MyKeys docs/findings.md).
#pragma once

#define ENCODER_DEFAULT_POS 0x3

#ifdef BT_MODE_ENABLE
/* Power / mode pins */
#    define BT_CABLE_PIN B8
#    define BT_CHARGE_PIN B9
#    define USB_POWER_EN_PIN A14
/* 3-position switch: C10 high = Bluetooth, C13 high = 2.4G, both low = USB */
#    define BT_MODE_SW_PIN C10
#    define RF_MODE_SW_PIN C13

#    define WLS_KEYBOARD_REPORT_KEYS 6

#    define MD_BT_NAME "V83P-$"

#    define PAIRING_TIMER_INTERVAL 200                 // ms
#    define RECONNECT_TIMER_INTERVAL 500               // ms
#    define PAIRING_TIMER_TIMEOUT ((60 - 7) * 1000)    // ms
#    define RECONNECT_TIMER_TIMEOUT ((30 - 3) * 1000)  // ms
#    define ENTRY_SLEEP_TIMEOUT ((5 * 60 - 37) * 1000) // ms

#    define WL_PROCESS_KEYS(keycode, pressed) bts_process_keys(keycode, pressed, dev_info.devs, keymap_config.no_gui, WLS_KEYBOARD_REPORT_KEYS)

#    define USB_SUSPEND_CHECK_ENABLE

/* Host indicators on the host-select keys 1..5 (Fn+1..3 BT, Fn+4 2.4G, Fn+5 USB) */
#    define LED_HOST_BT1_INDEX 15
#    define LED_HOST_BT2_INDEX 16
#    define LED_HOST_BT3_INDEX 17
#    define LED_HOST_BT4_INDEX 255
#    define LED_HOST_BT5_INDEX 255
#    define LED_HOST_2G4_INDEX 18
#    define LED_HOST_USB_INDEX 19
#    define LED_HOST_BT1_COLOR {0, 0, 0x77}
#    define LED_HOST_BT2_COLOR {0, 0, 0x77}
#    define LED_HOST_BT3_COLOR {0, 0, 0x77}
#    define LED_HOST_BT4_COLOR {0, 0, 0}
#    define LED_HOST_BT5_COLOR {0, 0, 0}
#    define LED_HOST_2G4_COLOR {0, 0x77, 0}
#    define LED_HOST_USB_COLOR {0x77, 0x77, 0x77}
#endif

/* SDB (shutdown) pin of the snled27351 drivers; high = LEDs powered */
#define LED_POWER_EN_PIN A15

/* MyKeys per-key map in EEPROM: magic + enabled + mask[12] + rgb[92][3] */
#define EECONFIG_KB_DATA_SIZE 290

/* RGB Indicator index */
#define LED_CAPS_LOCK_INDEX 44

/* I2C Config for LED Driver */
#define SNLED27351_I2C_ADDRESS_1 SNLED27351_I2C_ADDRESS_GND
#define SNLED27351_I2C_ADDRESS_2 SNLED27351_I2C_ADDRESS_VDDIO
#define I2C1_SDA_PIN B7
#define I2C1_SCL_PIN B6
#define I2C1_SCL_PAL_MODE 4
#define I2C1_OPMODE OPMODE_I2C
#define I2C1_CLOCK_SPEED 400000

/* SPI Config for spi flash*/
#define SPI_DRIVER SPIDQ
#define SPI_SCK_PIN B3
#define SPI_MOSI_PIN B5
#define SPI_MISO_PIN B4
#define SPI_MOSI_PAL_MODE 5

#define EXTERNAL_FLASH_SPI_SLAVE_SELECT_PIN C12
