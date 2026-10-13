"""Dry run of music mode's 'is this PC really playing?' gate (no keyboard, no audio device)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mykeys.music import engine as E  # noqa: E402

eng = object.__new__(E.MusicEngine)            # skip __init__ (no threads/devices)
eng.settings = dict(E.DEFAULTS, enabled=True, only_spotify=True)
eng.svc = SimpleNamespace(kb=object(), firmware={"mykeys": True, "protocol": 3})
eng.spotify = SimpleNamespace(playing=True)    # Spotify says "Playing" the whole time (like Spotify Connect)
eng.capture = SimpleNamespace(running=True, analyzer=SimpleNamespace(silent=True))
eng.active, eng._last_sound, eng._sound_start, eng._capture_since = False, 0.0, None, 0.0


def run(label, secs, silent, step=0.25):
    global t
    eng.capture.analyzer.silent = silent
    seen = []
    for _ in range(int(secs / step)):
        t += step
        eng._hear(t)
        w = eng._want(t)
        if w == "playing":
            eng.active = True
        elif eng.active and w != "playing":
            eng.active = False                 # (the real loop fades out, then restores the lighting)
        if not seen or seen[-1][1] != w:
            seen.append((round(t, 2), w))
    print(f"{label:52s} -> " + ", ".join(f"{w} @ {ts:.2f}s" for ts, w in seen))


t = 0.0
run("Spotify 'playing' on another device, PC silent 20 s", 20, True)
run("music starts on this PC", 3, False)
run("4 s gap between songs (should stay on)", 4, True)
run("music continues", 2, False)
run("switch playback to phone: PC silent 12 s", 12, True)
run("a 0.25 s notification ding (should not take over)", 0.25, False)
run("silence again", 2, True)
eng.spotify.playing = False
run("Spotify paused", 2, True)
