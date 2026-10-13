"""Per-key RGB over the MyKeys firmware protocol (see qmk_mykeys/keyboards/inland/v83p_mykeys/mykeys.h).

Stock firmware answers these commands with 0xFF, which detect() reports as unsupported.
"""
import json
from pathlib import Path

from .device import Keyboard

MK_GET_INFO, MK_SET_LEDS, MK_ENABLE, MK_CLEAR, MK_FILL, MK_SAVE, MK_LOAD, MK_GET_LEDS = range(0x40, 0x48)
MK_LIVE, MK_BOOTLOADER = 0x48, 0x4F
PER_REPORT = 9  # LEDs per SET_LEDS report: 3 header bytes + 9 * rgb = 30 of 32
from .boards import current as BOARD

LAYOUT_PATH = BOARD.layout_path


def to_rgb(c):
    if isinstance(c, (tuple, list)):
        return tuple(int(x) for x in c)
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def load_layout():
    """Key name -> LED index, plus LED positions, for the V83P."""
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


class PerKey:
    def __init__(self, kb: Keyboard):
        self.kb = kb
        self.layout = load_layout()
        self.keys = {k.upper(): v for k, v in self.layout["keys"].items()}
        self._sent = {}  # led -> rgb last written, so frames only send changes

    def _cmd(self, *payload):
        r = self.kb.transact(list(payload))
        if r[0] != payload[0]:
            raise RuntimeError(f"keyboard rejected command 0x{payload[0]:02X}")
        return r

    def detect(self):
        """Return (protocol, led_count, enabled, mode) or None on stock firmware."""
        r = self.kb.transact([MK_GET_INFO])
        return None if r[0] != MK_GET_INFO else (r[1], r[2], bool(r[3]), r[4])

    def led(self, key):
        """Key name ('W', 'ESC', 'LSHIFT'...) or LED number -> LED index."""
        if isinstance(key, int) or str(key).isdigit():
            return int(key)
        try:
            return self.keys[str(key).upper()]
        except KeyError:
            raise KeyError(f"unknown key {key!r}; known: {', '.join(sorted(self.keys))}") from None

    def set_leds(self, colors: dict):
        """{led_index: (r,g,b)} -> sends contiguous runs in as few reports as possible."""
        items = sorted((int(i), to_rgb(c)) for i, c in colors.items())
        run = []
        for i, rgb in items + [(None, None)]:
            if run and (i is None or i != run[-1][0] + 1 or len(run) == PER_REPORT):
                start = run[0][0]
                self._cmd(MK_SET_LEDS, start, len(run), *[b for _, c in run for b in c])
                run = []
            if i is not None:
                run.append((i, rgb))
        self._sent.update(dict(items))

    def set_keys(self, colors: dict):
        """{'W': '#ff0000', 'A': (255,0,0)} -> per-key colors (enables the overlay)."""
        self.set_leds({self.led(k): c for k, c in colors.items()})
        self.enable(True)

    def frame(self, colors: list):
        """Full frame of RGB per LED (None = leave effect). Sends only LEDs that changed."""
        changed = {i: c for i, c in enumerate(colors) if c is not None and self._sent.get(i) != to_rgb(c)}
        if changed:
            self.set_leds(changed)

    def stream(self, colors: list):
        """Like frame(), but fire-and-forget (no waiting for replies): for 30 fps music/animations."""
        changed = sorted((i, to_rgb(c)) for i, c in enumerate(colors)
                         if c is not None and self._sent.get(i) != to_rgb(c))
        run = []
        for i, rgb in changed + [(None, None)]:
            if run and (i is None or i != run[-1][0] + 1 or len(run) == PER_REPORT):
                self.kb.send([MK_SET_LEDS, run[0][0], len(run), *[b for _, c in run for b in c]])
                run = []
            if i is not None:
                run.append((i, rgb))
        self._sent.update(dict(changed))
        return len(changed)

    def fill(self, color):
        r, g, b = to_rgb(color)
        self._cmd(MK_FILL, r, g, b)
        self._sent = {i: (r, g, b) for i in range(self.layout["led_count"])}

    def clear(self):
        self._cmd(MK_CLEAR)
        self._sent = {}

    def enable(self, on=True):
        self._cmd(MK_ENABLE, 1 if on else 0)

    def save(self):
        self._cmd(MK_SAVE)

    def read_all(self):
        """{led: '#rrggbb'} for every LED with a custom color, as the keyboard has it (protocol 2+)."""
        n, out = self.layout["led_count"], {}
        for start in range(0, n, 8):
            count = min(8, n - start)
            r = self._cmd(MK_GET_LEDS, start, count)
            for k in range(count):
                if r[3] >> k & 1:
                    out[start + k] = "#%02x%02x%02x" % tuple(r[4 + 3 * k:7 + 3 * k])
        self._sent = {i: to_rgb(c) for i, c in out.items()}
        return out

    def live(self, on=True):
        """Protocol 3+: mark the overlay as a live stream. The keyboard reloads its saved lighting by itself
        if frames stop for 2 s or it leaves USB mode."""
        self._cmd(MK_LIVE, 1 if on else 0)

    def live_ping(self):
        """Keep-alive for the live watchdog (fire-and-forget, used while frames don't change)."""
        self.kb.send([MK_LIVE, 1])

    def bootloader(self):
        """Enter flash mode without wiping settings (protocol 2+)."""
        self._cmd(MK_BOOTLOADER)

