"""Sound effects synthesized from scratch (stdlib only): whooshes, risers, impacts, pops...

Everything here is generated, so it is free to use anywhere. Each recipe returns stereo
float samples; `write_wav` normalizes and writes 16-bit 48 kHz WAV (Resolve's native rate).
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable

RATE = 48000
TWO_PI = 2 * math.pi
Stereo = tuple[list[float], list[float]]


def _n(seconds: float) -> int:
    return int(seconds * RATE)


class _Filter:
    """One-pole low-pass with a cutoff that may change every sample."""

    def __init__(self) -> None:
        self.y = 0.0

    def lp(self, x: float, cutoff: float) -> float:
        a = 1.0 - math.exp(-TWO_PI * max(10.0, cutoff) / RATE)
        self.y += a * (x - self.y)
        return self.y


def _noise_sweep(seconds: float, f0: float, f1: float, peak_at: float, seed: int,
                 pan: tuple[float, float] = (-0.8, 0.8)) -> Stereo:
    """Band-limited noise whose brightness sweeps f0→f1, with a swell peaking at peak_at (0..1)."""
    rnd = random.Random(seed)
    lo, hi = _Filter(), _Filter()
    n = _n(seconds)
    left, right = [0.0] * n, [0.0] * n
    for i in range(n):
        u = i / n
        cutoff = f0 * (f1 / f0) ** u
        x = rnd.uniform(-1, 1)
        band = hi.lp(x, cutoff * 1.8) - lo.lp(x, cutoff * 0.5)      # crude band-pass
        env = (u / peak_at) ** 2 if u < peak_at else ((1 - u) / (1 - peak_at)) ** 1.5
        p = pan[0] + (pan[1] - pan[0]) * u                           # stereo movement
        left[i] = band * env * math.sqrt((1 - p) / 2)
        right[i] = band * env * math.sqrt((1 + p) / 2)
    return left, right


def whoosh(seconds: float = 0.9, seed: int = 1) -> Stereo:
    return _noise_sweep(seconds, 300, 4000, 0.55, seed)


def swoosh(seconds: float = 0.4, seed: int = 2) -> Stereo:
    return _noise_sweep(seconds, 800, 7000, 0.35, seed, pan=(0.6, -0.6))


def whoosh_low(seconds: float = 1.4, seed: int = 3) -> Stereo:
    return _noise_sweep(seconds, 120, 1500, 0.6, seed)


def reverse_swell(seconds: float = 1.6, seed: int = 4) -> Stereo:
    l, r = _noise_sweep(seconds, 200, 6000, 0.97, seed, pan=(0, 0))
    tone = [0.4 * math.sin(TWO_PI * 220 * i / RATE) * (i / len(l)) ** 3 for i in range(len(l))]
    return [a + b for a, b in zip(l, tone)], [a + b for a, b in zip(r, tone)]


def riser(seconds: float = 3.0, seed: int = 5) -> Stereo:
    rnd = random.Random(seed)
    n = _n(seconds)
    f = _Filter()
    out = []
    phase = 0.0
    for i in range(n):
        u = i / n
        freq = 180 * (8 ** u)                      # 3 octaves up
        phase += TWO_PI * freq / RATE
        tone = math.sin(phase) + 0.3 * math.sin(2.01 * phase)
        noise = f.lp(rnd.uniform(-1, 1), 500 + 9000 * u)
        out.append((0.5 * tone + 0.6 * noise) * u ** 2)
    return out, list(out)


def impact(seconds: float = 2.2, seed: int = 6) -> Stereo:
    rnd = random.Random(seed)
    n = _n(seconds)
    f = _Filter()
    out = []
    phase = 0.0
    for i in range(n):
        t = i / RATE
        freq = 45 + 120 * math.exp(-t * 18)        # pitch drop = weight
        phase += TWO_PI * freq / RATE
        body = math.sin(phase) * math.exp(-t * 2.2)
        crack = f.lp(rnd.uniform(-1, 1), 6000) * math.exp(-t * 30)
        out.append(0.9 * body + 0.5 * crack)
    return out, list(out)


def hit(seconds: float = 0.35, seed: int = 7) -> Stereo:
    rnd = random.Random(seed)
    out = []
    phase = 0.0
    for i in range(_n(seconds)):
        t = i / RATE
        phase += TWO_PI * (90 + 200 * math.exp(-t * 40)) / RATE
        out.append(math.sin(phase) * math.exp(-t * 14) + rnd.uniform(-1, 1) * 0.4 * math.exp(-t * 60))
    return out, list(out)


def sub_drop(seconds: float = 1.8, seed: int = 0) -> Stereo:
    out = []
    phase = 0.0
    for i in range(_n(seconds)):
        u = i / _n(seconds)
        phase += TWO_PI * (90 * (0.3 ** u)) / RATE
        out.append(math.sin(phase) * (1 - u) ** 0.7 * min(1.0, i / 400))
    return out, list(out)


def pop(seconds: float = 0.15, seed: int = 0) -> Stereo:
    out = []
    phase = 0.0
    for i in range(_n(seconds)):
        t = i / RATE
        phase += TWO_PI * (300 + 900 * math.exp(-t * 60)) / RATE
        out.append(math.sin(phase) * math.exp(-t * 35))
    return out, list(out)


def click(seconds: float = 0.05, seed: int = 8) -> Stereo:
    rnd = random.Random(seed)
    out = [rnd.uniform(-1, 1) * math.exp(-i / RATE * 400) for i in range(_n(seconds))]
    return out, list(out)


def shutter(seconds: float = 0.35, seed: int = 9) -> Stereo:
    l1, _ = click(0.05, seed)
    l2, _ = click(0.05, seed + 1)
    out = [0.0] * _n(seconds)
    for i, v in enumerate(l1):
        out[i] += v
    off = _n(0.12)
    for i, v in enumerate(l2):
        if off + i < len(out):
            out[off + i] += 0.8 * v
    return out, list(out)


def ding(seconds: float = 1.5, seed: int = 0) -> Stereo:
    partials = [(1.0, 1.0), (2.76, 0.5), (5.4, 0.25), (8.93, 0.12)]   # bell-like inharmonic ratios
    out = []
    for i in range(_n(seconds)):
        t = i / RATE
        out.append(sum(a * math.sin(TWO_PI * 880 * r * t) * math.exp(-t * (2 + 3 * r)) for r, a in partials))
    return out, list(out)


def glitch(seconds: float = 0.6, seed: int = 10) -> Stereo:
    rnd = random.Random(seed)
    n = _n(seconds)
    left, right = [0.0] * n, [0.0] * n
    i = 0
    while i < n:
        seg = rnd.randint(_n(0.01), _n(0.06))
        kind = rnd.random()
        freq = rnd.choice([110, 220, 440, 880, 1760])
        for j in range(seg):
            if i + j >= n:
                break
            t = (i + j) / RATE
            if kind < 0.4:
                v = 1.0 if math.sin(TWO_PI * freq * t) > 0 else -1.0     # square burst
            elif kind < 0.7:
                v = rnd.uniform(-1, 1)                                   # noise burst
            else:
                v = 0.0                                                  # dropout
            v = round(v * 4) / 4                                         # bit-crush
            left[i + j] = v * 0.6
            right[i + j] = v * 0.6 * (1 if rnd.random() > 0.2 else -1)
        i += seg
    return left, right


def typing(seconds: float = 2.0, seed: int = 11) -> Stereo:
    rnd = random.Random(seed)
    out = [0.0] * _n(seconds)
    t = 0.05
    while t < seconds - 0.06:
        c, _ = click(0.04, rnd.randint(0, 9999))
        off = _n(t)
        gain = rnd.uniform(0.4, 0.9)
        for j, v in enumerate(c):
            if off + j < len(out):
                out[off + j] += v * gain
        t += rnd.uniform(0.06, 0.18)
    return out, list(out)


RECIPES: dict[str, tuple[Callable[..., Stereo], dict, list[str], str]] = {
    "whoosh-medium": (whoosh, {}, ["whoosh", "transition", "movement"], "Under a cut or a fast pan"),
    "whoosh-long-low": (whoosh_low, {}, ["whoosh", "transition", "deep"], "Slow, heavy transitions"),
    "swoosh-fast": (swoosh, {}, ["swoosh", "transition", "fast", "text"], "Quick text pops, whip pans"),
    "whoosh-02": (whoosh, {"seed": 21, "seconds": 0.7}, ["whoosh", "transition"], "Alternative whoosh"),
    "reverse-swell": (reverse_swell, {}, ["riser", "reverse", "build-up"], "End it exactly on the cut"),
    "riser-3s": (riser, {}, ["riser", "build-up", "tension"], "Build tension before a reveal/drop"),
    "riser-short": (riser, {"seconds": 1.5, "seed": 15}, ["riser", "build-up"], "Short build into a cut"),
    "impact-boom": (impact, {}, ["impact", "boom", "cinematic", "hit"], "Logo/title reveal, big cut"),
    "hit-punch": (hit, {}, ["hit", "punch", "beat"], "Accents on beats, fast cuts"),
    "sub-drop": (sub_drop, {}, ["drop", "bass", "cinematic"], "After a riser, on the drop"),
    "pop-bubble": (pop, {}, ["pop", "ui", "text", "cute"], "Stickers, icons, text appearing"),
    "click-ui": (click, {}, ["click", "ui", "tick"], "UI/menu clicks, counters"),
    "camera-shutter": (shutter, {}, ["camera", "photo", "freeze-frame"], "Freeze frames, photo moments"),
    "ding-bell": (ding, {}, ["ding", "notification", "bell", "success"], "Reveals, prices, 'done!' moments"),
    "glitch-burst": (glitch, {}, ["glitch", "digital", "transition"], "Glitch transitions, tech look"),
    "typing": (typing, {}, ["typing", "keyboard", "text"], "Typewriter text animations"),
}


def write_wav(path: Path, stereo: Stereo, peak: float = 0.89) -> float:
    left, right = stereo
    m = max(max(map(abs, left), default=0.0), max(map(abs, right), default=0.0)) or 1.0
    k = peak / m
    data = bytearray()
    fade = min(len(left), 96)  # 2 ms fade-out avoids a click at the end
    for i, (a, b) in enumerate(zip(left, right)):
        g = k * (len(left) - i) / fade if i > len(left) - fade else k
        data += struct.pack("<hh", int(max(-1, min(1, a * g)) * 32767), int(max(-1, min(1, b * g)) * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(data))
    return len(left) / RATE
