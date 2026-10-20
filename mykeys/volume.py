"""The Windows playback volume: VolumeWatcher calls back when the level or mute changes (knob, media keys, slider).

Talks to Windows' Core Audio directly through ctypes (IMMDeviceEnumerator → IAudioEndpointVolume), so nothing extra
has to be installed or bundled. Polls at 20 Hz on its own thread: reading the volume is a cheap local call.
"""
import ctypes
import logging
import threading
import time
import uuid
from ctypes import POINTER, WINFUNCTYPE, byref, c_float, c_int, c_long, c_uint, c_void_p

log = logging.getLogger(__name__)
ole32 = ctypes.OleDLL("ole32")


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, s):
        super().__init__()
        ctypes.memmove(self.data, uuid.UUID(s).bytes_le, 16)


CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioEndpointVolume = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")
CLSCTX_ALL = 0x17
E_RENDER, E_MULTIMEDIA = 0, 1

# vtable slots (IUnknown takes 0-2)
ENUM_GET_DEFAULT = 4          # IMMDeviceEnumerator::GetDefaultAudioEndpoint
DEVICE_ACTIVATE = 3           # IMMDevice::Activate
VOL_GET_SCALAR = 9            # IAudioEndpointVolume::GetMasterVolumeLevelScalar
VOL_GET_MUTE = 15             # IAudioEndpointVolume::GetMute
RELEASE = 2


def _call(obj, slot, argtypes, *args):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[slot])
    hr = fn(obj, *args)
    if hr < 0:
        raise OSError(f"COM call failed (slot {slot}, hr=0x{hr & 0xFFFFFFFF:08X})")


def _release(obj):
    if obj:
        _call(obj, RELEASE, [])


class Endpoint:
    """The default playback device's volume control."""

    def __init__(self):
        self.vol = None
        enum, dev, vol = c_void_p(), c_void_p(), c_void_p()
        ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                               byref(IID_IMMDeviceEnumerator), byref(enum))
        try:
            _call(enum, ENUM_GET_DEFAULT, [c_int, c_int, POINTER(c_void_p)], E_RENDER, E_MULTIMEDIA, byref(dev))
            try:
                _call(dev, DEVICE_ACTIVATE, [POINTER(GUID), c_uint, c_void_p, POINTER(c_void_p)],
                      byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None, byref(vol))
            finally:
                _release(dev)
        finally:
            _release(enum)
        self.vol = vol

    def read(self):
        """(level 0..1, muted)"""
        level, mute = c_float(), c_int()
        _call(self.vol, VOL_GET_SCALAR, [POINTER(c_float)], byref(level))
        _call(self.vol, VOL_GET_MUTE, [POINTER(c_int)], byref(mute))
        return max(0.0, min(1.0, level.value)), bool(mute.value)

    def close(self):
        _release(self.vol)
        self.vol = None


class VolumeWatcher:
    """Calls callback(level, muted) when the volume or mute changes. The first reading is not a change."""

    def __init__(self, callback, poll=0.05, refresh=3.0):
        self.callback, self.poll, self.refresh = callback, poll, refresh
        self.level, self.muted = None, None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="volume-watch")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(2)

    def _run(self):
        ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED, for this thread
        ep, got = None, 0.0
        try:
            while not self._stop.is_set():
                try:
                    if ep is None or time.monotonic() - got > self.refresh:   # follow default-device changes
                        if ep:
                            ep.close()
                        ep, got = Endpoint(), time.monotonic()
                    level, muted = ep.read()
                    if self.level is None:
                        self.level, self.muted = level, muted          # starting point, not a change
                    elif muted != self.muted or abs(level - self.level) > 0.002:
                        self.level, self.muted = level, muted
                        self.callback(level, muted)
                except Exception as e:          # no playback device, device switching, …: retry
                    log.debug("volume read failed: %s", e)
                    if ep:
                        try:
                            ep.close()
                        except Exception:
                            pass
                    ep = None
                    self._stop.wait(1.0)
                self._stop.wait(self.poll)
        finally:
            if ep:
                ep.close()
            ole32.CoUninitialize()
