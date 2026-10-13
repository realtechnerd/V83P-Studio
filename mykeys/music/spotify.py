"""Is Spotify playing, and what? Uses the Windows media session (same data as the volume-key overlay).

Falls back to Spotify's window title ("Artist - Song" while playing) if WinRT isn't available.
"""
import asyncio
import ctypes
import ctypes.wintypes as wt
import logging
import threading

import psutil

log = logging.getLogger(__name__)
PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing


def album_palette(image_bytes, n=4):
    """Album art → 4 palette stops (dark → vivid → vivid → light), as hex strings."""
    import colorsys
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((64, 64))
    q = img.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    pal, counts = q.getpalette(), sorted(q.getcolors(), reverse=True)
    cols = []
    for count, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        cols.append((count, (r, g, b), h, s, v))
    vivid = sorted((c for c in cols if c[3] > 0.25 and c[4] > 0.25), key=lambda c: -(c[0] * (0.4 + c[3])))
    picks = [c[1:] for c in (vivid or sorted(cols, key=lambda c: -c[4]))[:2]]
    if len(picks) == 1:
        picks.append(picks[0])
    to_hex = lambda h, s, v: "#%02x%02x%02x" % tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, s, v))
    (_, h1, s1, v1), (_, h2, s2, v2) = picks
    # LEDs need saturated, bright colors to read well
    return [to_hex(h1, min(1, s1 * 1.1), 0.18), to_hex(h1, max(s1, .6), max(v1, .85)),
            to_hex(h2, max(s2, .5), max(v2, .95)), to_hex(h2, s2 * 0.3, 1.0)]


class SpotifyWatcher:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.info = {"running": False, "playing": False, "title": None, "artist": None, "source": None}
        self.album = None            # palette stops from the current album art
        self._art_for = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mykeys-spotify", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    @property
    def playing(self):
        return self.info["playing"]

    def _run(self):
        loop = asyncio.new_event_loop()
        try:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            mgr = loop.run_until_complete(M.request_async())
        except Exception as e:
            log.info("media session API unavailable (%s); using window titles", e)
            mgr = None
        while not self._stop.is_set():
            try:
                self.info = loop.run_until_complete(self._media(mgr)) if mgr else self._window_title()
            except Exception as e:
                log.debug("spotify check failed: %s", e)
                self.info = self._window_title()
            self._stop.wait(self.interval)

    async def _media(self, mgr):
        for s in mgr.get_sessions():
            if "spotify" not in (s.source_app_user_model_id or "").lower():
                continue
            playing = int(s.get_playback_info().playback_status) == PLAYING
            props = await s.try_get_media_properties_async()
            key = (props.title, props.artist)
            if key != self._art_for and props.thumbnail:
                self._art_for = key
                try:
                    from winrt.windows.storage.streams import DataReader
                    st = await props.thumbnail.open_read_async()
                    reader = DataReader(st.get_input_stream_at(0))
                    buf = bytearray(await reader.load_async(st.size))
                    reader.read_bytes(buf)
                    self.album = album_palette(bytes(buf))
                    log.info("album palette for %s: %s", props.title, self.album)
                except Exception as e:
                    log.info("album art unavailable: %s", e)
                    self.album = None
            return {"running": True, "playing": playing, "title": props.title or None,
                    "artist": props.artist or None, "source": "media-session"}
        return {"running": False, "playing": False, "title": None, "artist": None, "source": "media-session"}

    @staticmethod
    def _window_title():
        pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "spotify.exe"}
        if not pids:
            return {"running": False, "playing": False, "title": None, "artist": None, "source": "window"}
        user32, titles = ctypes.windll.user32, []
        proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(hwnd, _):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            n = user32.GetWindowTextLengthW(hwnd)
            if pid.value in pids and n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                titles.append(buf.value)
            return True

        user32.EnumWindows(proc(cb), 0)
        song = next((t for t in titles if " - " in t), None)
        artist, _, title = song.partition(" - ") if song else (None, None, None)
        return {"running": True, "playing": bool(song), "title": title, "artist": artist, "source": "window"}
