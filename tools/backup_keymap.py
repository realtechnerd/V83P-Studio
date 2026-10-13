"""Read-only backup of the VIA keymap, encoders and macros to backup/via_backup.json."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mykeys.device import Keyboard  # noqa: E402

ROWS, COLS, ENCODERS = 6, 16, 1
OUT = Path(__file__).resolve().parent.parent / "backup" / "via_backup.json"


def read_buffer(kb, cmd, total):
    data = bytearray()
    while len(data) < total:
        off, n = len(data), min(28, total - len(data))
        r = kb.transact([cmd, off >> 8, off & 0xFF, n])
        if r[0] != cmd:
            raise RuntimeError(f"command 0x{cmd:02X} unsupported (got {r[0]:#x})")
        data += r[4:4 + n]
    return bytes(data)


def main():
    with Keyboard() as kb:
        layers = kb.transact([0x11])[1]
        raw = read_buffer(kb, 0x12, layers * ROWS * COLS * 2)
        keymap = [[[raw[((l * ROWS + r) * COLS + c) * 2] << 8 | raw[((l * ROWS + r) * COLS + c) * 2 + 1]
                    for c in range(COLS)] for r in range(ROWS)] for l in range(layers)]
        encoders = []
        for l in range(layers):
            for e in range(ENCODERS):
                cw = kb.transact([0x14, l, e, 1])
                ccw = kb.transact([0x14, l, e, 0])
                encoders.append({"layer": l, "encoder": e,
                                 "cw": cw[4] << 8 | cw[5], "ccw": ccw[4] << 8 | ccw[5]})
        macro_count = kb.transact([0x0C])[1]
        r = kb.transact([0x0D])
        macro_size = r[1] << 8 | r[2]
        macros = read_buffer(kb, 0x0E, macro_size)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "taken": datetime.now().isoformat(timespec="seconds"),
        "layers": layers, "rows": ROWS, "cols": COLS,
        "keymap": keymap, "encoders": encoders,
        "macro_count": macro_count, "macro_buffer_hex": macros.hex(),
    }, indent=1), encoding="utf-8")
    used = macros.rstrip(b"\x00")
    print(f"Saved {layers} layers, {len(encoders)} encoder entries, "
          f"{macro_count} macro slots ({len(used)} of {macro_size} bytes used) -> {OUT}")


if __name__ == "__main__":
    main()
