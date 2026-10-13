"""Build mykeys/data/keycodes.json (the key picker catalog) from QMK's keycode spec.

Input: tools/qmk_keycodes_spec.json (made by tools/export_qmk_keycodes.py under QMK MSYS).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tools" / "qmk_keycodes_spec.json"
OUT = ROOT / "mykeys" / "data" / "keycodes.json"
LAYERS = ["Windows", "Windows Fn", "Mac", "Mac Fn"]

BOARD = [  # QK_KB_0.. in keyboard.json order (same as the stock VIA JSON)
    ("KC_BT1", "BT 1", "Bluetooth host 1 (hold to pair)"),
    ("KC_BT2", "BT 2", "Bluetooth host 2 (hold to pair)"),
    ("KC_BT3", "BT 3", "Bluetooth host 3 (hold to pair)"),
    ("KC_2G4", "2.4G", "2.4 GHz dongle (hold to pair)"),
    ("KC_USB", "USB", "Wired USB mode"),
    ("BT_VOL", "Batt", "Show battery level"),
]
SPECIAL = {"QK_BOOTLOADER": "Flash mode", "QK_REBOOT": "Reboot", "QK_CLEAR_EEPROM": "Factory reset",
           "QK_GRAVE_ESCAPE": "Esc / `", "QK_MAGIC_TOGGLE_GUI": "Win lock",
           "QK_MAGIC_TOGGLE_NKRO": "NKRO toggle", "QK_MAGIC_SWAP_CONTROL_CAPS_LOCK": "Caps↔Ctrl",
           "QK_MAGIC_UNSWAP_CONTROL_CAPS_LOCK": "Caps↔Ctrl off", "QK_MAGIC_SWAP_ESCAPE_CAPS_LOCK": "Caps↔Esc",
           "QK_MAGIC_UNSWAP_ESCAPE_CAPS_LOCK": "Caps↔Esc off", "QK_LOCK": "Key lock"}


def short(key, aliases):
    names = [key] + list(aliases or [])
    return min(names, key=len)


def basic_group(name, value):
    if 0x04 <= value <= 0x1D: return "Letters"
    if 0x1E <= value <= 0x27: return "Numbers"
    if 0x3A <= value <= 0x45 or 0x68 <= value <= 0x73: return "Function"
    if 0x53 <= value <= 0x67: return "Numpad"
    if value in range(0x49, 0x53) or value in (0x46, 0x47, 0x48): return "Navigation"
    if value in (0x29, 0x2A, 0x2B, 0x2C, 0x28, 0x39, 0x65): return "Editing"
    return "Symbols"


def main():
    spec = json.loads(SPEC.read_text())
    out = []

    def add(value, name, label, group, desc=None):
        out.append({"value": value, "name": name, "label": label, "group": group, **({"desc": desc} if desc else {})})

    for hexv, kc in spec["keycodes"].items():
        v, g, key = int(hexv, 16), kc.get("group"), kc["key"]
        name, label = short(key, kc.get("aliases")), kc.get("label", key)
        if g == "internal":
            add(v, name, {"KC_NO": "None", "KC_TRANSPARENT": "▽"}.get(key, label), "Basic",
                "Does nothing" if v == 0 else "Use the key from the layer below")
        elif g == "basic" and v <= 0xFF:
            add(v, name, label, basic_group(key, v))
        elif g == "modifiers":
            add(v, name, label.replace("Left ", "L").replace("Right ", "R"), "Modifiers")
        elif g in ("media", "system"):
            add(v, name, label, "Media")
        elif g == "mouse":
            add(v, name, re.sub(r"^Mouse ", "", label), "Mouse")
        elif g == "rgb_matrix":
            add(v, name, label.replace("RGB Matrix ", ""), "Lighting")
        elif g == "macro" and v - 0x7700 < 16:
            add(v, f"M{v - 0x7700}", f"Macro {v - 0x7700}", "Macros")
        elif key in SPECIAL:
            add(v, name, SPECIAL[key], "Special")

    for i, (name, label, desc) in enumerate(BOARD):
        add(0x7E00 + i, name, label, "Wireless", desc)

    for layer, title in enumerate(LAYERS):
        add(0x5220 + layer, f"MO({layer})", f"Hold {title}", "Layers", f"Use the {title} layer while held")
        add(0x5260 + layer, f"TG({layer})", f"Toggle {title}", "Layers", f"Switch the {title} layer on/off")
        add(0x5200 + layer, f"TO({layer})", f"Go to {title}", "Layers")
        add(0x5280 + layer, f"OSL({layer})", f"Once {title}", "Layers", "Next key only")
        add(0x5240 + layer, f"DF({layer})", f"Default {title}", "Layers")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=0, ensure_ascii=False), encoding="utf-8")
    groups = {}
    for k in out:
        groups[k["group"]] = groups.get(k["group"], 0) + 1
    print(len(out), "keycodes:", groups)


if __name__ == "__main__":
    main()
