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
        self._launches = {}   # rule index -> (handle, started)
        self._fg = {}         # rule index -> handle

    def start(self):
        self._thread = threading.Thread(target=self._run, name="mykeys-triggers", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop watching, and stop every animation this manager started (rules saved, deleted or paused)."""
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        for h, _ in self._launches.values():
            self.engine.cancel(h)
        for h in self._fg.values():
            self.engine.cancel(h)
        self._launches.clear()
        self._fg.clear()

    def _run(self):
        self._names = {}                       # pid -> process name (looked up once per process)
        self._refresh_names()
        # apps already open when we start don't count as launches
        self._was_running = {i: bool(self._matching(r)) for i, r in enumerate(self.rules) if r["when"] == "app_launch"}
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("trigger tick failed")
            self._stop.wait(self.poll)

    def _refresh_names(self):
        pids = set(psutil.pids())
        for pid in pids - self._names.keys():
            try:
                self._names[pid] = psutil.Process(pid).name()
            except psutil.Error:
                self._names[pid] = None
        for pid in self._names.keys() - pids:
            del self._names[pid]

    def _matching(self, r):
        return {pid for pid, n in self._names.items() if n and _matches(n, r["apps"])}

    def _tick(self):
        """App launch = the app goes from not running to running. Apps like Discord, Spotify or Steam start many
        processes with the same name; each used to count as a new launch, and a helper that never opens a window
        kept the reaction going. Now: one launch per app start, done when any of its processes (or their children)
        shows a window, when it closes, or at the timeout. It can't fire again until the app has fully closed."""
        now = time.monotonic()
        self._refresh_names()

        # --- app_launch ---
        windowed = None
        for i, r in enumerate(self.rules):
            if r["when"] != "app_launch":
                continue
            matching = self._matching(r)
            running, was = bool(matching), self._was_running.get(i, False)
            self._was_running[i] = running
            if running and not was and i not in self._launches:
                h = self.engine.play(from_spec({"name": r.get("name", "launch"), **r["animation"]}))
                self._launches[i] = (h, now)
                log.info("launch: rule %r", r.get("name"))
                continue
            if i not in self._launches:
                continue
            h, t0 = self._launches[i]
            elapsed = now - t0
            if running and elapsed < r.get("min_seconds", 0.8):
                continue
            ready = False
            if running:
                if windowed is None:
                    windowed = pids_with_windows()
                family = set(matching)
                for pid in matching:
                    try:
                        family |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
                    except psutil.Error:
                        pass
                ready = bool(family & windowed)
            if ready or not running or elapsed > r.get("timeout", 30):
                self.engine.cancel(h)
                del self._launches[i]
                if ready and r.get("on_ready"):
                    self.engine.play(from_spec(r["on_ready"]))

        # --- foreground ---
        fg_rules = [(i, r) for i, r in enumerate(self.rules) if r["when"] == "foreground"]
        if fg_rules:
            fg = foreground_process_name()
            for i, r in fg_rules:
                hit = _matches(fg, r["apps"])
                if hit and i not in self._fg:
                    spec = {"name": r.get("name", fg), **r["animation"]}
                    if spec.get("type") == "flash":
                        spec["duration"] = None       # keep blinking while the app is focused
                    self._fg[i] = self.engine.play(from_spec(spec))
                elif not hit and i in self._fg:
                    self.engine.cancel(self._fg.pop(i))
