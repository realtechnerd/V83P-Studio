"""Raw-HID transport to the keyboard's VIA interface (32-byte reports)."""
import threading
import time

import hid

from .boards import current as BOARD

VID, PID = BOARD.vid, BOARD.pid  # from mykeys/boards/<board>/board.json
USAGE_PAGE, USAGE = 0xFF60, 0x61
REPORT_LEN = 32

# Commands this app must never send: keymap reset, EEPROM reset, bootloader jump, macro reset.
FORBIDDEN = {0x06, 0x0A, 0x0B, 0x10}


class DeviceNotFound(RuntimeError):
    pass


class Keyboard:
    """Thread-safe request/response channel. Reopens the device on I/O errors."""

    def __init__(self, vid=VID, pid=PID, timeout_ms=250):
        self.vid, self.pid, self.timeout_ms = vid, pid, timeout_ms
        self._dev = None
        self._lock = threading.Lock()
        self.info = None

    def open(self):
        for d in hid.enumerate(self.vid, self.pid):
            if d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE:
                dev = hid.device()
                dev.open_path(d["path"])
                self._dev, self.info = dev, d
                return self
        raise DeviceNotFound(f"No VIA interface for {self.vid:04X}:{self.pid:04X} "
                             "(plugged in by USB? VIA closed?)")

    def close(self):
        with self._lock:
            if self._dev:
                self._dev.close()
                self._dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def send(self, payload):
        """Write one report without waiting for the reply (for streaming LED frames).
        The keyboard still replies; the next transact() discards those replies."""
        if payload[0] in FORBIDDEN:
            raise ValueError(f"Command 0x{payload[0]:02X} is blocked")
        buf = bytes(payload) + bytes(REPORT_LEN - len(payload))
        with self._lock:
            if self._dev is None:
                self.open()
            self._dev.write(b"\x00" + buf)

    def transact(self, payload, retries=2):
        """Send one report and return the 32-byte response."""
        if payload[0] in FORBIDDEN:
            raise ValueError(f"Command 0x{payload[0]:02X} is blocked")
        buf = bytes(payload) + bytes(REPORT_LEN - len(payload))
        with self._lock:
            for attempt in range(retries + 1):
                try:
                    if self._dev is None:
                        self.open()
                    # Windows delivers every reply to every program that has the keyboard open (VIA,
                    # the CLI, the app...). Drop stale replies, then wait for the one answering us:
                    # it echoes our command id, or is 0xFF + our echoed arguments (unhandled/bad args).
                    self._dev.set_nonblocking(True)  # (a plain read(n, 0) blocks forever in hidapi)
                    try:
                        for _ in range(256):
                            if not self._dev.read(REPORT_LEN):
                                break
                    finally:
                        self._dev.set_nonblocking(False)
                    self._dev.write(b"\x00" + buf)
                    deadline = time.monotonic() + self.timeout_ms / 1000
                    while (left := deadline - time.monotonic()) > 0:
                        resp = bytes(self._dev.read(REPORT_LEN, max(1, int(left * 1000))))
                        if not resp:
                            break
                        if resp[0] == buf[0] or (resp[0] == 0xFF and resp[1:3] == buf[1:3]):
                            return resp
                except (OSError, ValueError, DeviceNotFound):
                    if attempt == retries:
                        raise
                if self._dev:
                    self._dev.close()
                    self._dev = None
                time.sleep(0.2)
        raise TimeoutError(f"No response to command 0x{payload[0]:02X}")
