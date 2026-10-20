"""KeyboardService: the one owner of the keyboard for the Studio app.

Tracks the connection (wired / wireless-only / disconnected), runs the lighting engine and
reaction triggers, and keeps app-side state the firmware can't report back (per-key colors,
macro names) in config/studio_state.json.
"""
import json
import logging
import threading
import time

import hid
import psutil

from ..config import PROFILES, STATE_PATH, load_rules
from ..device import PID, VID, DeviceNotFound, Keyboard
from ..engine import Engine
from ..keymap import Keymap
from ..macros import Macros
from ..perkey import PerKey, load_layout, to_rgb
from ..triggers import TriggerManager
from ..via import EFFECTS, LightState, RGBMatrix

log = logging.getLogger(__name__)
from ..boards import current as BOARD

DONGLE = BOARD.dongle


class NotWired(RuntimeError):
    pass


class KeyboardService:
    def __init__(self):
        self.lock = threading.RLock()
        self.kb = None
        self.rgb = self.perkey = self.keymap = self.macros = None
        self.engine = self.triggers = None
        self.connection = "disconnected"
        self.firmware = None
        self.layout = load_layout()
        self.app_state = self._load_state()
        self.app_state.setdefault("auto_profiles", {"enabled": False, "default": None, "rules": []})
        self.active_profile = None   # last profile applied (manually or automatically)
        self.auto_reason = None      # app that caused the current automatic switch
        self.paused = False
        self.flashing = False        # the keyboard is (or may be) in flash mode for a firmware job
        self._flash_check = 0.0
        self._last_write = self._last_sync = 0.0
        self._stop = threading.Event()
        self._overlay_hidden = False  # per-key colors hidden while a reaction plays
        from ..flasher import Flasher
        self.flasher = Flasher(self)  # (before the watch thread starts: it asks the flasher)
        threading.Thread(target=self._watch, daemon=True, name="studio-watch").start()
        threading.Thread(target=self._auto_loop, daemon=True, name="studio-autoprofile").start()
        from ..music.engine import MusicEngine
        self.music = MusicEngine(self)

    # ---------- persistence ----------
    def _load_state(self):
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"perkey": {}, "perkey_enabled": False, "macro_names": [""] * 16}

    def _save_state(self):
        STATE_PATH.write_text(json.dumps(self.app_state, indent=1), encoding="utf-8")

    # ---------- connection ----------
    def _present(self):
        ids = {(d["vendor_id"], d["product_id"]) for d in hid.enumerate()}
        if (VID, PID) in ids:
            return "wired"
        return "wireless" if DONGLE in ids else "disconnected"

    def _watch(self):
        """Wired: ping the keyboard every 0.3 s (~8 ms each), so a switch to 2.4G/BT or a pulled cable is
        noticed almost immediately. Not wired: list USB devices once a second (~200 ms each, too slow to
        run faster) to notice the keyboard coming back."""
        while not self._stop.is_set():
            wait = 1.0
            try:
                if self.kb is not None:
                    wait = 0.3
                    try:
                        with self.lock:
                            if self.kb is not None:
                                self.kb.transact([0x01])  # VIA "protocol version": harmless, works on any firmware
                    except (OSError, TimeoutError, DeviceNotFound):
                        if self.device_lost():
                            continue
                    if self.kb is not None and time.monotonic() - self._last_sync > 2:
                        with self.lock:
                            self._safe_sync()
                else:
                    now = self._present()
                    with self.lock:
                        if now == "wired":
                            self._connect()
                            self.flashing = False     # it's back (after a firmware job, or the user replugged)
                            self._safe_sync()
                        self.connection = self._label(now)
                    if self.flashing and not self.flasher.busy and time.monotonic() - self._flash_check > 3:
                        self._flash_check = time.monotonic()   # left in flash mode after a job: still there?
                        from ..flasher import in_flash_mode
                        if not in_flash_mode():
                            self.flashing = False
            except Exception:
                log.exception("connection check failed")
                with self.lock:
                    self._disconnect()
                    self.connection = self._label("disconnected")
            self._stop.wait(wait)

    def _safe_sync(self):
        """A failed read (e.g. another program talking to the keyboard at the same moment) just skips this
        round. It used to tear down the whole connection, stopping the engine and music mode mid-song."""
        try:
            self._sync()
        except Exception as e:
            log.warning("sync skipped: %s", e)

    def _sync(self):
        """Mirror the keyboard's real state (it can change via Fn keys or a factory reset).

        Skipped right after the app changes something (so a write in flight isn't undone)
        and while a reaction animation is playing (the keyboard shows the animation, not the base)."""
        self._last_sync = time.monotonic()
        if time.monotonic() - self._last_write < 1.5 or self.engine._active or self._overlay_hidden \
                or getattr(self, "music", None) and self.music.active:
            return
        actual = self.rgb.read()  # also marks it as already sent
        self.engine.set_base(actual)
        if self.firmware and (self.firmware.get("protocol") or 0) >= 2:
            info = self.perkey.detect()
            colors = self.perkey.read_all()
            self.app_state["perkey"] = {str(i): c for i, c in colors.items()}
            self.app_state["perkey_enabled"] = bool(info[2]) if info else False

    def _connect(self):
        """All or nothing: a keyboard that's still booting can miss a question; then undo the half-made
        connection (callers hold the lock, so nobody sees it) and the watch loop simply tries again."""
        try:
            self.kb = Keyboard().open()
            self.rgb, self.perkey = RGBMatrix(self.kb), PerKey(self.kb)
            self.keymap, self.macros = Keymap(self.kb), Macros(self.kb)
            info = self.perkey.detect()
            self.firmware = {"release": f"{self.kb.info['release_number']:04X}",
                             "mykeys": info is not None, "protocol": info[0] if info else None}
            self.engine = Engine(self.rgb, on_playing=self._reaction_playing).start()
            self.triggers = TriggerManager(self.engine, load_rules().get("rules", [])).start()
        except Exception:
            self._disconnect()
            raise
        log.info("keyboard connected: %s", self.firmware)

    def _reaction_playing(self, playing):
        """Reactions change the keyboard's effect, which per-key colors would cover (a fully static keyboard
        showed nothing but Pulse's dimming). Hide the per-key layer while one plays and bring it back after.
        RAM only: the saved colors are untouched, and a replug restores them anyway."""
        pk = self.perkey
        if pk is None or not self.ours():
            return
        if playing and not self._overlay_hidden and self.app_state.get("perkey_enabled"):
            pk.enable(False)
            self._overlay_hidden = True
        elif not playing and self._overlay_hidden:
            self._overlay_hidden = False
            pk.enable(True)

    def _disconnect(self):
        for part in (self.triggers, self.engine):
            if part:
                try:
                    part.stop() if part is self.triggers else part.stop(restore=False)
                except Exception:
                    pass
        if self.kb:
            self.kb.close()
        self.kb = self.rgb = self.perkey = self.keymap = self.macros = None
        self.engine = self.triggers = None
        self.firmware = None

    def device_lost(self):
        """Called when a write fails. If the keyboard really left USB, drop the connection now
        (UI greys out immediately) and return True; False means it was some other error."""
        now = self._present()
        if now == "wired":
            return False
        with self.lock:
            self._disconnect()
            self.connection = self._label(now)
        log.info("keyboard left USB during a change (%s)", now)
        return True

    def _label(self, now):
        """In flash mode the keyboard is gone from USB while the 2.4G dongle stays: that's not 'wireless'."""
        busy = getattr(self, "flasher", None) is not None and self.flasher.busy
        return "flashing" if now != "wired" and (self.flashing or busy) else now

    # ---------- firmware wizard ----------
    def enter_flash_mode(self):
        """Our firmware: jump to flash mode by command (settings are kept)."""
        with self.lock:
            self.flashing = True
            try:
                self.perkey.bootloader()
            except (OSError, TimeoutError):
                pass  # it may reset before answering
            self._disconnect()
            self.connection = "flashing"

    def release_for_flash(self):
        """Stock firmware: the user will replug with Esc held. Stop talking to the keyboard until it's done."""
        with self.lock:
            self.flashing = True
            self._disconnect()
            self.connection = "flashing"

    def resume_after_flash(self):
        """The job is over. If the keyboard is still in flash mode (waiting for the replug, or after an
        error), keep saying 'flashing' until it shows up again; the watch loop reconnects it."""
        from ..flasher import in_flash_mode
        with self.lock:
            self.flashing = in_flash_mode()
            self._flash_check = time.monotonic()
            if self.connection == "flashing" and not self.flashing:
                self.connection = "disconnected"

    def firmware_info(self):
        return self.flasher.info()

    def firmware_start(self, action, backup=None):
        self.flasher.start(action, backup)
        return self.flasher.status

    def firmware_cancel(self):
        self.flasher.cancel()
        return self.flasher.status

    def set_music(self, changes):
        if changes.get("enabled"):
            self._need_ours("Music mode")
        return self.music.update(changes)

    # ---------- app preferences (colorway, appearance) ----------
    def set_prefs(self, prefs):
        with self.lock:
            ui = self.app_state.setdefault("ui", {})
            ui.update({k: v for k, v in prefs.items() if k in ("colorway", "appearance") and isinstance(v, str)})
            self._save_state()
            return ui

    def shutdown(self):
        self._stop.set()
        if getattr(self, "music", None):
            self.music.shutdown()
        with self.lock:
            self._disconnect()

    def ours(self):
        """The keyboard runs the V83P Studio firmware (per-key colors, music mode). False on stock or unknown."""
        return bool(self.firmware and self.firmware.get("mykeys"))

    def _need_ours(self, what="This"):
        if self.kb is not None and not self.ours():
            raise NotWired(f"{what} needs the V83P Studio firmware. Install it on the Device page.")

    def _need(self):
        if self.kb is None:
            raise NotWired("Plug the keyboard in with the cable (switch on wired) to edit.")

    # ---------- state ----------
    def state(self, lite=False):
        """lite=True leaves out the static layout/effect tables (for frequent polling)."""
        with self.lock:
            s = {"connection": self.connection, "firmware": self.firmware,
                 "active_profile": self.active_profile, "auto_reason": self.auto_reason, "paused": self.paused,
                 "music": ({"enabled": self.music.settings["enabled"], "active": self.music.active,
                            "status": self.music.status, "title": self.music.spotify.info.get("title"),
                            "artist": self.music.spotify.info.get("artist")} if getattr(self, "music", None) else None),
                 "perkey": self.app_state["perkey"], "perkey_enabled": self.app_state["perkey_enabled"],
                 "flash": self.flasher.status, "ui": self.app_state.get("ui", {}),
                 **({} if lite else {"effects": EFFECTS, "layout": self.layout, "board": BOARD.public()})}
            if self.kb and self.engine:   # (the engine starts a moment after the keyboard connects)
                st = self.engine.base
                s["lighting"] = {"effect": st.effect, "brightness": st.brightness, "speed": st.speed,
                                 "hue": st.hue, "sat": st.sat}
            return s

    # ---------- lighting ----------
    def set_lighting(self, fields, save=False):
        with self.lock:
            self._need()
            self._last_write = time.monotonic()
            st = self.engine.base.with_(**{k: v for k, v in fields.items()
                                            if k in ("effect", "brightness", "speed", "hue", "sat")})
            self.engine.set_base(st)
            if save:
                self.rgb.apply(st)
                self.rgb.save()
            return st

    def set_perkey(self, colors=None, fill=None, clear=False, enabled=None, save=False):
        """colors: {led: '#rrggbb' | None}. None removes a key's custom color."""
        with self.lock:
            self._need()
            self._need_ours("Per-key lighting")
            self._last_write = time.monotonic()
            pk, cache = self.perkey, self.app_state["perkey"]
            if clear:
                pk.clear()
                cache.clear()
            if fill:
                pk.fill(fill)
                cache.clear()
                cache.update({str(i): fill for i in range(self.layout["led_count"])})
            if colors:
                removed = [int(i) for i, c in colors.items() if not c]
                setc = {int(i): c for i, c in colors.items() if c}
                if removed:  # firmware has no 'unset one key': clear and resend the rest
                    for i in removed:
                        cache.pop(str(i), None)
                    pk.clear()
                    pk._sent = {}
                    setc = {int(i): c for i, c in cache.items()} | setc
                if setc:
                    pk.set_leds(setc)
                    cache.update({str(i): c for i, c in setc.items()})
            if enabled is not None:
                pk.enable(enabled)
                self.app_state["perkey_enabled"] = bool(enabled)
            if save:
                pk.save()
            self._save_state()
            return {"perkey": cache, "perkey_enabled": self.app_state["perkey_enabled"]}

    # ---------- keymap / knob ----------
    def get_keymap(self):
        with self.lock:
            self._need()
            return {"keymap": self.keymap.read_all(), "encoders": self.keymap.read_encoders()}

    def set_key(self, layer, row, col, keycode):
        with self.lock:
            self._need()
            self.keymap.set_key(layer, row, col, keycode)

    def set_encoder(self, layer, clockwise, keycode):
        with self.lock:
            self._need()
            self.keymap.set_encoder(layer, clockwise, keycode)

    # ---------- macros ----------
    def get_macros(self):
        with self.lock:
            self._need()
            slots = self.macros.read()
            names = (self.app_state.get("macro_names") or [])[:len(slots)]
            names += [""] * (len(slots) - len(names))
            return {"slots": slots, "names": names, "size": self.macros.size(),
                    "used": Macros.used_bytes(slots)}

    def set_macros(self, slots, names=None):
        with self.lock:
            self._need()
            used = self.macros.write(slots)
            if names is not None:
                self.app_state["macro_names"] = names
                self._save_state()
            return {"used": used, "size": self.macros.size()}

    # ---------- reactions ----------
    def get_rules(self):
        return load_rules()

    def set_rules(self, cfg):
        from ..config import RULES_PATH
        RULES_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        with self.lock:
            if self.triggers:
                self.triggers.stop()
                self.triggers = TriggerManager(self.engine, cfg.get("rules", [])).start()

    @staticmethod
    def processes():
        names = set()
        for p in psutil.process_iter(["name"]):
            n = p.info.get("name")
            if n and n.lower().endswith(".exe"):
                names.add(n)
        return sorted(names, key=str.lower)

    # ---------- profiles ----------
    def list_profiles(self):
        PROFILES.mkdir(exist_ok=True)
        return sorted(p.stem for p in PROFILES.glob("*.json"))

    def save_profile(self, name):
        with self.lock:
            self._need()
            data = {"saved": time.strftime("%Y-%m-%d %H:%M"), "lighting": self.state()["lighting"],
                    "perkey": self.app_state["perkey"], "perkey_enabled": self.app_state["perkey_enabled"],
                    **self.get_keymap(), "macros": self.macros.read(),
                    "macro_names": self.app_state.get("macro_names", [])}
        PROFILES.mkdir(exist_ok=True)
        (PROFILES / f"{_safe(name)}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data

    def apply_profile(self, name, to_keyboard=True, lighting_only=False):
        """lighting_only=True: effect + per-key colors in RAM only (instant, no flash wear)."""
        data = json.loads((PROFILES / f"{_safe(name)}.json").read_text(encoding="utf-8"))
        with self.lock:
            self._need()
            self.set_lighting(data["lighting"], save=to_keyboard and not lighting_only)
            if self.ours():     # stock firmware: the effect only; per-key colors need our firmware
                self.set_perkey(clear=True)
                if data.get("perkey"):
                    self.set_perkey(colors=data["perkey"])
                self.set_perkey(enabled=data.get("perkey_enabled", False), save=to_keyboard and not lighting_only)
            self.active_profile = name
            if lighting_only:
                return data
            for l, layer in enumerate(data.get("keymap", [])):
                cur = self.keymap.read_all()[l]
                for r, row in enumerate(layer):
                    for c, kc in enumerate(row):
                        if cur[r][c] != kc:
                            self.keymap.set_key(l, r, c, kc)
            for l, enc in enumerate(data.get("encoders", [])):
                self.keymap.set_encoder(l, True, enc["cw"])
                self.keymap.set_encoder(l, False, enc["ccw"])
            if "macros" in data:
                self.set_macros(data["macros"], data.get("macro_names"))
        return data

    def delete_profile(self, name):
        (PROFILES / f"{_safe(name)}.json").unlink(missing_ok=True)

    # ---------- automatic profile per app ----------
    def get_autoprofiles(self):
        return self.app_state["auto_profiles"]

    def set_autoprofiles(self, cfg):
        cfg = {"enabled": bool(cfg.get("enabled")), "default": cfg.get("default") or None,
               "rules": [{"apps": [a for a in r.get("apps", []) if a], "profile": r.get("profile")}
                         for r in cfg.get("rules", []) if r.get("profile")]}
        with self.lock:
            self.app_state["auto_profiles"] = cfg
            self._save_state()
            self._auto_last = None  # re-evaluate on the next tick
        return cfg

    def set_paused(self, paused):
        with self.lock:
            self.paused = bool(paused)
            if self.engine:
                self.engine.clear()
            if self.triggers and paused:
                self.triggers.stop()
            elif self.engine and not paused:
                self.triggers = TriggerManager(self.engine, load_rules().get("rules", [])).start()
        return self.paused

    def _auto_loop(self):
        from ..triggers import _matches, foreground_process_name
        self._auto_last = None
        while not self._stop.is_set():
            self._stop.wait(0.5)
            cfg = self.app_state["auto_profiles"]
            if not cfg.get("enabled") or self.paused or self.kb is None:
                self._auto_last = None
                continue
            fg = foreground_process_name()
            if not fg or fg.lower() in ("electron.exe", "mykeys studio.exe"):
                continue  # don't switch while the user is in this app
            want, reason = cfg.get("default"), None
            for r in cfg["rules"]:
                if _matches(fg, r["apps"]):
                    want, reason = r["profile"], fg
                    break
            if want and want != self._auto_last:
                try:
                    self.apply_profile(want, lighting_only=True)
                    self._auto_last, self.auto_reason = want, reason
                    log.info("auto profile -> %s (%s)", want, fg)
                except Exception as e:
                    log.warning("auto profile %s failed: %s", want, e)
                    self._auto_last = want  # don't retry every tick


def _safe(name):
    keep = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()
    if not keep:
        raise ValueError("profile name is empty")
    return keep
