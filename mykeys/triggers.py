"""PC-event triggers that start and stop animations on the engine.

Rule kinds (see config/rules.json):
  app_launch  - a matching process starts → play until it shows a window (or timeout/exit)
  foreground  - play while a matching app is the focused window
"""
import ctypes
import ctypes.wintypes as wt
import fnmatch
import logging
import threading
import time

import psutil

from .animations import from_spec

log = logging.getLogger(__name__)
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _pid_of(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def pids_with_windows():
    """PIDs owning a visible, titled top-level window."""
    found = set()

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found.add(_pid_of(hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def foreground_process_name():
    try:
        return psutil.Process(_pid_of(user32.GetForegroundWindow())).name()
    except (psutil.Error, ValueError):
        return None


def _matches(name, patterns):
    n = (name or "").lower()
    return any(fnmatch.fnmatch(n, p.lower()) for p in patterns)


class TriggerManager:
    def __init__(self, engine, rules, poll=0.25):
        self.engine, self.rules, self.poll = engine, rules, poll
        self._stop = threading.Event()
        self._thread = None
        self._launches = {}   # rule index -> (handle, root pid, started)
        self._fg = {}         # rule index -> handle

    def start(self):
        self._thread = threading.Thread(target=self._run, name="mykeys-triggers", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _run(self):
        known = set(psutil.pids())  # ignore everything already running
        while not self._stop.is_set():
            try:
                known = self._tick(known)
            except Exception:
                log.exception("trigger tick failed")
            self._stop.wait(self.poll)

    def _tick(self, known):
        now = time.monotonic()
        pids = set(psutil.pids())
        new = pids - known
        launch_rules = [(i, r) for i, r in enumerate(self.rules) if r["when"] == "app_launch"]

        # --- app_launch: start ---
        if new and launch_rules:
            for pid in new:
                try:
                    name = psutil.Process(pid).name()
                except psutil.Error:
                    continue
                for i, r in launch_rules:
                    if i not in self._launches and _matches(name, r["apps"]):
                        h = self.engine.play(from_spec({"name": r.get("name", name), **r["animation"]}))
                        self._launches[i] = (h, pid, now)
                        log.info("launch: %s (pid %d) -> rule %r", name, pid, r.get("name"))

        # --- app_launch: finish when a window appears, the process exits, or timeout ---
        if self._launches:
            windowed = pids_with_windows()
            for i, (h, pid, t0) in list(self._launches.items()):
                r = self.rules[i]
                elapsed = now - t0
                if elapsed < r.get("min_seconds", 0.8):
                    continue
                family = {pid}
                try:
                    family |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
                    alive = True
                except psutil.Error:
                    alive = False
                if not alive or family & windowed or elapsed > r.get("timeout", 30):
                    self.engine.cancel(h)
                    del self._launches[i]
                    if r.get("on_ready"):
                        self.engine.play(from_spec(r["on_ready"]))

        # --- foreground ---
        fg_rules = [(i, r) for i, r in enumerate(self.rules) if r["when"] == "foreground"]
        if fg_rules:
            fg = foreground_process_name()
            for i, r in fg_rules:
                hit = _matches(fg, r["apps"])
                if hit and i not in self._fg:
                    self._fg[i] = self.engine.play(from_spec({"name": r.get("name", fg), **r["animation"]}))
                elif not hit and i in self._fg:
                    self.engine.cancel(self._fg.pop(i))
        return pids
