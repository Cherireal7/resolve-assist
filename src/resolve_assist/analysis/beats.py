"""Tempo and beat grid from audio (stdlib only).

Onset envelope from frame energy rises (full band + high-passed for hats/snares),
tempo from its autocorrelation (60–180 BPM, octave-checked), beat phase by
comb alignment, downbeats as the strongest of the four phases.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

ANALYSIS_RATE = 11025
HOP = 256  # ~43 envelope frames per second


def read_wav_mono(path: Path, max_seconds: float = 900.0) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if width != 2:
            raise ValueError("only 16-bit WAV is supported; convert with ffmpeg")
        n = min(n, int(max_seconds * rate))
        raw = w.readframes(n)
    vals = struct.unpack("<%dh" % (len(raw) // 2), raw)
    mono = [sum(vals[i:i + ch]) / (ch * 32768.0) for i in range(0, len(vals), ch)]
    return mono, rate


def resample(samples: list[float], rate: int, target: int = ANALYSIS_RATE) -> list[float]:
    if rate == target:
        return samples
    step = rate / target
    out = []
    pos = 0.0
    while pos + step <= len(samples):
        a, b = int(pos), int(pos + step)
        out.append(sum(samples[a:b]) / max(1, b - a))
        pos += step
    return out


def onset_envelope(samples: list[float]) -> list[float]:
    env = []
    prev_full = prev_hi = 0.0
    last = 0.0
    for i in range(0, len(samples) - HOP, HOP):
        chunk = samples[i:i + HOP]
        full = sum(x * x for x in chunk) / HOP
        hi = 0.0
        for x in chunk:
            hi += (x - last) ** 2
            last = x
        hi /= HOP
        lf, lh = math.log1p(1000 * full), math.log1p(1000 * hi)
        env.append(max(0.0, lf - prev_full) + max(0.0, lh - prev_hi))
        prev_full, prev_hi = lf, lh
    mean = sum(env) / len(env) if env else 0.0
    return [max(0.0, e - mean) for e in env]


def _autocorr(env: list[float], lag: int) -> float:
    return sum(env[i] * env[i + lag] for i in range(len(env) - lag)) / max(1, len(env) - lag)


def tempo(env: list[float], fps: float, lo: float = 60.0, hi: float = 180.0) -> tuple[float, float]:
    """(bpm, confidence 0..1)."""
    lags = range(max(1, int(fps * 60 / hi)), int(fps * 60 / lo) + 1)
    scores = {lag: _autocorr(env, lag) for lag in lags}
    if not scores or max(scores.values()) <= 0:
        return 0.0, 0.0

    def octave_score(lag: int) -> float:
        # A true beat period also correlates at 2x lag; eighth-note periods don't at 0.5x as strongly.
        s = scores[lag]
        double = _autocorr(env, lag * 2) if lag * 2 < len(env) else 0.0
        prior = math.exp(-0.5 * (math.log2((fps * 60 / lag) / 100.0) / 0.6) ** 2)
        return (s + 0.5 * double) * (0.5 + prior)

    best = max(scores, key=octave_score)
    # Parabolic refinement of the lag.
    l0 = best
    if l0 - 1 in scores and l0 + 1 in scores:
        a, b, c = scores[l0 - 1], scores[l0], scores[l0 + 1]
        denom = a - 2 * b + c
        offset = 0.5 * (a - c) / denom if denom else 0.0
        l0 = best + max(-0.5, min(0.5, offset))
    vals = sorted(scores.values(), reverse=True)
    conf = 1.0 - (vals[len(vals) // 2] / vals[0]) if vals[0] > 0 else 0.0
    return 60.0 * fps / l0, max(0.0, min(1.0, conf))


def beat_grid(env: list[float], fps: float, bpm: float) -> tuple[list[float], list[float]]:
    period = 60.0 * fps / bpm
    n = len(env)
    best_phase, best = 0.0, -1.0
    steps = max(1, int(period))
    for k in range(steps * 4):
        phase = k / 4.0
        s = 0.0
        t = phase
        while t < n:
            s += env[int(t)]
            t += period
        if s > best:
            best, best_phase = s, phase
    beats = []
    t = best_phase
    while t < n:
        beats.append(t / fps)
        t += period
    # Downbeat: which of the 4 beat positions carries the most onset energy.
    sums = [0.0] * 4
    for i, b in enumerate(beats):
        sums[i % 4] += env[min(n - 1, int(b * fps))]
    first = max(range(4), key=lambda i: sums[i])
    return beats, beats[first::4]


def analyze_audio(path: Path) -> dict:
    samples, rate = read_wav_mono(path)
    duration = len(samples) / rate
    x = resample(samples, rate)
    env = onset_envelope(x)
    fps = ANALYSIS_RATE / HOP
    bpm, conf = tempo(env, fps)
    beats, downbeats = beat_grid(env, fps, bpm) if bpm else ([], [])
    return {"duration": round(duration, 3), "bpm": round(bpm, 2), "confidence": round(conf, 2),
            "beats": [round(b, 3) for b in beats], "downbeats": [round(b, 3) for b in downbeats]}
