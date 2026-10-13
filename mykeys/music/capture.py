"""WASAPI loopback capture of whatever the PC is playing (default output device)."""
import logging
import threading
import time
import warnings

import numpy as np

from .analyzer import Analyzer

log = logging.getLogger(__name__)
SAMPLERATE, BLOCK = 48000, 1024


class LoopbackCapture:
    """Background thread: default speaker loopback → Analyzer. Follows default-device changes."""

    def __init__(self):
        self.analyzer = Analyzer(SAMPLERATE, BLOCK)
        self.error = None
        self.device = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mykeys-audio", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        self._thread = None

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        import soundcard as sc
        warnings.filterwarnings("ignore", module="soundcard")  # "data discontinuity" spam
        while not self._stop.is_set():
            try:
                spk = sc.default_speaker()
                self.device = spk.name
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                with mic.recorder(samplerate=SAMPLERATE, channels=2, blocksize=BLOCK) as rec:
                    self.error, checked = None, time.monotonic()
                    while not self._stop.is_set():
                        self.analyzer.process(rec.record(numframes=BLOCK).astype(np.float32))
                        if time.monotonic() - checked > 3:  # switched headphones/speakers?
                            checked = time.monotonic()
                            if sc.default_speaker().name != spk.name:
                                log.info("default output changed, reopening")
                                break
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                log.warning("audio capture failed: %s", self.error)
                self._stop.wait(2)
