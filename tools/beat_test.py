"""Measures beat-detection timing quality on whatever is playing (never touches the keyboard).

Real beats are evenly spaced, so we estimate the tempo from the detections and report how far each
detected beat is from the nearest point on that steady grid (timing jitter), plus missed/extra beats.
"""
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mykeys.music.capture import LoopbackCapture  # noqa: E402
from mykeys.music.spotify import SpotifyWatcher  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
sp = SpotifyWatcher().start()
cap = LoopbackCapture().start()
time.sleep(1.5)
print("song:", sp.info.get("artist"), "-", sp.info.get("title"))
a, beats, last = cap.analyzer, [], 0.0
t_end = time.monotonic() + secs
while time.monotonic() < t_end:
    if a.last_beat != last:
        last = a.last_beat
        beats.append(last)
    time.sleep(0.002)
cap.stop()

b = np.array(beats)
if len(b) < 6:
    sys.exit(f"only {len(b)} beats detected in {secs:.0f}s")
iv = np.diff(b)
# tempo: the most common interval, folded into a 70-180 BPM range
cands = np.concatenate([iv, iv / 2, iv * 2])
cands = cands[(cands > 60 / 180) & (cands < 60 / 70)]
hist, edges = np.histogram(cands, bins=np.arange(60 / 180, 60 / 70, 0.01))
period = edges[hist.argmax()] + 0.005
# refine: fit a steady grid (period + phase) by least squares on the beat numbers
n = np.round((b - b[0]) / period)
period, phase = np.polyfit(n, b, 1)
err = (b - (phase + n * period)) * 1000
expected = (b[-1] - b[0]) / period + 1
print(f"{len(b)} beats in {secs:.0f}s -> tempo {60 / period:.1f} BPM")
print(f"timing vs a steady beat grid: median |error| {np.median(np.abs(err)):.0f} ms, "
      f"90th pct {np.percentile(np.abs(err), 90):.0f} ms, worst {np.abs(err).max():.0f} ms")
print(f"beats on the grid: {len(set(n))} of ~{expected:.0f} expected  "
      f"(missed ~{max(0, expected - len(set(n))):.0f}, extra/duplicate {len(n) - len(set(n))})")
