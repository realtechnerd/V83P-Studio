"""Dry run of music mode: capture + analysis + visualizer, printed to the terminal. Never touches the keyboard."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mykeys.music.capture import LoopbackCapture  # noqa: E402
from mykeys.music.spotify import SpotifyWatcher  # noqa: E402
from mykeys.music.visualizers import Visualizer  # noqa: E402

from mykeys.boards import current as BOARD  # noqa: E402
layout = BOARD.layout
vis = Visualizer(layout)
print(f"visualizer: {vis.rows} key rows, {vis.bands} columns, VU strips {len(vis.vu[0])}+{len(vis.vu[1])} LEDs")
sp = SpotifyWatcher().start()
cap = LoopbackCapture().start()
time.sleep(1.5)
print("spotify:", sp.info, "| device:", cap.device, "| error:", cap.error)
beats, t0, frames = 0, time.monotonic(), 0
BARS = " ▁▂▃▄▅▆▇█"
while time.monotonic() - t0 < 6:
    snap = cap.analyzer.snapshot()
    colors = vis.frame(snap, time.monotonic())
    frames += 1
    if snap["beat"] > 0.95:
        beats += 1
    if frames % 6 == 0:
        bars = "".join(BARS[min(8, int(b * 8.99))] for b in snap["bands"])
        lit = sum(1 for c in colors if c and sum(c) > 30)
        print(f"|{bars}|  L{snap['levels'][0]:.2f} R{snap['levels'][1]:.2f}  energy {snap['energy']:.2f}  "
              f"{'BEAT' if snap['beat'] > 0.6 else '    '}  lit LEDs {lit:2d}")
    time.sleep(1 / 30)
cap.stop()
print(f"{frames / 6:.0f} visual fps, {beats} beat frames in 6 s")
