"""VIA protocol v12 lighting control (rgb_matrix on custom channel 3).

QMK applies VIA set-value calls with the *_noeeprom functions, so live changes
only touch RAM. Nothing persists across a replug unless save() is called.
"""
import math
from dataclasses import dataclass, replace

from .boards import current as BOARD
from .device import Keyboard

MAX_BRIGHTNESS = BOARD.max_brightness  # RGB_MATRIX_MAXIMUM_BRIGHTNESS

CMD_GET_PROTOCOL = 0x01
CMD_GET_KEYBOARD_VALUE = 0x02
CMD_CUSTOM_SET = 0x07
CMD_CUSTOM_GET = 0x08
CMD_CUSTOM_SAVE = 0x09
CMD_LAYER_COUNT = 0x11

CH_RGB_MATRIX = 3
V_BRIGHTNESS, V_EFFECT, V_SPEED, V_COLOR = 1, 2, 3, 4

# rgb_matrix mode numbers, as VIA sends them (0 = off), from the board definition
# (mykeys/boards/<board>/board.json → rgb.effects).
EFFECTS = BOARD.effects
EFFECT_IDS = {v: k for k, v in EFFECTS.items()}


def effect_id(name_or_id):
    if isinstance(name_or_id, int):
        return name_or_id
    s = str(name_or_id).strip().lower()
    return int(s) if s.isdigit() else EFFECT_IDS[s]


@dataclass(frozen=True)
class LightState:
    """Everything the stock firmware lets us control. hue/sat/brightness/speed are 0-255."""
    effect: int = 1
    brightness: int = 128
    speed: int = 128
    hue: int = 0
    sat: int = 255

    def with_(self, **kw):
        return replace(self, **{k: (max(0, min(255, int(v))) if k != "effect" else v)
                                for k, v in kw.items()})


class RGBMatrix:
    def __init__(self, kb: Keyboard):
        self.kb = kb
        self._sent = None  # last LightState written, used to skip unchanged fields

    # --- raw value access ---
    def _get(self, value_id):
        r = self.kb.transact([CMD_CUSTOM_GET, CH_RGB_MATRIX, value_id])
        if r[0] == 0xFF:
            raise RuntimeError(f"rgb_matrix value {value_id} unsupported")
        return r[3:5]

    def _set(self, value_id, *data):
        self.kb.transact([CMD_CUSTOM_SET, CH_RGB_MATRIX, value_id, *data])

    def protocol_version(self):
        r = self.kb.transact([CMD_GET_PROTOCOL])
        return r[1] << 8 | r[2]

    def layer_count(self):
        return self.kb.transact([CMD_LAYER_COUNT])[1]

    # --- state ---
    def read(self) -> LightState:
        h, s = self._get(V_COLOR)
        st = LightState(effect=self._get(V_EFFECT)[0], brightness=self._get(V_BRIGHTNESS)[0],
                        speed=self._get(V_SPEED)[0], hue=h, sat=s)
        self._sent = st
        return st

    @staticmethod
    def _brightness_raw(value):
        """VIA brightness is 0-255, but firmware stores scale8(x, MAX) and reports v*255/MAX.
        Pick the x that makes a read-back return `value` exactly, so restores don't drift."""
        v = round(value * MAX_BRIGHTNESS / 255)
        return min(255, math.ceil(v * 256 / (MAX_BRIGHTNESS + 1)))

    def apply(self, st: LightState, force=False):
        """Write only the fields that changed since the last apply/read."""
        prev = None if force else self._sent
        if prev is None or st.effect != prev.effect:
            self._set(V_EFFECT, st.effect)
        if prev is None or st.brightness != prev.brightness:
            self._set(V_BRIGHTNESS, self._brightness_raw(st.brightness))
        if prev is None or st.speed != prev.speed:
            self._set(V_SPEED, st.speed)
        if prev is None or (st.hue, st.sat) != (prev.hue, prev.sat):
            self._set(V_COLOR, st.hue, st.sat)
        self._sent = st

    def save(self):
        """Persist the current lighting to EEPROM (what VIA's save does). Use sparingly."""
        self.kb.transact([CMD_CUSTOM_SAVE, CH_RGB_MATRIX])
