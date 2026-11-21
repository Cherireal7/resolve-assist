"""Small DSP toolbox (stdlib only) shared by the SFX and music generators.

Everything works on plain lists of floats (mono). Nothing here is fast, but every asset is
rendered once and kept, so clarity wins over speed.
"""

from __future__ import annotations

import math
import random

TWO_PI = 2 * math.pi
Mono = list[float]
Stereo = tuple[list[float], list[float]]


class Biquad:
    """RBJ biquad filter. kind: 'lp' | 'hp' | 'bp'. `set` may be called any time to move it."""

    __slots__ = ("kind", "rate", "b0", "b1", "b2", "a1", "a2", "x1", "x2", "y1", "y2")

    def __init__(self, kind: str, cutoff: float, rate: int, q: float = 0.707) -> None:
        self.kind, self.rate = kind, rate
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self.set(cutoff, q)

    def set(self, cutoff: float, q: float = 0.707) -> None:
        w = TWO_PI * min(max(cutoff, 10.0), self.rate * 0.45) / self.rate
        c, alpha = math.cos(w), math.sin(w) / (2 * q)
        a0 = 1 + alpha
        if self.kind == "lp":
            b0, b1, b2 = (1 - c) / 2, 1 - c, (1 - c) / 2
        elif self.kind == "hp":
            b0, b1, b2 = (1 + c) / 2, -(1 + c), (1 + c) / 2
        else:  # band-pass, 0 dB peak gain
            b0, b1, b2 = alpha, 0.0, -alpha
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = -2 * c / a0, (1 - alpha) / a0

    def __call__(self, x: float) -> float:
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


def filt(sig: Mono, kind: str, cutoff: float, rate: int, q: float = 0.707) -> Mono:
    f = Biquad(kind, cutoff, rate, q)
    return [f(x) for x in sig]


def sweep(sig: Mono, kind: str, f0: float, f1: float, rate: int, q: float = 0.707, every: int = 32) -> Mono:
    """Filter whose cutoff glides exponentially from f0 to f1 over the signal."""
    f = Biquad(kind, f0, rate, q)
    n = max(1, len(sig))
    out = []
    for i, x in enumerate(sig):
        if i % every == 0:
            f.set(f0 * (f1 / f0) ** (i / n), q)
        out.append(f(x))
    return out


def noise(n: int, seed: int = 0) -> Mono:
    rnd = random.Random(seed)
    return [rnd.uniform(-1.0, 1.0) for _ in range(n)]


def tone(freq: float, n: int, rate: int, shape: str = "sine", f_end: float | None = None,
         vibrato: tuple[float, float] = (0.0, 0.0)) -> Mono:
    """Oscillator with an optional exponential glide to f_end and vibrato (rate Hz, depth 0..1)."""
    out = []
    phase = 0.0
    ratio = (f_end / freq) if f_end else 1.0
    vr, vd = vibrato
    for i in range(n):
        f = freq * ratio ** (i / n) if f_end else freq
        if vd:
            f *= 1.0 + vd * math.sin(TWO_PI * vr * i / rate)
        phase += f / rate
        p = phase % 1.0
        if shape == "sine":
            out.append(math.sin(TWO_PI * p))
        elif shape == "saw":
            out.append(2.0 * p - 1.0)
        elif shape == "square":
            out.append(1.0 if p < 0.5 else -1.0)
        else:  # triangle
            out.append(4.0 * abs(p - 0.5) - 1.0)
    return out


def decay(sig: Mono, rate: int, per_second: float, attack: float = 0.002) -> Mono:
    """Exponential decay envelope with a short linear attack (seconds)."""
    a = max(1, int(attack * rate))
    return [x * math.exp(-i / rate * per_second) * min(1.0, i / a) for i, x in enumerate(sig)]


def fade(sig: Mono, rate: int, fade_in: float = 0.0, fade_out: float = 0.0) -> Mono:
    n = len(sig)
    a, b = int(fade_in * rate), int(fade_out * rate)
    return [x * (min(1.0, i / a) if a else 1.0) * (min(1.0, (n - i) / b) if b else 1.0) for i, x in enumerate(sig)]


def gain(sig: Mono, g: float) -> Mono:
    return [x * g for x in sig]


def mix(dst: Mono, src: Mono, at: int = 0, g: float = 1.0) -> Mono:
    """Add src into dst starting at sample `at` (dst grows when needed). Returns dst."""
    need = at + len(src) - len(dst)
    if need > 0:
        dst.extend([0.0] * need)
    for i, x in enumerate(src):
        dst[at + i] += x * g
    return dst


def soft_clip(sig: Mono, drive: float = 1.5) -> Mono:
    k = math.tanh(drive)
    return [math.tanh(x * drive) / k for x in sig]


def reverb(sig: Mono, rate: int, tail: float = 1.5, wet: float = 0.3, size: float = 1.0) -> Mono:
    """Schroeder reverb: four damped combs into two all-passes. Output is `tail` seconds longer."""
    n = len(sig) + int(tail * rate)
    src = sig + [0.0] * (n - len(sig))
    acc = [0.0] * n
    for ms in (29.7, 37.1, 41.1, 43.7):
        d = max(1, int(ms * size * rate / 1000))
        g = 10 ** (-3.0 * (d / rate) / max(0.05, tail))   # reach -60 dB after `tail` seconds
        buf = [0.0] * d
        lp = 0.0
        k = 0
        for i in range(n):
            y = buf[k]
            lp += 0.4 * (y - lp)                          # darker repeats = more natural
            buf[k] = src[i] + lp * g
            acc[i] += y
            k = k + 1 if k + 1 < d else 0
    for ms in (5.0, 1.7):
        d = max(1, int(ms * rate / 1000))
        buf = [0.0] * d
        k = 0
        for i in range(n):
            y = buf[k]
            x = acc[i]
            buf[k] = x + y * 0.7
            acc[i] = y - x * 0.7
            k = k + 1 if k + 1 < d else 0
    return [src[i] * (1.0 - wet) + acc[i] * wet * 0.25 for i in range(n)]


def pluck(freq: float, seconds: float, rate: int, seed: int = 0, damp: float = 0.996, bright: float = 0.6) -> Mono:
    """Karplus-Strong plucked string (guitar, harp, krar-like)."""
    rnd = random.Random(seed)
    d = max(2, int(rate / freq))
    buf = []
    prev = 0.0
    for _ in range(d):
        x = rnd.uniform(-1.0, 1.0)
        prev += bright * (x - prev)        # darker excitation = softer pick
        buf.append(prev)
    out = []
    k = 0
    for _ in range(int(seconds * rate)):
        nxt = k + 1 if k + 1 < d else 0
        y = buf[k]
        buf[k] = damp * 0.5 * (y + buf[nxt])
        out.append(y)
        k = nxt
    return out


def pan(mono: Mono, p: float = 0.0) -> Stereo:
    """Equal-power pan, p from -1 (left) to 1 (right)."""
    l, r = math.sqrt((1 - p) / 2), math.sqrt((1 + p) / 2)
    return [x * l for x in mono], [x * r for x in mono]


def widen(mono: Mono, rate: int, ms: float = 11.0) -> Stereo:
    """Haas widening: the right channel is a slightly delayed copy."""
    d = int(ms * rate / 1000)
    return list(mono), ([0.0] * d + mono)[:len(mono)]


def midi_freq(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)
