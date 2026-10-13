"""VIA dynamic macros: 16 slots in one NUL-separated buffer, QMK send-string format.

Step types (as the GUI edits them):
  {"type": "text",  "text": "hello"}
  {"type": "tap"|"down"|"up", "key": <basic keycode 0x04-0xE7>}
  {"type": "delay", "ms": 100}
"""
from .device import Keyboard
from .keymap import read_buffer

CMD_COUNT, CMD_SIZE, CMD_GET, CMD_SET = 0x0C, 0x0D, 0x0E, 0x0F
PREFIX, TAP, DOWN, UP, DELAY = 1, 1, 2, 3, 4
CODES = {"tap": TAP, "down": DOWN, "up": UP}


def encode(steps):
    out = bytearray()
    for s in steps:
        t = s["type"]
        if t == "text":
            text = s["text"].encode("ascii", "ignore").replace(b"\x00", b"")
            out += bytes(b for b in text if b >= 0x20 or b in (0x09, 0x0A))
        elif t in CODES:
            if not 0 < s["key"] <= 0xFF:
                raise ValueError("macros can only use basic keys (no layers/media)")
            out += bytes([PREFIX, CODES[t], s["key"]])
        elif t == "delay":
            out += bytes([PREFIX, DELAY]) + f"{int(s['ms'])}|".encode()
        else:
            raise ValueError(f"unknown macro step {t!r}")
    return bytes(out)


def decode(data: bytes):
    steps, i, text = [], 0, bytearray()

    def flush():
        if text:
            steps.append({"type": "text", "text": text.decode("ascii", "replace")})
            text.clear()

    while i < len(data):
        b = data[i]
        if b == PREFIX and i + 1 < len(data):
            flush()
            code = data[i + 1]
            if code == DELAY:
                j = i + 2
                while j < len(data) and chr(data[j]).isdigit():
                    j += 1
                steps.append({"type": "delay", "ms": int(data[i + 2:j] or b"0")})
                i = j + (1 if j < len(data) and data[j] == ord("|") else 0)
                continue
            kind = {TAP: "tap", DOWN: "down", UP: "up"}.get(code)
            if kind and i + 2 < len(data):
                steps.append({"type": kind, "key": data[i + 2]})
            i += 3
            continue
        text.append(b)
        i += 1
    flush()
    return steps


class Macros:
    def __init__(self, kb: Keyboard):
        self.kb = kb

    def count(self):
        return self.kb.transact([CMD_COUNT])[1]

    def size(self):
        r = self.kb.transact([CMD_SIZE])
        return r[1] << 8 | r[2]

    def read(self):
        """-> list of step lists, one per slot."""
        n, raw = self.count(), read_buffer(self.kb, CMD_GET, self.size())
        parts = raw.split(b"\x00")
        return [decode(parts[i]) if i < len(parts) else [] for i in range(n)]

    def write(self, slots):
        """Write all slots. Raises if they don't fit the buffer."""
        size = self.size()
        blob = b"\x00".join(encode(s) for s in slots) + b"\x00"
        if len(blob) > size:
            raise ValueError(f"macros need {len(blob)} bytes but the keyboard has {size}")
        blob += bytes(size - len(blob))
        # All-or-nothing: QMK ignores every macro while the buffer's last byte is non-zero ("write in
        # progress"). Set that marker first, write the rest, and clear it last. If the write is cut off
        # (cable pulled, switched to wireless), macros just don't play until the next save, instead of
        # playing half-old, half-new garbage.
        last = size - 1
        self._set(last, b"\xff")
        for off in range(0, last, 28):
            self._set(off, blob[off:min(off + 28, last)])
        self._set(last, b"\x00")
        return len(blob.rstrip(b"\x00")) + 1

    def _set(self, off, chunk):
        r = self.kb.transact([CMD_SET, off >> 8, off & 0xFF, len(chunk), *chunk])
        if r[0] != CMD_SET:
            raise RuntimeError("keyboard rejected macro write")

    @staticmethod
    def used_bytes(slots):
        return len(b"\x00".join(encode(s) for s in slots)) + 1
