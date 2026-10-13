// Copyright 2023 jonylee@hfd (@jonylee1986)
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#define HAL_USE_I2C TRUE
#define HAL_USE_SPI TRUE
#define HAL_USE_SERIAL TRUE // UART1 to the BT/2.4G module

#include_next <halconf.h>
