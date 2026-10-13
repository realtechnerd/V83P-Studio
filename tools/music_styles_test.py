"""Dry run of every music style on live audio (never touches the keyboard)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mykeys.music.capture import LoopbackCapture  # noqa: E402
from mykeys.music.spotify import SpotifyWatcher  # noqa: E402
from mykeys.music.visualizers import STYLES, Visualizer  # noqa: E402

from mykeys.boards import current as BOARD  # noqa: E402
layout = BOARD.layout
vis = Visualizer(layout)
sp = SpotifyWatcher().start()
cap = LoopbackCapture().start()
time.sleep(2)
print("spotify:", sp.info.get("artist"), "-", sp.info.get("title"), "| album palette:", sp.album)
for style in STYLES:
    lit, bright, cost, t_end = [], [], [], time.monotonic() + 1.5
    while time.monotonic() < t_end:
        snap = cap.analyzer.snapshot()
        t0 = time.perf_counter()
        colors = vis.frame(snap, time.monotonic(), style, sp.album or "matcha")
        cost.append((time.perf_counter() - t0) * 1000)
        on = [c for c in colors if c and sum(c) > 24]
        lit.append(len(on))
        bright.append(sum(sum(c) for c in on) / (3 * 255 * max(1, len(on))))
        time.sleep(1 / 30)
    print(f"{style:11s} lit LEDs min/avg/max {min(lit):2d}/{sum(lit) / len(lit):4.1f}/{max(lit):2d}   "
          f"avg brightness {sum(bright) / len(bright):.2f}   {sum(cost) / len(cost):.2f} ms/frame")
a = cap.analyzer.snapshot()
print(f"pitch {a['pitch']:.2f} (conf {a['pitch_conf']:.2f})  treble hit {a['treble']:.2f}")
cap.stop()
