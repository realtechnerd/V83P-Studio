"""Read-only probe of the Inland MK PRO V2 (V83P, FFFE:001B) VIA raw-HID interface.

Sends only query commands. Never sends bootloader jump (0x0B), EEPROM reset,
save, or any set/write command. Close VIA before running.
"""
import sys
import time
from pathlib import Path

import hid

VID, PID = 0xFFFE, 0x001B
USAGE_PAGE, USAGE = 0xFF60, 0x61
REPORT_LEN = 32
LOG = Path(__file__).resolve().parent.parent / "probe_log.txt"

lines = []


def log(msg=""):
    print(msg)
    lines.append(msg)


def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


def open_device():
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE:
            dev = hid.device()
            dev.open_path(d["path"])
            log(f"Opened {d['product_string']!r} by {d['manufacturer_string']!r} "
                f"release=0x{d['release_number']:04X} interface={d['interface_number']}")
            return dev
    sys.exit("VIA raw-HID interface not found. Is the keyboard plugged in by USB?")


def query(dev, label, payload, timeout_ms=300):
    buf = bytes(payload) + bytes(REPORT_LEN - len(payload))
    dev.write(b"\x00" + buf)  # leading 0x00 = report ID
    resp = bytes(dev.read(REPORT_LEN, timeout_ms))
    if not resp:
        status = "NO RESPONSE"
    elif resp[0] == 0xFF:
        status = "UNHANDLED (0xFF)"
    elif resp == buf:
        status = "ECHO (unchanged)"
    else:
        status = "ok"
    log(f"{label:<38} -> [{status}] {hexs(resp[:12]) if resp else ''}")
    time.sleep(0.02)
    return resp


def main():
    dev = open_device()
    try:
        log("\n== VIA core ==")
        r = query(dev, "0x01 get_protocol_version", [0x01])
        proto = (r[1] << 8 | r[2]) if r else 0
        log(f"   VIA protocol version = {proto} (0x{proto:04X})")

        for vid, name in [(1, "uptime"), (2, "layout_options"), (3, "switch_matrix_state"),
                          (4, "firmware_version")]:
            query(dev, f"0x02 get_keyboard_value {name}", [0x02, vid])

        query(dev, "0x11 dynamic_keymap_get_layer_count", [0x11])
        query(dev, "0x0C macro_get_count", [0x0C])

        log("\n== Lighting, VIA v12 custom channels (0x08 custom_get_value) ==")
        for ch, ch_name, ids in [
            (1, "backlight", {1: "brightness", 2: "effect"}),
            (2, "rgblight", {1: "brightness", 2: "effect", 3: "speed", 4: "color"}),
            (3, "rgb_matrix", {1: "brightness", 2: "effect", 3: "speed", 4: "color"}),
        ]:
            for vid, vname in ids.items():
                query(dev, f"ch{ch} {ch_name}.{vname}", [0x08, ch, vid])

        log("\n== Lighting, legacy (protocol <= 9) 0x08 lighting_get_value ==")
        for vid, vname in [(0x80, "rgbmatrix_brightness"), (0x81, "rgbmatrix_effect"),
                           (0x82, "rgbmatrix_speed"), (0x83, "rgbmatrix_color"),
                           (0x40, "qmk_backlight_brightness"), (0x41, "qmk_backlight_effect")]:
            query(dev, f"legacy {vname}", [0x08, vid])

        log("\n== Per-key protocol probes (info/version commands only) ==")
        query(dev, "SignalRGB 0x21 get_qmk_version", [0x21])
        query(dev, "SignalRGB 0x22 get_protocol_version", [0x22])
        query(dev, "SignalRGB 0x23 get_unique_identifier", [0x23])
    finally:
        dev.close()
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nLog written to {LOG}")


if __name__ == "__main__":
    main()
