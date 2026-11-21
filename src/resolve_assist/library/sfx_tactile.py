"""Tactile sound effects: clicks, taps, paper, pens, stamps (stdlib only).

Small, dry, close sounds for text, labels, cuts and reveals, so an edit does not lean on whooshes.
"""

from __future__ import annotations

import math
import random
from typing import Callable

from ..dsp import TWO_PI, Stereo, decay, fade, filt, mix, noise, pluck, tone, widen
from .sfx import RATE, _n


def _st(mono: list[float]) -> Stereo:
    return mono, list(mono)


def _tick(freq: float, q: float, rate_d: float, seconds: float, seed: int) -> list[float]:
    return decay(filt(noise(_n(seconds), seed), "bp", freq, RATE, q), RATE, rate_d, 0.0004)


def click_soft(seed: int = 101) -> Stereo:
    out = _tick(1900, 3.0, 190, 0.035, seed)
    mix(out, decay(tone(240, _n(0.03), RATE, "sine", 150), RATE, 120), 0, 0.5)
    return _st(out)


def click_mech(seed: int = 102) -> Stereo:
    out = _tick(3200, 5.0, 260, 0.03, seed)
    mix(out, _tick(1500, 3.0, 170, 0.04, seed + 1), _n(0.045), 0.8)
    return _st(out)


def switch(seed: int = 103) -> Stereo:
    out = _tick(2400, 6.0, 300, 0.02, seed)
    mix(out, _tick(900, 2.5, 110, 0.06, seed + 1), _n(0.022), 1.0)
    mix(out, decay(tone(180, _n(0.05), RATE, "sine", 110), RATE, 70), _n(0.022), 0.6)
    return _st(out)


def tap_wood(freq: float = 420, seed: int = 104) -> Stereo:
    out = decay(tone(freq, _n(0.16), RATE), RATE, 38, 0.0006)
    mix(out, decay(tone(freq * 2.7, _n(0.08), RATE), RATE, 80, 0.0006), 0, 0.35)
    mix(out, _tick(1800, 2.0, 220, 0.02, seed), 0, 0.5)
    return _st(out)


def tap_glass(seed: int = 105) -> Stereo:
    out: list[float] = []
    for f, a, d in ((2850, 1.0, 16), (5270, 0.5, 24), (7900, 0.25, 34)):
        mix(out, decay(tone(f, _n(0.35), RATE), RATE, d, 0.0005), 0, a)
    mix(out, _tick(4000, 2.0, 300, 0.012, seed), 0, 0.4)
    return widen(out, RATE, 4)


def stamp(seed: int = 106) -> Stereo:
    out = decay(tone(130, _n(0.22), RATE, "sine", 60), RATE, 26, 0.001)
    mix(out, decay(filt(noise(_n(0.07), seed), "lp", 1800, RATE), RATE, 70, 0.0004), 0, 0.8)
    mix(out, decay(filt(noise(_n(0.12), seed + 1), "bp", 3000, RATE, 0.8), RATE, 40), _n(0.05), 0.12)   # paper give
    return _st(out)


def _rough(seconds: float, lo: float, hi: float, wobble: float, seed: int, swell: float = 0.5) -> list[float]:
    """Friction noise: band-limited, with a fast uneven tremor (fibres, nib on paper)."""
    rnd = random.Random(seed)
    src = filt(filt(noise(_n(seconds), seed), "hp", lo, RATE), "lp", hi, RATE)
    n = len(src)
    out, level, target = [], 0.5, 0.5
    for i, x in enumerate(src):
        if i % max(1, int(RATE / wobble)) == 0:
            target = rnd.uniform(0.25, 1.0)
        level += 0.02 * (target - level)
        u = i / n
        env = (u / swell) ** 0.7 if u < swell else ((1 - u) / (1 - swell)) ** 1.2
        out.append(x * level * env)
    return out


def paper_slide(seed: int = 107) -> Stereo:
    return widen(_rough(0.38, 1500, 7500, 60, seed, 0.35), RATE, 6)


def page_turn(seed: int = 108) -> Stereo:
    out = _rough(0.32, 900, 6000, 45, seed, 0.6)
    mix(out, _rough(0.14, 2500, 9000, 90, seed + 1, 0.2), _n(0.3), 0.9)       # the flick at the end
    mix(out, _tick(700, 1.5, 90, 0.05, seed + 2), _n(0.4), 0.5)               # page lands
    return widen(out, RATE, 8)


def pen_scribble(seed: int = 109) -> Stereo:
    out: list[float] = []
    t = 0.0
    rnd = random.Random(seed)
    for k in range(5):                                   # short back-and-forth strokes
        ln = rnd.uniform(0.07, 0.13)
        mix(out, _rough(ln, 2200, 8000, 140, seed + k, 0.4), _n(t), rnd.uniform(0.6, 1.0))
        t += ln * 0.85
    return _st(out)


def marker_stroke(seed: int = 110) -> Stereo:
    body = _rough(0.5, 1200, 5200, 30, seed, 0.3)
    squeak = [0.05 * math.sin(TWO_PI * (2300 + 500 * (i / len(body))) * i / RATE) * (0.5 + 0.5 * math.sin(TWO_PI * 23 * i / RATE)) for i in range(len(body))]
    return _st(fade([a + b * abs(a) * 6 for a, b in zip(body, squeak)], RATE, 0.01, 0.06))


def pencil_tick(seed: int = 111) -> Stereo:
    return _st(_rough(0.07, 3000, 9000, 200, seed, 0.3))


def tape_stick(seed: int = 112) -> Stereo:
    rnd = random.Random(seed)
    out = [0.0] * _n(0.22)
    for _ in range(26):                                  # tiny crackles as tape grabs paper
        at = int(rnd.uniform(0, 0.16) ** 0.8 * RATE)
        for j in range(rnd.randint(3, 14)):
            if at + j < len(out):
                out[at + j] += rnd.uniform(-1, 1) * rnd.uniform(0.3, 1.0) * math.exp(-j / 4)
    mix(out, decay(tone(170, _n(0.06), RATE, "sine", 110), RATE, 60), _n(0.16), 0.5)
    return _st(filt(out, "hp", 900, RATE))


def typewriter(bell: bool = False, seed: int = 113) -> Stereo:
    out = _tick(2600, 4.0, 230, 0.03, seed)
    mix(out, decay(tone(190, _n(0.06), RATE, "sine", 120), RATE, 55), 0, 0.9)
    mix(out, _tick(1200, 2.0, 120, 0.05, seed + 1), _n(0.03), 0.6)
    if bell:
        for f, a in ((2640, 1.0), (5300, 0.35)):
            mix(out, decay(tone(f, _n(0.9), RATE), RATE, 5.5, 0.0005), _n(0.09), 0.5 * a)
    return _st(out)


def pluck_accent(freq: float = 392, seed: int = 114) -> Stereo:
    return widen(decay(pluck(freq, 0.7, RATE, seed, 0.994, 0.6), RATE, 3.5, 0.0005), RATE, 5)


def wood_block(seed: int = 115) -> Stereo:
    out = decay(tone(980, _n(0.09), RATE), RATE, 75, 0.0004)
    mix(out, decay(tone(1470, _n(0.06), RATE), RATE, 110, 0.0004), 0, 0.5)
    return _st(out)


def bell_tiny(freq: float = 2093, seed: int = 0) -> Stereo:
    out: list[float] = []
    for r, a, d in ((1.0, 1.0, 7), (2.76, 0.4, 13), (5.4, 0.15, 22)):
        mix(out, decay(tone(freq * r, _n(0.6), RATE), RATE, d, 0.0005), 0, a)
    return widen(out, RATE, 4)


def shutter_soft(seed: int = 116) -> Stereo:
    out = _tick(2100, 3.0, 210, 0.03, seed)
    mix(out, _tick(1300, 2.0, 150, 0.05, seed + 1), _n(0.06), 0.9)
    mix(out, _rough(0.05, 1500, 6000, 200, seed + 2, 0.5), _n(0.02), 0.3)
    return _st(out)


R = Callable[..., Stereo]
RECIPES: dict[str, tuple[R, dict, list[str], str]] = {
    "click-soft": (click_soft, {}, ["click", "soft", "text", "ui", "tactile"], "A word or label appearing"),
    "click-mechanical": (click_mech, {}, ["click", "mechanical", "button", "tactile", "cut"], "A hard cut or a button press"),
    "click-switch": (switch, {}, ["click", "switch", "toggle", "tactile", "cut"], "Scene change with a snap instead of a whoosh"),
    "tap-wood": (tap_wood, {}, ["tap", "wood", "knock", "tactile", "text"], "A caption line landing"),
    "tap-wood-high": (tap_wood, {"freq": 620, "seed": 124}, ["tap", "wood", "high", "tactile", "text"], "Alternate with tap-wood"),
    "tap-glass": (tap_glass, {}, ["tap", "glass", "tink", "highlight", "tactile"], "A highlight, a number, a clean accent"),
    "stamp-thunk": (stamp, {}, ["stamp", "thunk", "date", "paper", "tactile"], "Date and place stamps hitting paper"),
    "paper-slide": (paper_slide, {}, ["paper", "slide", "photo", "document", "tactile"], "A photo or document sliding in"),
    "page-turn": (page_turn, {}, ["paper", "page", "turn", "book", "chapter"], "New chapter or section"),
    "pen-scribble": (pen_scribble, {}, ["pen", "scribble", "write", "underline", "note"], "Handwritten notes, underlines, circles"),
    "marker-stroke": (marker_stroke, {}, ["marker", "highlighter", "stroke", "highlight"], "A highlighter sweeping over words"),
    "pencil-tick": (pencil_tick, {}, ["pencil", "tick", "mark", "check", "tactile"], "Small marks, ticks, list items"),
    "tape-stick": (tape_stick, {}, ["tape", "stick", "collage", "photo", "tactile"], "A taped photo being stuck down"),
    "typewriter-key": (typewriter, {}, ["typewriter", "key", "text", "clack", "retro"], "Typed text, one clack per word"),
    "typewriter-bell": (typewriter, {"bell": True}, ["typewriter", "bell", "line", "retro"], "End of a typed line or a title"),
    "pluck-accent": (pluck_accent, {}, ["pluck", "string", "accent", "musical", "pin"], "Map pins, list items (musical, warm)"),
    "pluck-accent-high": (pluck_accent, {"freq": 587, "seed": 125}, ["pluck", "string", "accent", "musical", "high"], "Alternate with pluck-accent"),
    "wood-block": (wood_block, {}, ["wood block", "tick", "percussion", "accent"], "Rhythmic accents on beats or steps"),
    "bell-tiny": (bell_tiny, {}, ["bell", "tiny", "ting", "reveal", "accent"], "A small reveal or the final line"),
    "shutter-soft": (shutter_soft, {}, ["shutter", "camera", "photo", "soft"], "A picture appearing, softer than camera-shutter"),
}
