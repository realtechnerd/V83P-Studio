ifeq ($(strip $(CONSOLE_ENABLE)), yes)
    KEYBOARD_SHARED_EP = no
endif

# HFDKB_WIRELESS_DIR := keyboards/hfdkb_wireless
RULES_MK_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

OPT_DEFS += -DBT_MODE_ENABLE
OPT_DEFS += -DENTRY_STOP_MODE
OPT_DEFS += -DNO_USB_STARTUP_CHECK

UART_DRIVER_REQUIRED = yes

SRC += common/bt_task.c
SRC += common/lp_sleep.c
SRC += common/retarget_suspend.c

LDFLAGS += -L $(RULES_MK_DIR)/common -l_bts

SRC += mykeys.c
