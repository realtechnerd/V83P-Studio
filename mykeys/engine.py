"""Lighting engine: a background loop that shows the highest-priority active animation,
falling back to the base profile. Restores the keyboard's original lighting on stop."""
import itertools
import logging
import threading
import time

from .via import LightState, RGBMatrix

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, rgb: RGBMatrix, base: LightState | None = None, fps=30, on_playing=None, on_frame=None):
        self.rgb = rgb
        self.on_playing = on_playing        # called with True/False when animations start / all end
        self.on_frame = on_frame            # called after each frame while animations play (keep-alives)
        self._playing = False
        self.original = rgb.read()          # restored on stop()
        self.base = base or self.original
        self.fps = fps
        self._active = {}                   # handle -> (animation, start_time)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()      # set on any change, so an idle loop reacts immediately
        self._thread = None
        self.paused = False

    # --- control ---
    def play(self, anim) -> int:
        with self._lock:
            h = next(self._ids)
            self._active[h] = (anim, time.monotonic())
        log.info("play #%d %s (priority %d)", h, anim.name, anim.priority)
        self._wake.set()
        return h

    def cancel(self, handle):
        with self._lock:
            if self._active.pop(handle, None):
                log.info("stop #%d", handle)
        self._wake.set()

    def clear(self):
        with self._lock:
            self._active.clear()
        self._wake.set()

    def set_base(self, state: LightState):
        self.base = state
        self._wake.set()

    def start(self):
        self._thread = threading.Thread(target=self._run, name="mykeys-engine", daemon=True)
        self._thread.start()
        return self

    def stop(self, restore=True):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(2)
        self._notify(False)
        if restore:
            self.rgb.apply(self.original, force=True)

    def _notify(self, playing):
        if playing != self._playing and self.on_playing:
            self._playing = playing
            try:
                self.on_playing(playing)
            except Exception as e:
                log.warning("on_playing(%s) failed: %s", playing, e)

    # --- loop ---
    def current(self, now):
        with self._lock:
            ranked = sorted(self._active.items(), key=lambda kv: (kv[1][0].priority, kv[1][1]),
                            reverse=True)
            for h, (anim, t0) in ranked:
                st = anim.frame(now - t0, self.base)
                if st is not None:
                    return st
                del self._active[h]         # finished
                log.info("done #%d %s", h, anim.name)
        return self.base

    def _run(self):
        period = 1 / self.fps
        while not self._stop.is_set():
            t = time.monotonic()
            if not self.paused:
                try:
                    st = self.current(t)
                    self._notify(bool(self._active))   # e.g. per-key colors step aside while a reaction plays
                    self.rgb.apply(st)
                    if self._active and self.on_frame:
                        self.on_frame()
                except Exception as e:  # unplugged, asleep, etc.: keep running, retry later
                    log.warning("device error: %s", e)
                    self.rgb._sent = None
                    self._stop.wait(1.0)
                    continue
            if self._active:  # animating: steady frame rate
                self._stop.wait(max(0.0, period - (time.monotonic() - t)))
            else:             # idle: sleep until something changes (or stop is requested)
                self._wake.wait(1.0)
                self._wake.clear()
