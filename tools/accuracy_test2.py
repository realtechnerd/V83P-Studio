"""Accuracy test part 2:
  4. do beat-driven styles (ripple) actually draw every detected beat at 30 fps?  (offline, simulated)
  5. does the keyboard show exactly what was sent?  (streams one test frame, reads it back, restores)
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mykeys.music.analyzer as an  # noqa: E402
from mykeys.music.visualizers import Visualizer  # noqa: E402

SR, BLOCK = 48000, 1024
from mykeys.boards import current as BOARD  # noqa: E402
layout = BOARD.layout
clock = {"t": 0.0}
an.time.monotonic = lambda: clock["t"]
rng = np.random.default_rng(2)

# --- 4. ripple sampling at 30 fps on a clean 120 BPM kick track ---
t = np.arange(int(SR * 0.15)) / SR
kick = 0.8 * np.sin(2 * np.pi * np.cumsum(45 + 65 * np.exp(-t * 30)) / SR) * np.exp(-t * 18)
sig = 0.01 * rng.standard_normal(SR * 16)
for n in range(32):
    i = int(n * 0.5 * SR)
    sig[i:i + len(kick)] += kick[: len(sig) - i]
a, vis = an.Analyzer(SR, BLOCK), Visualizer(layout)
beats, last, next_frame, ring_ids = 0, 0.0, 0.0, set()
# The real app runs the visual loop on its own 30 fps timer, so its phase vs the audio blocks is
# arbitrary; try several phase offsets and report the average.
results = []
for phase in np.linspace(0, 1 / 30, 6, endpoint=False):
    clock["t"], a, vis = 0.0, an.Analyzer(SR, BLOCK), Visualizer(layout)
    beats, last, next_frame, ring_ids = 0, 0.0, phase, set()
    for i in range(0, len(sig) - BLOCK + 1, BLOCK):
        clock["t"] += BLOCK / SR
        a.process(np.repeat(sig[i:i + BLOCK, None], 2, axis=1).astype(np.float32))
        if a.last_beat != last:
            last, beats = a.last_beat, beats + 1
        while next_frame <= clock["t"]:
            vis.frame(a.snapshot(), next_frame, "ripple")
            ring_ids.update(r[0] for r in vis.rings)   # each ring is identified by its start time
            next_frame += 1 / 30
    results.append((beats, len(ring_ids)))
beats = int(np.mean([r[0] for r in results]))
rings = np.mean([r[1] for r in results])
print("4. RIPPLE SAMPLING (30 fps visual loop)")
print(f"   beats detected {beats}, ripples drawn {rings} → {rings / max(1, beats) * 100:.0f}% of detected beats shown")

# --- 5. delivery: stream a known frame to the keyboard and read it back ---
if "--keyboard" in sys.argv:
    from mykeys.device import Keyboard
    from mykeys.perkey import PerKey
    print("5. DELIVERY (keyboard readback)")
    with Keyboard() as kb:
        pk = PerKey(kb)
        saved, info = pk.read_all(), pk.detect()
        frame = [tuple(int(v) for v in rng.integers(0, 256, 3)) for _ in range(92)]
        pk.clear()
        pk.stream(frame)
        back = pk.read_all()
        exact = sum(1 for i, c in enumerate(frame) if back.get(i) == "#%02x%02x%02x" % c)
        print(f"   {exact}/92 LEDs on the keyboard exactly match the sent frame")
        pk.clear()
        if saved:
            pk.set_leds(saved)
        pk.enable(info[2])
        print("   your colors restored:", pk.read_all() == saved)
