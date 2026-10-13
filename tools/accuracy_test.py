"""Accuracy test for music mode using synthetic audio with known answers (offline, no audio device).

Feeds generated signals through the real Analyzer + Visualizer with a simulated clock and checks:
  1. frequency → column mapping (pure tones)
  2. loudness tracking (volume steps)
  3. beat detection vs a known 120 BPM click track (plain and with a sustained 808 under it)
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
an.time.monotonic = lambda: clock["t"]  # simulated time for the analyzer's beat logic
rng = np.random.default_rng(1)


def pink(n):
    w = rng.standard_normal(n)
    f = np.fft.rfft(w)
    f /= np.sqrt(np.maximum(np.arange(len(f)), 1))
    x = np.fft.irfft(f, n)
    return x / np.abs(x).max()


def feed(a, sig, on_block=None):
    for i in range(0, len(sig) - BLOCK + 1, BLOCK):
        clock["t"] += BLOCK / SR
        a.process(np.repeat(sig[i:i + BLOCK, None], 2, axis=1).astype(np.float32))
        if on_block:
            on_block(a, clock["t"])


def tone(f, secs, amp=0.3):
    t = np.arange(int(SR * secs)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def band_of(a, f):
    return next((k for k, (lo, hi) in enumerate(a.ranges) if lo <= f / (SR / a.nfft) < hi), None)


print("=" * 78)
print("1. FREQUENCY → COLUMN  (after 3 s of pink-noise warm-up, then a 1 s pure tone)")
print("=" * 78)
vis = Visualizer(layout)
results = []
for f in (60, 120, 250, 500, 1000, 2000, 4000, 8000, 12000):
    a = an.Analyzer(SR, BLOCK)
    feed(a, 0.2 * pink(SR * 3))
    feed(a, tone(f, 1.0))
    b = a.bands
    expect = band_of(a, f)
    top = int(b.argmax())
    others = np.delete(b, top)
    frame = vis.frame(a.snapshot(), clock["t"], "spectrum")
    lit_cols = sorted({vis.col[i] for i in vis.keys if frame[i] and sum(frame[i]) > 40})
    results.append((f, expect, top, b[top], others.max(), others.mean(), lit_cols))
    print(f"{f:6d} Hz  expected col {expect:2d}  brightest col {top:2d} ({b[top]:.2f})  "
          f"other cols max {others.max():.2f} / avg {others.mean():.2f}   lit columns: {lit_cols}")
ok = sum(1 for r in results if abs(r[1] - r[2]) <= 1)
print(f"→ right column (±1) for {ok}/{len(results)} tones")

print("\n  1b. same tone held for 10 s (does the rest of the board creep up?)")
a = an.Analyzer(SR, BLOCK)
feed(a, 0.2 * pink(SR * 3))
for secs in (1, 3, 10):
    feed(a, tone(1000, 1 if secs == 1 else (2 if secs == 3 else 7)))
    others = np.delete(a.bands, band_of(a, 1000))
    print(f"     after {secs:2d} s of 1 kHz: other columns avg {others.mean():.2f}, max {others.max():.2f}")

print("\n" + "=" * 78)
print("2. LOUDNESS  (pink noise, volume stepped every 2 s)")
print("=" * 78)
a = an.Analyzer(SR, BLOCK)
for db in (-30, -18, -6, -18, -30, 0):
    amp = 10 ** (db / 20)
    samples = []
    feed(a, amp * pink(SR * 2), lambda x, t: samples.append((x.energy, x.levels[0])))
    early = np.mean([s[0] for s in samples[5:20]])
    late = np.mean([s[0] for s in samples[-20:]])
    print(f"  {db:+4d} dB: energy first 0.4 s {early:.2f} → after 2 s {late:.2f}   VU level {samples[-1][1]:.2f}")

print("\n" + "=" * 78)
print("3. BEATS vs a known 120 BPM drum track (16 s)")
print("=" * 78)


def kick(secs=0.15, f0=110, f1=45):
    t = np.arange(int(SR * secs)) / SR
    f = f1 + (f0 - f1) * np.exp(-t * 30)
    return 0.8 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 18)


def track(secs, bpm, with_808=False, hats=True):
    x = np.zeros(int(SR * secs))
    period, k = 60 / bpm, kick()
    truth = []
    for n in range(int(secs / period)):
        i = int(n * period * SR)
        truth.append(n * period)
        x[i:i + len(k)] += k[: len(x) - i]
        if hats:  # off-beat hi-hats
            j = int((n + 0.5) * period * SR)
            h = 0.15 * rng.standard_normal(int(SR * 0.03)) * np.exp(-np.arange(int(SR * 0.03)) / 300)
            x[j:j + len(h)] += h[: max(0, len(x) - j)]
    if with_808:  # long sustained 808 note under every bar (like trap), restarting every 2 beats
        for n in range(0, int(secs / period), 2):
            i = int(n * period * SR)
            t = np.arange(int(SR * period * 2)) / SR
            note = 0.5 * np.sin(2 * np.pi * 50 * t) * np.exp(-t * 0.8)
            x[i:i + len(note)] += note[: len(x) - i]
    x += 0.02 * pink(len(x))
    return x / np.abs(x).max() * 0.6, np.array(truth)


for name, with_808 in (("plain kick + hats", False), ("kick + sustained 808 (trap-style)", True)):
    a = an.Analyzer(SR, BLOCK)
    clock["t"] = 0.0
    sig, truth = track(16, 120, with_808)
    det, last = [], 0.0

    def watch(x, t):
        global last
        if x.last_beat != last:
            last = x.last_beat
            det.append(t)

    feed(a, sig, watch)
    det = np.array(det)
    truth = truth[truth > 1.0]  # skip the first second (averages warming up)
    det = det[det > 1.0]
    hits, lat = 0, []
    for tb in truth:
        d = det - tb
        m = d[(d > -0.03) & (d < 0.12)]
        if m.size:
            hits += 1
            lat.append(m.min() * 1000)
    false = sum(1 for td in det if not np.any(np.abs(truth - td) < 0.12))
    print(f"  {name}:")
    print(f"     beats caught {hits}/{len(truth)} ({hits / len(truth) * 100:.0f}%), false beats {false}, "
          f"detection delay {np.mean(lat):.0f} ms avg ({min(lat):.0f}–{max(lat):.0f})" if lat else
          f"     beats caught 0/{len(truth)}, false beats {false}")
