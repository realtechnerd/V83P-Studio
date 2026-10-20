"""Indicators: the keyboard briefly shows PC state over the user's lighting. Today: the volume meter.

Turn the knob (or change the volume any other way) and the whole keyboard becomes a meter, filling left to right,
then fades back to the user's lighting. Smooth like the built-in effects: the level eases instead of jumping, the edge
is a soft gradient that glides across keys, and it fades in and out. Needs the V83P Studio firmware (per-key colors).
"""
import colorsys
import logging
import math
import threading
import time

from .boards import current as BOARD
from .perkey import to_rgb

log = logging.getLogger(__name__)

FPS = 40
HOLD = 1.5            # seconds after the last volume change
FADE_IN, FADE_OUT = 0.15, 0.4
EASE = 0.15           # time constant of the level following the real volume
SOFT = 0.07           # width of the soft edge (≈ one key)
UNFILLED = 0.15       # unfilled keys: the user's own color at this brightness
MUTE_RGB = (150, 18, 18)
KEEPALIVE = 1.0
ONE_COLOR = {"solid_color", "breathing"}   # effects that show a single steady color on every key
LIVE_MIN = 0.15       # an animated key under the soft edge shows the bar from this much fill on
DEFAULTS = {"enabled": True, "color": "auto"}   # color: "auto" | "gradient" | "#rrggbb"


def _smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def _mix(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def _positions(layout):
    """Where each LED sits along the meter, 0..1: keys left → right, underglow strips bottom → top."""
    pts, edge = layout["points"], set(layout["edge_leds"])
    keys = [i for i in range(layout["led_count"]) if i not in edge]
    x0, x1 = min(pts[i][0] for i in keys), max(pts[i][0] for i in keys)
    out = {i: (pts[i][0] - x0) / ((x1 - x0) or 1) for i in keys}
    if edge:
        y0, y1 = min(pts[i][1] for i in edge), max(pts[i][1] for i in edge)
        out.update({i: 1 - (pts[i][1] - y0) / ((y1 - y0) or 1) for i in edge})
    return out


def volume_frame(positions, level, base, bar, unfilled=UNFILLED, soft=SOFT, alpha=1.0):
    """One frame: base = the user's colors per LED, (r,g,b) or None where the keyboard's own animation shows
    (it can't be dimmed from here, so it keeps running); bar = the meter color.
    alpha blends the whole meter in/out over the user's own lighting (fades). Returns (r,g,b) or None per LED."""
    lvl = level * (1 + soft) - soft / 2          # so 0 % lights nothing and 100 % lights everything
    out = []
    for i, b in enumerate(base):
        f = _smooth((lvl - positions.get(i, 0.0)) / soft + 0.5)
        if b is None:                            # animated key: the animation, or the bar once it's reached
            k = f * alpha
            out.append(None if k < LIVE_MIN else tuple(max(0, min(255, round(v * k))) for v in bar))
            continue
        meter = _mix(tuple(c * unfilled for c in b), bar, f)
        c = _mix(b, meter, alpha)
        out.append(tuple(max(0, min(255, round(v))) for v in c))
    return out


def _hue(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    return h, s, v


def auto_color(accent, colors):
    """The accent, unless the user's lighting is already close to it: then the opposite hue, fully saturated."""
    ah, asat, _ = _hue(accent)
    sx = sy = wsum = 0.0
    for c in colors:                              # saturation-weighted average hue of the user's lighting
        h, s, v = _hue(c)
        w = s * v
        sx += math.cos(2 * math.pi * h) * w
        sy += math.sin(2 * math.pi * h) * w
        wsum += w
    if wsum / max(1, len(colors)) < 0.2 or asat < 0.3:
        return accent                             # mostly white / off / dim: the accent stands out
    dh = (math.atan2(sy, sx) / (2 * math.pi)) % 1
    if min(abs(dh - ah), 1 - abs(dh - ah)) * 360 > 45:
        return accent
    r, g, b = colorsys.hsv_to_rgb((dh + 0.5) % 1, 1.0, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255))


class VolumeMeter:
    def __init__(self, svc):
        self.svc = svc
        self.positions = _positions(svc.layout)
        self.level = self.shown = 0.0
        self.muted = False
        self.since = self.last = 0.0              # meter appeared / last volume change
        self.owns = False                         # streaming over the user's lighting right now
        self._colored = set()                      # LEDs that currently have a per-key color on the keyboard
        self.overlay = False                      # drawn inside music mode's frames instead
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="volume-meter").start()

    # ---------- settings ----------
    @property
    def settings(self):
        return {**DEFAULTS, **self.svc.app_state.get("indicators", {}).get("volume", {})}

    def update(self, changes):
        s = self.settings
        if "enabled" in changes:
            s["enabled"] = bool(changes["enabled"])
        if "color" in changes:
            c = str(changes["color"])
            if c not in ("auto", "gradient") and not (c.startswith("#") and len(c) == 7):
                raise ValueError("color must be auto, gradient or #rrggbb")
            s["color"] = c
        self.svc.app_state.setdefault("indicators", {})["volume"] = s
        self.svc._save_state()
        return s

    # ---------- events ----------
    def on_volume(self, level, muted, force=False):
        svc = self.svc
        if not force and not self.settings["enabled"]:
            return
        if svc.kb is None or not svc.ours() or svc.flashing:
            return
        now = time.monotonic()
        if not (self.owns or self.overlay):
            self.since, self.shown = now, level      # appear at the current level, then follow it
        self.level, self.muted, self.last = level, muted, now
        self._wake.set()

    def shutdown(self):
        self._stop.set()
        self._wake.set()

    # ---------- drawing ----------
    def _alpha(self, now):
        a = min(1.0, (now - self.since) / FADE_IN)
        end = self.last + HOLD
        if now > end:
            a = min(a, 1 - (now - end) / FADE_OUT)
        return max(0.0, a)

    def _bar(self):
        s = self.settings["color"]
        if self.muted:
            return MUTE_RGB
        if s == "gradient":
            r, g, b = colorsys.hsv_to_rgb((1 - self.shown) * 120 / 360, 1.0, 1.0)
            return (r * 255, g * 255, b * 255)
        if s.startswith("#"):
            return to_rgb(s)
        cw = BOARD.colorways.get(self.svc.app_state.get("ui", {}).get("colorway") or BOARD.info.get("default_colorway"), {})
        accent = to_rgb((cw.get("accent", {}).get("dark", {}) or {}).get("accent", "#b9e48f"))
        return auto_color(accent, [c for c in self._base() if c and any(c)])

    def _base(self):
        """The user's lighting per LED: per-key colors from the app's cache. Animated keys: a single-color effect
        (static color, breathing) gives its color; off gives black; anything multi-color (rainbows, spiral, …)
        gives None, so the real animation keeps running there."""
        from .via import EFFECTS
        svc, n = self.svc, self.svc.layout["led_count"]
        st = svc.engine.base if svc.engine else None
        name = EFFECTS.get(st.effect) if st is not None else None
        if name == "off":
            effect_rgb = (0, 0, 0)
        elif name in ONE_COLOR:
            r, g, b = colorsys.hsv_to_rgb(st.hue / 255, st.sat / 255, 1.0)
            effect_rgb = (r * 255, g * 255, b * 255)
        else:
            effect_rgb = None
        cache = svc.app_state.get("perkey", {}) if svc.app_state.get("perkey_enabled") else {}
        return [to_rgb(cache[str(i)]) if str(i) in cache else effect_rgb for i in range(n)]

    def frame_over(self, colors, t=None):
        """Music mode: draw the meter over the music's own frame (colors: list of (r,g,b) or None)."""
        if not self.overlay:
            return colors
        now = time.monotonic()
        base = [c if c else (0, 0, 0) for c in colors]
        return volume_frame(self.positions, self.shown, base, self._bar(), alpha=self._alpha(now))

    def _send(self, frame):
        """Stream a frame. A key going back to None (the animation) needs its per-key color removed, which the
        firmware can only do for all keys at once: clear, then resend the keys that keep a color."""
        pk = self.svc.perkey
        back = {i for i, c in enumerate(frame) if c is None} & self._colored
        if back:
            pk.clear()
            self._colored = set()
        self._colored |= {i for i, c in enumerate(frame) if c is not None}
        return pk.stream(frame)

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                self._show()
            except Exception as e:
                log.warning("volume meter failed: %s", e)
                self.overlay = False
                try:
                    self._restore()
                except Exception:
                    pass

    def _show(self):
        svc = self.svc
        music = getattr(svc, "music", None)
        prev = time.monotonic()
        if self._alpha(prev) <= 0:
            return                                  # a leftover wake-up from changes made while it was showing
        if music is not None and music.active:     # music mode draws it inside its own frames
            self.overlay = True
            while not self._stop.is_set() and self._alpha(time.monotonic()) > 0 and music.active:
                now = time.monotonic()
                self.shown += (self.level - self.shown) * (1 - math.exp(-(now - prev) / EASE))
                prev = now
                self._stop.wait(1 / FPS)
            self._wake.clear()                      # changes during the show were already drawn
            self.overlay = False
            return
        self._take_over()
        live, keep = svc.firmware and (svc.firmware.get("protocol") or 0) >= 3, time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            a = self._alpha(now)
            if a <= 0 or svc.kb is None:
                break
            self.shown += (self.level - self.shown) * (1 - math.exp(-(now - prev) / EASE))
            prev = now
            sent = self._send(volume_frame(self.positions, self.shown, self._base(), self._bar(), alpha=a))
            if live and not sent and now - keep > KEEPALIVE:
                svc.perkey.live_ping()
                keep = now
            elif sent:
                keep = now
            self._stop.wait(max(0.0, 1 / FPS - (time.monotonic() - now)))
        self._wake.clear()                          # changes during the show were already drawn; later ones re-wake
        self._restore()

    def _take_over(self):
        svc = self.svc
        with svc.lock:
            self.owns = True
            cache = svc.app_state.get("perkey", {}) if svc.app_state.get("perkey_enabled") else {}
            self._colored = {int(i) for i in cache}
            if not svc.app_state.get("perkey_enabled"):
                svc.perkey.clear()                  # hidden old colors must not reappear when we enable
                self._colored = set()
            svc.perkey.enable(True)                 # also when a reaction had hidden the per-key layer
            if svc.firmware and (svc.firmware.get("protocol") or 0) >= 3:
                svc.perkey.live(True)               # the app dies mid-meter → the keyboard reloads its saved lighting

    def _restore(self):
        """Put the user's lighting back exactly, from the app's cache (read at the end, so edits made meanwhile win)."""
        svc = self.svc
        if not self.owns:
            return
        try:
            with svc.lock:
                pk = svc.perkey
                if pk is None:
                    return
                if svc.firmware and (svc.firmware.get("protocol") or 0) >= 3:
                    pk.live(False)
                n = svc.layout["led_count"]
                cache = svc.app_state.get("perkey", {})
                if all(str(i) in cache for i in range(n)):
                    pk.frame([cache[str(i)] for i in range(n)])     # every key has a color: no clear, no flicker
                else:
                    pk.clear()
                    if cache:
                        pk.set_leds({int(i): c for i, c in cache.items()})
                enabled = bool(svc.app_state.get("perkey_enabled"))
                playing = bool(svc.engine and svc.engine._active)   # a reaction hides the per-key layer
                svc._overlay_hidden = enabled and playing
                pk.enable(enabled and not playing)
        finally:
            self.owns = False
