"""Build the board layout (mykeys/boards/inland-mk-pro-v2/layout.json: key -> LED index, positions) from the QMK sources."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT.parent / "qmk_mykeys" / "keyboards" / "inland" / "v83p_mykeys"
OUT = ROOT / "mykeys" / "boards" / "inland-mk-pro-v2" / "layout.json"

RENAME = {"GRV": "GRAVE", "MINS": "MINUS", "EQL": "EQUAL", "BSPC": "BACKSPACE", "LBRC": "LBRACKET",
          "RBRC": "RBRACKET", "BSLS": "BACKSLASH", "SCLN": "SEMICOLON", "QUOT": "QUOTE",
          "ENT": "ENTER", "COMM": "COMMA", "SLSH": "SLASH", "LSFT": "LSHIFT", "RSFT": "RSHIFT",
          "LCTL": "LCTRL", "RCTL": "RCTRL", "LGUI": "WIN", "SPC": "SPACE", "PGUP": "PAGEUP",
          "PGDN": "PAGEDOWN", "MUTE": "KNOB", "MO(WIN_FN)": "FN", "RGHT": "RIGHT"}


def main():
    kb = json.loads((KB / "keyboard.json").read_text())
    layout = kb["layouts"]["LAYOUT_ansi"]["layout"]
    leds = kb["rgb_matrix"]["layout"]
    keymap = (KB / "keymaps" / "via" / "keymap.c").read_text()
    base = re.search(r"\[WIN_B\] = LAYOUT_ansi\((.*?)\),\s*\n\s*\[WIN_FN\]", keymap, re.S).group(1)
    base = re.sub(r"/\*.*?\*/", "", base)
    names = [t.strip() for t in base.split(",")]
    assert len(names) == len(layout), (len(names), len(layout))

    led_of = {tuple(l["matrix"]): i for i, l in enumerate(leds) if "matrix" in l}
    keys, caps = {}, []
    for kc, pos in zip(names, layout):
        name = kc[3:] if kc.startswith("KC_") else kc
        name = RENAME.get(name, name)
        led = led_of.get(tuple(pos["matrix"]))
        if led is not None:
            keys[name] = led
        caps.append({"name": name, "row": pos["matrix"][0], "col": pos["matrix"][1], "x": pos["x"],
                     "y": pos["y"], "w": pos.get("w", 1), "h": pos.get("h", 1), "led": led})
    edge = [i for i, l in enumerate(leds) if "matrix" not in l]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "led_count": len(leds),
        "keys": keys,
        "caps": caps,
        "edge_leds": edge,
        "points": [[l["x"], l["y"]] for l in leds],
    }, indent=1))
    print(f"{len(keys)} keys, {len(edge)} edge LEDs -> {OUT}")


if __name__ == "__main__":
    main()
