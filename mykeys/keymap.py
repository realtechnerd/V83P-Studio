"""VIA dynamic keymap: keys on every layer, plus the knob (encoder)."""
from .device import Keyboard

ROWS, COLS, ENCODERS = 6, 16, 1
CMD_GET_KEYCODE, CMD_SET_KEYCODE = 0x04, 0x05
CMD_LAYER_COUNT, CMD_GET_BUFFER = 0x11, 0x12
CMD_GET_ENCODER, CMD_SET_ENCODER = 0x14, 0x15


def read_buffer(kb: Keyboard, cmd, total):
    """Read `total` bytes with a VIA buffer command (offset hi, offset lo, size <= 28)."""
    data = bytearray()
    while len(data) < total:
        off, n = len(data), min(28, total - len(data))
        r = kb.transact([cmd, off >> 8, off & 0xFF, n])
        if r[0] != cmd:
            raise RuntimeError(f"command 0x{cmd:02X} unsupported")
        data += r[4:4 + n]
    return bytes(data)


class Keymap:
    def __init__(self, kb: Keyboard):
        self.kb = kb

    def layer_count(self):
        return self.kb.transact([CMD_LAYER_COUNT])[1]

    def read_all(self):
        """-> keymap[layer][row][col] as 16-bit keycodes."""
        layers = self.layer_count()
        raw = read_buffer(self.kb, CMD_GET_BUFFER, layers * ROWS * COLS * 2)
        k = lambda i: raw[i * 2] << 8 | raw[i * 2 + 1]
        return [[[k((l * ROWS + r) * COLS + c) for c in range(COLS)] for r in range(ROWS)]
                for l in range(layers)]

    def set_key(self, layer, row, col, keycode):
        self.kb.transact([CMD_SET_KEYCODE, layer, row, col, keycode >> 8, keycode & 0xFF])

    def get_key(self, layer, row, col):
        r = self.kb.transact([CMD_GET_KEYCODE, layer, row, col])
        return r[4] << 8 | r[5]

    def read_encoders(self):
        """-> encoders[layer] = {"cw": kc, "ccw": kc} for encoder 0."""
        out = []
        for l in range(self.layer_count()):
            cw = self.kb.transact([CMD_GET_ENCODER, l, 0, 1])
            ccw = self.kb.transact([CMD_GET_ENCODER, l, 0, 0])
            out.append({"cw": cw[4] << 8 | cw[5], "ccw": ccw[4] << 8 | ccw[5]})
        return out

    def set_encoder(self, layer, clockwise, keycode):
        self.kb.transact([CMD_SET_ENCODER, layer, 0, 1 if clockwise else 0, keycode >> 8, keycode & 0xFF])
