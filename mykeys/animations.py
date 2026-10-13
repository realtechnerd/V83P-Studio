"""Host-driven animations. Each one maps elapsed time to a LightState, or returns None when done.

With the stock firmware these are whole-board animations. Smooth spatial motion
(spirals, waves) comes from the firmware's own effects (see Firmware); the host
adds timing, color and brightness changes on top.
"""
import colorsys
import math

from .via import LightState, effect_id

SOLID = 1


def parse_color(c):
    """'#ff8800' / 'ff8800' / (r,g,b) -> (hue, sat, val) as 0-255."""
    if isinstance(c, str):
        c = c.lstrip("#")
        c = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
    return round(h * 255), round(s * 255), round(v * 255)


class Animation:
    priority = 50
    name = "animation"

    def __init__(self, duration=None, priority=None, name=None):
        self.duration = duration
        if priority is not None:
            self.priority = priority
        if name:
            self.name = name

    def done(self, t):
        return self.duration is not None and t >= self.duration

    def frame(self, t, base: LightState):
        return None if self.done(t) else self.render(t, base)

    def render(self, t, base):
        raise NotImplementedError


class Static(Animation):
    """Hold a scene: a full LightState, or a dict of fields that overrides the base."""

    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.state = state

    def render(self, t, base):
        if isinstance(self.state, LightState):
            return self.state
        return state_from_dict(self.state, base)


class Firmware(Animation):
    """Run one of the keyboard's built-in effects with chosen speed, color and brightness."""

    def __init__(self, effect, speed=None, color=None, brightness=None, **kw):
        super().__init__(**kw)
        self.effect, self.speed, self.brightness = effect_id(effect), speed, brightness
        self.hs = parse_color(color)[:2] if color else None

    def render(self, t, base):
        st = base.with_(effect=self.effect)
        if self.speed is not None:
            st = st.with_(speed=self.speed)
        if self.brightness is not None:
            st = st.with_(brightness=self.brightness)
        if self.hs:
            st = st.with_(hue=self.hs[0], sat=self.hs[1])
        return st


class Pulse(Animation):
    """Solid color breathing at a chosen rate (smoother and tunable vs firmware breathing)."""

    def __init__(self, color, period=1.2, low=0.15, high=1.0, **kw):
        super().__init__(**kw)
        self.h, self.s, _ = parse_color(color)
        self.period, self.low, self.high = period, low, high

    def render(self, t, base):
        k = 0.5 - 0.5 * math.cos(2 * math.pi * t / self.period)
        level = self.low + (self.high - self.low) * k
        return base.with_(effect=SOLID, hue=self.h, sat=self.s, brightness=base.brightness * level)


class Flash(Animation):
    """Blink a color `count` times, then finish."""
    priority = 80

    def __init__(self, color, count=3, on=0.15, off=0.12, **kw):
        kw.setdefault("duration", count * (on + off))
        super().__init__(**kw)
        self.h, self.s, _ = parse_color(color)
        self.on, self.off = on, off

    def render(self, t, base):
        lit = (t % (self.on + self.off)) < self.on
        return base.with_(effect=SOLID, hue=self.h, sat=self.s,
                          brightness=max(base.brightness, 160) if lit else 0)


class HueSweep(Animation):
    """Solid color whose hue rotates continuously."""

    def __init__(self, period=4.0, sat=255, **kw):
        super().__init__(**kw)
        self.period, self.sat = period, sat

    def render(self, t, base):
        return base.with_(effect=SOLID, hue=(t / self.period * 255) % 256, sat=self.sat)


class Fade(Animation):
    """Fade from one color to another over `duration` (e.g. red→green progress)."""

    def __init__(self, start, end, duration=3.0, **kw):
        super().__init__(duration=duration, **kw)
        self.a, self.b = parse_color(start), parse_color(end)

    def render(self, t, base):
        k = min(1.0, t / self.duration)
        dh = ((self.b[0] - self.a[0] + 128) % 256) - 128  # shortest way round the hue circle
        return base.with_(effect=SOLID, hue=(self.a[0] + dh * k) % 256,
                          sat=self.a[1] + (self.b[1] - self.a[1]) * k)


ANIMATIONS = {"static": Static, "firmware": Firmware, "pulse": Pulse, "flash": Flash,
              "hue_sweep": HueSweep, "fade": Fade}


def state_from_dict(d: dict, base: LightState | None = None) -> LightState:
    """{"effect": "cycle_all", "color": "#00ff88", "brightness": 120, ...} -> LightState."""
    d = dict(d)
    if "color" in d:
        h, s, _ = parse_color(d.pop("color"))
        d.update(hue=h, sat=s)
    if "effect" in d:
        d["effect"] = effect_id(d["effect"])
    return (base or LightState()).with_(**d)


def from_spec(spec: dict) -> Animation:
    """Build an animation from a config dict like {"type": "pulse", "color": "#00f", ...}."""
    spec = dict(spec)
    kind = spec.pop("type")
    if kind == "static":
        return Static(spec.pop("state", {}), **spec)
    return ANIMATIONS[kind](**spec)
