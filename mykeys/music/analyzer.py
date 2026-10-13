"""Audio → 16 frequency bands, L/R levels and beats, normalized to 0..1 for lighting."""
import time

import numpy as np

BANDS = 16


class Analyzer:
    def __init__(self, samplerate=48000, blocksize=1024, bands=BANDS, fmin=45.0, fmax=16000.0, nfft=4096):
        # Blocks arrive every 1024 samples (~21 ms), but the FFT looks at the last 4096 (~85 ms) so the
        # bass bands get ~12 Hz resolution instead of ~47 Hz (otherwise the lowest bars move as one).
        self.sr, self.n, self.nfft = samplerate, blocksize, nfft
        self.buf = np.zeros(nfft, np.float32)
        self.window = np.hanning(nfft).astype(np.float32)
        freqs = np.fft.rfftfreq(nfft, 1 / samplerate)
        edges = np.geomspace(fmin, fmax, bands + 1)
        # FFT bin range per band (at least one bin each, so low bands aren't empty)
        self.ranges = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            idx = np.nonzero((freqs >= lo) & (freqs < hi))[0]
            if idx.size == 0:
                idx = np.array([np.argmin(np.abs(freqs - (lo + hi) / 2))])
            self.ranges.append((idx[0], idx[-1] + 1))
        self.sensitivity = 1.0      # >1 = more reactive
        self.smoothing = 0.7        # decay factor per block (0 = jumpy, 0.95 = slow)
        self.band_peak = np.full(bands, 1e-3, np.float32)
        self.bands = np.zeros(bands, np.float32)
        self.levels = np.zeros(2, np.float32)
        self.level_peak = 1e-3
        self.energy = 0.0           # overall loudness 0..1
        self.bass_hist = []         # ~1 s of bass energy, for beat detection
        self.last_beat = 0.0
        self.beat = 0.0             # 1 at a beat, decays to 0
        self.silent = True
        self.treble_hit = 0.0       # 1 on a hi-hat/cymbal transient, decays
        self.treble_avg = 1e-3
        self.pitch = 0.0            # dominant melody note as 0..1 around the circle of 12 notes
        self.pitch_conf = 0.0
        self.freqs = freqs
        self.melody = np.nonzero((freqs >= 110) & (freqs <= 1100))[0]
        # beat onsets: spectral flux on a short window (precise timing), not the 85 ms band window
        self.owin = np.hanning(1024).astype(np.float32)
        of = np.fft.rfftfreq(1024, 1 / samplerate)
        self.o_low = np.nonzero((of >= 35) & (of <= 180))[0]   # kick / 808 attack
        self.o_mid = np.nonzero((of > 180) & (of <= 3000))[0]  # snare / claps
        self.o_prev = None
        self.flux = []              # ~1 s of onset strength
        # dynamics: 0 = every song fills the board, 1 = loud parts look louder than quiet parts
        self.dynamics = 0.4
        self.loud_ref = 1e-3

    def process(self, block):
        """block: (n, channels) float32 in -1..1."""
        if block.ndim == 1:
            block = block[:, None]
        mono = block.mean(axis=1)[: self.n]
        if mono.size < self.n:
            mono = np.pad(mono, (0, self.n - mono.size))
        rms = np.sqrt((block[: self.n] ** 2).mean(axis=0))
        self.silent = float(rms.max()) < 1e-4

        self.buf = np.concatenate((self.buf[mono.size:], mono))
        mag = np.abs(np.fft.rfft(self.buf * self.window))
        raw = np.array([mag[a:b].mean() for a, b in self.ranges], np.float32)

        # per-band auto-gain: each band follows its own recent peak (quiet and loud songs both fill the board)
        self.band_peak = np.maximum(raw, self.band_peak * 0.997)
        self.band_peak = np.maximum(self.band_peak, 1e-3)
        target = np.clip((raw / self.band_peak) ** (0.8 / self.sensitivity), 0, 1)
        if self.silent:
            target[:] = 0
        # dynamics: scale everything by loudness relative to the loudest moment of the last ~20 s,
        # so a build-up looks smaller than the drop (per-band auto-gain alone flattens that out)
        loud = float(rms.max())
        # reference = loudest of the last ~20 s, but never below a typical loud-music level (Spotify
        # normalizes songs), so a quiet intro or build-up reads as quiet even before the drop arrives
        self.loud_ref = max(loud, self.loud_ref * 0.99926, 0.12)
        rel = min(1.0, loud / self.loud_ref)
        target = target * ((1 - self.dynamics) + self.dynamics * rel ** 0.8)
        rise = target > self.bands  # fast attack, smooth decay
        self.bands = np.where(rise, self.bands + (target - self.bands) * 0.7, self.bands * self.smoothing + target * (1 - self.smoothing))

        self.level_peak = max(float(rms.max()), self.level_peak * 0.998, 1e-3)
        lv = np.clip(rms[:2] / self.level_peak if rms.size > 1 else np.repeat(rms / self.level_peak, 2), 0, 1)
        self.levels = np.maximum(lv, self.levels * 0.85)
        self.energy = float(self.bands.mean())

        # beat: a sudden *rise* in bass energy (spectral flux) that stands out from the last ~1 s,
        # picked at its local peak. Works with sustained 808s, which a loudness threshold misses.
        now = time.monotonic()
        self.beat *= 0.82
        spec = np.log1p(100 * np.abs(np.fft.rfft(self.buf[-1024:] * self.owin)))
        if self.o_prev is not None:
            d = spec - self.o_prev
            f = float(np.maximum(d[self.o_low], 0).sum())  # bass only: hi-hats/snares caused false beats
            self.flux = (self.flux + [f])[-47:]
            if len(self.flux) >= 4:
                prev, cur = self.flux[-2], self.flux[-1]
                hist = np.array(self.flux[:-1])
                thr = max(hist.mean() + (2.0 / self.sensitivity) * hist.std(), 0.35 * hist.max()) + 1e-3
                # a peak: last block rose above the threshold and this block is lower (one block of delay)
                if not self.silent and prev > thr and prev >= self.flux[-3] and cur < prev \
                        and now - self.last_beat > 0.15:
                    self.last_beat, self.beat = now - self.n / self.sr, 1.0
        self.o_prev = spec

        # hi-hat / cymbal transients: top bands jump above their running average
        treble = float(raw[12:].mean())
        self.treble_hit *= 0.7
        if not self.silent and treble > self.treble_avg * 1.6 and treble > self.band_peak[12:].mean() * 0.3:
            self.treble_hit = min(1.0, treble / (self.treble_avg * 3))
        self.treble_avg = self.treble_avg * 0.92 + treble * 0.08

        # dominant note (110 Hz - 1.1 kHz): strongest bin → pitch class on a 0..1 circle
        seg = mag[self.melody]
        k = int(seg.argmax())
        if seg[k] > 0:
            f = float(self.freqs[self.melody[k]])
            self.pitch = ((12 * np.log2(f / 440.0)) % 12) / 12
            self.pitch_conf = float(min(1.0, seg[k] / (seg.mean() * 6 + 1e-9)))

    def snapshot(self):
        return {"bands": self.bands.tolist(), "levels": self.levels.tolist(), "energy": self.energy,
                "beat": self.beat, "beat_t": self.last_beat, "silent": self.silent, "treble": self.treble_hit,
                "pitch": self.pitch, "pitch_conf": self.pitch_conf}
