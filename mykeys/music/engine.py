"""MusicEngine: runs the visualizer on the keyboard while music should be shown.

Takes over per-key output (RAM only, no flash writes), pauses reactions/auto profiles, and on stop
fades out and restores the user's own per-key map exactly.

Safety rules (each one fixes a way the keyboard could get stuck showing a music frame):
- Spotify saying "playing" isn't enough: this PC must actually be making sound (Spotify Connect reports
  "playing" while it plays on another device). Silence for 8 s releases the keyboard.
- The user's colors are snapshotted to disk at take-over, so a crash/restart mid-song restores them later
  instead of mistaking the music frame for the user's lighting.
- Errors and disconnects never throw the snapshot away.
- Firmware protocol 3+: the stream is marked LIVE, so the keyboard reloads its saved lighting by itself if
  frames stop or it leaves USB mode (mode switch, cable pulled, app closed).
"""
import logging
import threading
import time

from .capture import LoopbackCapture
from .spotify import SpotifyWatcher
from .visualizers import PALETTES, STYLES, Visualizer

log = logging.getLogger(__name__)
FPS = 30
SILENCE_RELEASE = 8.0   # s of silence before the keyboard is given back
SOUND_TO_START = 0.5    # s of continuous sound before taking over (ignores clicks/notification sounds)
KEEPALIVE = 1.0         # s between LIVE refreshes (the firmware watchdog fires after 2 s)
STYLE_FADE = 0.3     # seconds: crossfade when switching styles

DEFAULTS = {"enabled": False, "only_spotify": True, "style": "spectrum", "palette": "matcha",
            "sensitivity": 1.0, "smoothing": 0.7, "dynamics": 0.4, "underglow_vu": True, "brightness": 1.0}


class MusicEngine:
    def __init__(self, service):
        self.svc = service
        st = service.app_state.setdefault("music", {})
        self.settings = {**DEFAULTS, **st}
        self.capture = LoopbackCapture()
        self.spotify = SpotifyWatcher().start()
        self.vis = Visualizer(service.layout)
        self.active = False          # currently driving the keyboard
        self.status = "idle"
        self.frame = [None] * service.layout["led_count"]
        self._saved = self._load_snapshot()   # user's lighting to restore (survives restarts)
        self._was_paused = (service.app_state.get("music_restore") or {}).get("was_paused", False)
        self._last_sound = 0.0
        self._sound_start = None
        self._capture_since = None
        self._last_keepalive = 0.0
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="mykeys-music", daemon=True).start()

    # ---------- settings ----------
    def update(self, changes):
        s = dict(self.settings)
        for k, v in changes.items():
            if k not in DEFAULTS:
                continue
            if k == "style" and v not in STYLES:
                raise ValueError(f"unknown style {v}")
            if k == "palette" and v not in PALETTES:
                raise ValueError(f"unknown palette {v}")
            s[k] = type(DEFAULTS[k])(v)
        self.settings = s
        self.svc.app_state["music"] = s
        self.svc._save_state()
        return self.public()

    def public(self):
        sp = self.spotify.info
        return {**self.settings, "status": self.status, "active": self.active,
                "spotify": sp, "device": self.capture.device, "error": self.capture.error,
                "styles": STYLES, "palettes": list(PALETTES), "album": self.spotify.album}

    def snapshot(self):
        a = self.capture.analyzer
        hexes = ["#%02x%02x%02x" % c if c else None for c in self.frame]
        return {"colors": hexes, "bands": [round(b, 3) for b in a.bands.tolist()], "beat": round(a.beat, 2)}

    def shutdown(self):
        self._stop.set()

    # ---------- restore snapshot (persisted) ----------
    def _load_snapshot(self):
        r = self.svc.app_state.get("music_restore")
        if not r:
            return None
        return ({int(i): c for i, c in r.get("colors", {}).items()}, bool(r.get("enabled")))

    def _store_snapshot(self):
        if self._saved is None:
            self.svc.app_state.pop("music_restore", None)
        else:
            colors, enabled = self._saved
            self.svc.app_state["music_restore"] = {"colors": {str(i): c for i, c in colors.items()},
                                                   "enabled": enabled, "was_paused": self._was_paused}
        self.svc._save_state()

    # ---------- decisions ----------
    def _hear(self, now):
        """Track whether this PC is actually producing sound."""
        if not self.capture.running:
            self._sound_start = None
            return
        if self.capture.analyzer.silent:
            self._sound_start = None
        else:
            self._last_sound = now
            if self._sound_start is None:
                self._sound_start = now

    def _audible(self, now):
        return (self._sound_start is not None and now - self._sound_start >= SOUND_TO_START) or \
               (self.active and now - self._last_sound < SILENCE_RELEASE)

    def _want(self, now):
        s = self.settings
        if not s["enabled"]:
            return "idle"
        if self.svc.kb is None:
            return "not_wired"
        if not (self.svc.firmware or {}).get("mykeys"):
            return "needs_firmware"           # stock firmware can't show per-key frames
        if s["only_spotify"] and not self.spotify.playing:
            return "waiting_for_spotify"
        if self._audible(now):
            return "playing"
        # Spotify says playing (or any-audio mode) but this PC is silent: playing on another device / muted
        listened = self._capture_since is not None and now - self._capture_since > 3
        return "elsewhere" if listened else "waiting_for_spotify"

    # ---------- loop ----------
    def _run(self):
        fade_until = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            # listen whenever music could be playing (needed to notice silence and sound returning)
            could_play = self.settings["enabled"] and self.svc.kb is not None and self.svc.ours() and \
                (self.spotify.playing or not self.settings["only_spotify"])
            if could_play and not self.capture.running:
                self.capture.start()
                self._capture_since = t0
            elif not could_play and self.capture.running and not self.active:
                self.capture.stop()
                self._capture_since = None
            self._hear(t0)
            want = self._want(t0)
            try:
                meter = getattr(self.svc, "volume_meter", None)
                if want == "playing" and not self.active and meter is not None and meter.owns:
                    pass                          # the volume meter is up: take over once it's done
                elif want == "playing":
                    if not self.active:
                        self._take_over()
                    fade_until = 0.0
                    self._draw(t0, 1.0)
                elif self.active:
                    if want in ("not_wired", "needs_firmware"):   # can't show it: keep the snapshot for later
                        self.active = False
                        log.info("music mode paused: keyboard not reachable (restore pending)")
                    elif not fade_until:
                        fade_until = t0 + 1.0     # fade out over 1 s, then give the lighting back
                    elif t0 < fade_until:
                        self._draw(t0, (fade_until - t0) / 1.0)
                    else:
                        fade_until = 0.0
                        self._release()
                elif self._saved is not None and self.svc.kb is not None and want != "playing":
                    self._release()               # leftover from a crash/restart/unplug: give it back now
            except Exception as e:
                log.warning("music frame failed (will retry, lighting snapshot kept): %s", e)
                self.active = False               # retry next tick; _saved stays, so nothing is lost
                self._stop.wait(0.5)
            self.status = "playing" if self.active and want == "playing" else want
            busy = self.active or want == "playing"
            self._stop.wait(max(0.0, 1 / FPS - (time.monotonic() - t0)) if busy else 0.25)

    def _draw(self, t, fade):
        s, a = self.settings, self.capture.analyzer
        a.sensitivity, a.smoothing, a.dynamics = s["sensitivity"], s["smoothing"], s["dynamics"]
        pal = self.spotify.album if s["palette"] == "album" and self.spotify.album else s["palette"]
        snap = a.snapshot()
        colors = self.vis.frame(snap, t, s["style"], pal, s["underglow_vu"], s["brightness"] * fade)
        # switching styles: the old one fades into the new one over STYLE_FADE instead of snapping
        if s["style"] != getattr(self, "_style", s["style"]):
            self._style_prev, self._style_since = self._style, t
        self._style = s["style"]
        prev = getattr(self, "_style_prev", None)
        if prev and t - self._style_since < STYLE_FADE:
            k = (t - self._style_since) / STYLE_FADE
            old = self.vis.frame(snap, t, prev, pal, s["underglow_vu"], s["brightness"] * fade)
            colors = [None if (a_ is None and b_ is None) else
                      tuple(int((a_ or (0, 0, 0))[j] * (1 - k) + (b_ or (0, 0, 0))[j] * k) for j in range(3))
                      for a_, b_ in zip(old, colors)]
        else:
            self._style_prev = None
        self.frame = colors
        meter = getattr(self.svc, "volume_meter", None)
        if meter is not None:
            colors = meter.frame_over(colors, t)   # the volume meter, drawn over the music
        pk = self.svc.perkey
        pk.stream([c if c else (0, 0, 0) for c in colors])
        if self._live() and t - self._last_keepalive > KEEPALIVE:  # unchanged frames send nothing
            self._last_keepalive = t
            pk.live_ping()

    def _live(self):
        return ((self.svc.firmware or {}).get("protocol") or 0) >= 3

    def _take_over(self):
        svc = self.svc
        with svc.lock:
            pk = svc.perkey
            if self._saved is None:               # fresh start: remember the user's lighting first
                info = pk.detect()
                self._saved = (pk.read_all() if info and info[0] >= 2 else {}, bool(info and info[2]))
                self._was_paused = svc.paused
                self._store_snapshot()
            svc.set_paused(True)                  # reactions + auto profiles off while music plays
            pk.clear()
            pk.fill("#000000")
            pk.enable(True)
            if self._live():
                pk.live(True)
                self._last_keepalive = time.monotonic()
        self.active = True
        log.info("music mode on (%s)", self.spotify.info.get("title"))

    def _release(self):
        """Fade finished (or a leftover snapshot): put the user's lighting back exactly."""
        svc, saved = self.svc, self._saved
        with svc.lock:
            pk = svc.perkey
            if self._live():
                pk.live(False)
            if saved is not None:
                colors, enabled = saved
                pk.clear()
                if colors:
                    pk.set_leds(colors)
                pk.enable(enabled)
            svc.set_paused(self._was_paused)
        self.active, self._saved = False, None
        self._store_snapshot()
        self.frame = [None] * len(self.frame)
        log.info("music mode off (lighting restored)")
