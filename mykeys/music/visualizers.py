"""Music visualizers: audio snapshot → one RGB tuple (or None) per LED, using real LED positions.

LED coordinates come from the board's layout.json: x 0..224 (left→right), y 0..64 (top→bottom).
"""
import colorsys
import math

import numpy as np

PALETTES = {
    "matcha": ["#1e2a0c", "#7fbf2a", "#c8f06a", "#f4ffe4"],
    "rainbow": None,  # hue by position/level
    "fire": ["#2a0000", "#d11a00", "#ff8a00", "#ffe9a8"],
    "ice": ["#00142e", "#0068ff", "#3fd8ff", "#eafcff"],
    "synthwave": ["#22003f", "#a100ff", "#ff2a9d", "#00e5ff"],
    "album": None,  # filled per song from the album art (falls back to matcha)
}
STYLES = ["spectrum", "mirror", "waterfall", "bass_pulse", "ripple", "fireworks", "sparkle", "zones", "pitch", "wave"]
# physical keycap groups for the "zones" style, from the board definition (board.json → zones)
from ..boards import current as BOARD  # noqa: E402
BASS_KEYS = set(BOARD.info.get("zones", {}).get("bass", []))
HIGH_KEYS = set(BOARD.info.get("zones", {}).get("highs", []))


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Palette:
    def __init__(self, name_or_stops):
        stops = name_or_stops if isinstance(name_or_stops, list) else PALETTES.get(name_or_stops)
        if name_or_stops == "album" and not isinstance(name_or_stops, list):
            stops = PALETTES["matcha"]
        self.stops = [_hex(s) for s in stops] if stops else None

    def __call__(self, x):
        """x 0..1 → (r, g, b) 0..255."""
        x = min(1.0, max(0.0, x))
        if not self.stops:
            r, g, b = colorsys.hsv_to_rgb(x * 0.83, 1, 1)  # red → violet
            return r * 255, g * 255, b * 255
        pos = x * (len(self.stops) - 1)
        i = min(int(pos), len(self.stops) - 2)
        f = pos - i
        a, b = self.stops[i], self.stops[i + 1]
        return tuple(a[k] + (b[k] - a[k]) * f for k in range(3))


def _scale(rgb, k):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))


class Visualizer:
    def __init__(self, layout, bands=16):
        pts = layout["points"]
        self.n = layout["led_count"]
        self.edge = set(layout["edge_leds"])
        self.keys = [i for i in range(self.n) if i not in self.edge]
        self.x = [p[0] for p in pts]
        self.y = [p[1] for p in pts]
        self.bands = bands
        self.col = [min(bands - 1, int(x / 224 * bands)) for x in self.x]
        # row from the bottom (0 = space-bar row … 5 = F-row), from the key y positions
        ys = sorted({round(self.y[i]) for i in self.keys})
        self.row = {i: (len(ys) - 1 - ys.index(round(self.y[i]))) for i in self.keys}
        self.rows = len(ys)
        # underglow: left/right strips, bottom→top
        side = lambda x0: sorted((i for i in self.edge if self.x[i] == x0), key=lambda i: -self.y[i])
        self.vu = (side(0), side(224))
        self.peaks = np.zeros(bands)
        self.rings = []      # beat ripples: (start_time, palette_pos)
        self.phase = 0.0
        self.last_beat_seen = 0.0
        # mirror: distance from the center column → band (bass in the middle)
        self.mcol = [min(bands - 1, int(abs(x - 112) / 112 * bands)) for x in self.x]
        self.history = []    # waterfall: recent spectra, newest first
        self.last_push = 0.0
        self.sparks = {}     # sparkle: led -> (start, palette pos)
        self.rockets = []    # fireworks: (start, x, palette pos)
        names = {v: k for k, v in layout["keys"].items()}
        self.zone = {i: (0 if names.get(i) in BASS_KEYS else 2 if names.get(i) in HIGH_KEYS else 1) for i in self.keys}
        self.hue = 0.0       # pitch style: smoothed hue
        self.rng = np.random.default_rng()

    def frame(self, snap, t, style="spectrum", palette="matcha", vu=True, brightness=1.0):
        pal = Palette(palette)  # a palette name, or a list of hex stops (album colors)
        bands = snap["bands"]
        out = [None] * self.n
        getattr(self, "_" + style, self._spectrum)(out, snap, t, pal, bands)
        if vu:
            self._vu(out, snap, pal)
        if brightness < 1:
            out = [_scale(c, brightness) if c else c for c in out]
        return out

    def _new_beat(self, snap):
        """True once per detected beat. Uses the beat's timestamp: the 0..1 'beat' value fades within
        one audio block (~21 ms), so checking it at 30 fps missed about 1 beat in 3."""
        if snap["beat_t"] > self.last_beat_seen:
            self.last_beat_seen = snap["beat_t"]
            return True
        return False

    # --- styles ---
    def _spectrum(self, out, snap, t, pal, bands):
        self.peaks = np.maximum(np.array(bands), self.peaks - 0.025)
        for i in self.keys:
            level = bands[self.col[i]] * self.rows      # how many rows this column lights
            r = self.row[i]
            peak_row = int(self.peaks[self.col[i]] * self.rows - 0.001)
            if r < level:
                fill = min(1.0, level - r)               # partial top row
                out[i] = _scale(pal(r / (self.rows - 1)), 0.25 + 0.75 * fill)
            elif r == peak_row and self.peaks[self.col[i]] > 0.08:
                out[i] = _scale(pal(1.0), 0.55)          # falling peak dot
            else:
                out[i] = (0, 0, 0)

    def _bass_pulse(self, out, snap, t, pal, bands):
        bass = sum(bands[:3]) / 3
        v = 0.12 + 0.88 * bass ** 1.4
        v = min(1.0, v + 0.35 * math.exp(-max(0.0, t - snap["beat_t"]) / 0.12))  # flash on each beat
        for i in self.keys:
            # a little spatial variation: center glows a bit stronger
            d = abs(self.x[i] - 112) / 112
            out[i] = _scale(pal(0.35 + 0.65 * bass * (1 - 0.3 * d)), v * (1 - 0.25 * d))

    def _ripple(self, out, snap, t, pal, bands):
        if self._new_beat(snap):  # start the ring at the beat's own time, so it's in phase
            self.rings.append((snap["beat_t"], (len(self.rings) * 0.23) % 1))
        self.rings = [(t0, c) for t0, c in self.rings if t - t0 < 1.2][-6:]
        base = 0.06 + 0.2 * snap["energy"]
        cx, cy = 112, 54  # around the space bar
        for i in self.keys:
            d = math.hypot((self.x[i] - cx), (self.y[i] - cy) * 1.6)
            acc = [0.0, 0.0, 0.0]
            for t0, c in self.rings:
                age = t - t0
                k = math.exp(-((d - age * 220) / 18) ** 2) * (1 - age / 1.2)
                if k > 0.01:
                    col = pal(0.4 + 0.6 * c)
                    for j in range(3):
                        acc[j] += col[j] * k
            b = pal(0.15)
            out[i] = tuple(int(min(255, acc[j] + b[j] * base)) for j in range(3))

    def _wave(self, out, snap, t, pal, bands):
        self.phase += 0.004 + 0.03 * snap["energy"]
        v = 0.25 + 0.75 * snap["energy"]
        for i in self.keys:
            x = (self.x[i] / 224 - self.phase) % 1
            out[i] = _scale(pal(0.5 + 0.5 * math.sin(x * 2 * math.pi)), v)

    def _mirror(self, out, snap, t, pal, bands):
        self.peaks = np.maximum(np.array(bands), self.peaks - 0.025)
        for i in self.keys:
            b = self.mcol[i]
            level, r = bands[b] * self.rows, self.row[i]
            if r < level:
                out[i] = _scale(pal(0.25 + 0.75 * b / (self.bands - 1)), 0.3 + 0.7 * min(1.0, level - r))
            elif r == int(self.peaks[b] * self.rows - 0.001) and self.peaks[b] > 0.08:
                out[i] = _scale(pal(1.0), 0.5)
            else:
                out[i] = (0, 0, 0)

    def _waterfall(self, out, snap, t, pal, bands):
        if t - self.last_push > 0.07:  # a new line every ~70 ms → ~0.4 s of history on the board
            self.last_push = t
            self.history = ([list(bands)] + self.history)[: self.rows]
        for i in self.keys:
            age = self.rows - 1 - self.row[i]  # F-row = newest, space-bar row = oldest
            v = self.history[age][self.col[i]] if age < len(self.history) else 0
            out[i] = _scale(pal(v), v ** 1.3 * (1 - 0.1 * age))

    def _sparkle(self, out, snap, t, pal, bands):
        if snap["treble"] > 0.3:
            for i in self.rng.choice(self.keys, size=1 + int(snap["treble"] * 4), replace=False):
                self.sparks[int(i)] = (t, float(self.rng.random()))
        self.sparks = {i: s for i, s in self.sparks.items() if t - s[0] < 0.5}
        base = _scale(pal(0.2), 0.08 + 0.4 * sum(bands[:3]) / 3)
        for i in self.keys:
            s = self.sparks.get(i)
            out[i] = _scale(pal(0.6 + 0.4 * s[1]), 1 - (t - s[0]) / 0.5) if s else base

    def _fireworks(self, out, snap, t, pal, bands):
        if self._new_beat(snap):
            self.rockets.append((snap["beat_t"], float(self.rng.uniform(30, 194)), float(self.rng.random())))
        self.rockets = [r for r in self.rockets if t - r[0] < 1.0][-5:]
        for i in self.keys:
            acc = [0.0, 0.0, 0.0]
            for t0, rx, c in self.rockets:
                age = t - t0
                if age < 0.25:   # rising spark from the space bar
                    ry = 64 - age / 0.25 * 60
                    k = math.exp(-(((self.x[i] - rx) / 10) ** 2 + ((self.y[i] - ry) / 8) ** 2))
                    col = pal(1.0)
                else:            # burst at the top, expanding ring
                    a = age - 0.25
                    d = math.hypot(self.x[i] - rx, (self.y[i] - 6) * 1.5)
                    k = math.exp(-((d - a * 130) / 12) ** 2) * (1 - a / 0.75)
                    col = pal(0.4 + 0.6 * c)
                if k > 0.02:
                    for j in range(3):
                        acc[j] += col[j] * k
            out[i] = tuple(int(min(255, v)) for v in acc)

    def _zones(self, out, snap, t, pal, bands):
        lv = (sum(bands[:4]) / 4, sum(bands[4:11]) / 7, sum(bands[11:]) / 5)  # bass / mids / highs
        for i in self.keys:
            z = self.zone[i]
            out[i] = _scale(pal(0.35 + 0.3 * z), 0.08 + 0.92 * lv[z] ** 0.85)

    def _pitch(self, out, snap, t, pal, bands):
        if snap["pitch_conf"] > 0.25:  # follow the melody, gliding around the hue circle
            d = ((snap["pitch"] - self.hue + 0.5) % 1) - 0.5
            self.hue = (self.hue + d * 0.25) % 1
        r, g, b = colorsys.hsv_to_rgb(self.hue, 0.9, 1)
        v = 0.15 + 0.85 * snap["energy"] ** 0.8
        for i in self.keys:
            k = v * (0.6 + 0.4 * bands[self.col[i]])
            out[i] = (int(r * 255 * k), int(g * 255 * k), int(b * 255 * k))

    def _vu(self, out, snap, pal):
        for strip, level in zip(self.vu, snap["levels"]):
            n = len(strip)
            for k, i in enumerate(strip):
                fill = level * n - k
                out[i] = _scale(pal(k / max(1, n - 1)), min(1.0, max(0.0, fill))) if fill > 0 else (0, 0, 0)
