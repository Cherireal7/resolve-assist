"""More synthesized sound effects: transitions, impacts, drums, tension and ambience (stdlib only)."""

from __future__ import annotations

import math
import random
from typing import Callable

from ..dsp import TWO_PI, Stereo, decay, fade, filt, mix, noise, pan, reverb, soft_clip, sweep, tone, widen
from .sfx import RATE, _n, impact, riser


def _st(mono: list[float]) -> Stereo:
    return mono, list(mono)


def _swell(sig: list[float], peak_at: float, up: float = 2.0, down: float = 1.5) -> list[float]:
    n = len(sig)
    return [x * ((i / n / peak_at) ** up if i / n < peak_at else ((1 - i / n) / (1 - peak_at)) ** down)
            for i, x in enumerate(sig)]


# ---------------------------------------------------------------- transitions

def whip(seconds: float = 0.28, seed: int = 31) -> Stereo:
    body = _swell(sweep(noise(_n(seconds), seed), "bp", 900, 9000, RATE, 1.4), 0.45)
    n = len(body)
    return [x * math.sqrt(1 - i / n) for i, x in enumerate(body)], [x * math.sqrt(i / n) for i, x in enumerate(body)]


def air(seconds: float = 1.3, seed: int = 32) -> Stereo:
    body = _swell(filt(sweep(noise(_n(seconds), seed), "bp", 1500, 7000, RATE, 0.8), "hp", 1200, RATE), 0.6)
    return widen(body, RATE, 14)


def pass_by(seconds: float = 1.3, seed: int = 33) -> Stereo:
    n = _n(seconds)
    rush = sweep(noise(n, seed), "bp", 2600, 700, RATE, 1.0)
    hum = tone(190, n, RATE, "saw", 120)
    body = _swell([a + 0.25 * b for a, b in zip(rush, filt(hum, "lp", 900, RATE))], 0.5, 2.5, 2.0)
    return ([x * math.sqrt(max(0.0, 1 - i / n)) for i, x in enumerate(body)],
            [x * math.sqrt(i / n) for i, x in enumerate(body)])


def tape_stop(seconds: float = 0.9, seed: int = 0) -> Stereo:
    out = []
    phase = 0.0
    n = _n(seconds)
    for i in range(n):
        speed = (1 - i / n) ** 1.6                      # the tape slows to a halt
        phase += speed / RATE
        v = sum(math.sin(TWO_PI * f * phase) for f in (220, 277.2, 329.6, 440)) * 0.25
        out.append(v * min(1.0, i / 200) * min(1.0, (n - i) / 3000))
    return _st(out)


def rewind(seconds: float = 0.9, seed: int = 0) -> Stereo:
    out = []
    phase = 0.0
    n = _n(seconds)
    for i in range(n):
        t = i / RATE
        f = 900 * (3.2 ** (i / n)) * (1 + 0.25 * math.sin(TWO_PI * 34 * t))
        phase += TWO_PI * f / RATE
        out.append(math.sin(phase) * (0.6 + 0.4 * math.sin(TWO_PI * 17 * t)))
    return _st(fade(out, RATE, 0.02, 0.05))


def power(up: bool = False, seconds: float = 1.0, seed: int = 0) -> Stereo:
    a, b = (45, 420) if up else (420, 38)
    raw = tone(a, _n(seconds), RATE, "saw", b)
    body = sweep(raw, "lp", 300 if up else 3000, 3000 if up else 180, RATE, 1.5)
    return _st(fade(body, RATE, 0.01, 0.12))


def zap(seed: int = 0) -> Stereo:
    body = decay(tone(3200, _n(0.22), RATE, "saw", 180), RATE, 14, 0.001)
    return _st(filt(body, "lp", 6000, RATE))


def stutter(seed: int = 41) -> Stereo:
    out: list[float] = []
    for k in range(8):
        burst = [a * 0.5 + b for a, b in zip(noise(_n(0.03), seed + k), tone(330, _n(0.03), RATE, "square"))]
        mix(out, fade(filt(burst, "lp", 4000, RATE), RATE, 0.001, 0.004), _n(k * 0.055), 1.0 - k * 0.08)
    return _st(out)


def scratch(seed: int = 42) -> Stereo:
    n = _n(0.38)
    src = noise(n, seed)
    f = [0.0] * n
    from ..dsp import Biquad
    bq = Biquad("bp", 800, RATE, 3.0)
    for i in range(n):
        if i % 16 == 0:
            u = i / n
            bq.set(500 + 2600 * abs(math.sin(TWO_PI * 2.6 * u)) * (1 - 0.4 * u), 3.0)
        f[i] = bq(src[i]) * (0.4 + abs(math.sin(TWO_PI * 2.6 * i / n)))
    return _st(fade(f, RATE, 0.004, 0.03))


def cymbal(reverse: bool = False, seconds: float = 2.2, seed: int = 43) -> Stereo:
    raw = filt(noise(_n(seconds), seed), "hp", 5500, RATE)
    metal = [x * (1 + 0.5 * math.sin(TWO_PI * 3400 * i / RATE)) for i, x in enumerate(raw)]
    body = decay(metal, RATE, 2.2, 0.002)
    if reverse:
        body = fade(body[::-1], RATE, 0.0, 0.01)
    return widen(body, RATE, 9)


# ---------------------------------------------------------------- impacts

def braam(seconds: float = 3.4, seed: int = 0) -> Stereo:
    n = _n(seconds)
    raw = [0.0] * n
    for f, a in ((55.0, 1.0), (55.4, 0.9), (82.4, 0.6), (110.3, 0.5), (27.5, 0.7)):
        mix(raw, tone(f, n, RATE, "saw"), 0, a)
    body = sweep(raw, "lp", 2600, 260, RATE, 1.1)
    env = [x * min(1.0, i / 900) * math.exp(-i / RATE * 1.1) for i, x in enumerate(body)]
    return widen(reverb(soft_clip(env, 2.2), RATE, 1.8, 0.3, 1.4), RATE, 12)


def slam(seed: int = 51) -> Stereo:
    out = decay(tone(120, _n(0.5), RATE, "sine", 42), RATE, 9, 0.001)
    mix(out, decay(filt(noise(_n(0.12), seed), "lp", 5000, RATE), RATE, 45, 0.0005), 0, 0.7)
    return _st(soft_clip(out, 1.8))


def thud(seed: int = 52) -> Stereo:
    out = decay(tone(85, _n(0.4), RATE, "sine", 40), RATE, 11, 0.004)
    mix(out, decay(filt(noise(_n(0.08), seed), "lp", 500, RATE), RATE, 40), 0, 0.5)
    return _st(out)


def boom_tail(seed: int = 6) -> Stereo:
    return widen(reverb(impact(2.2, seed)[0], RATE, 2.6, 0.4, 1.6), RATE, 13)


def cinematic_hit(seed: int = 0) -> Stereo:
    out = list(impact(1.8, 6)[0])
    mix(out, slam(seed)[0], 0, 0.8)
    mix(out, decay(filt(noise(_n(0.5), 53), "hp", 4000, RATE), RATE, 9, 0.0005), 0, 0.25)
    return widen(reverb(soft_clip(out, 1.6), RATE, 2.2, 0.32, 1.3), RATE, 11)


# ---------------------------------------------------------------- drum one-shots

def kick(seed: int = 0) -> Stereo:
    return _st(decay(tone(165, _n(0.4), RATE, "sine", 46), RATE, 10, 0.0008))


def snare(seed: int = 61) -> Stereo:
    out = decay(filt(noise(_n(0.25), seed), "bp", 2100, RATE, 0.8), RATE, 17, 0.0005)
    mix(out, decay(tone(210, _n(0.12), RATE, "sine", 170), RATE, 28), 0, 0.7)
    return _st(out)


def clap(seed: int = 62) -> Stereo:
    out: list[float] = []
    for k, at in enumerate((0.0, 0.011, 0.023)):
        mix(out, decay(filt(noise(_n(0.02), seed + k), "bp", 1500, RATE, 1.2), RATE, 140, 0.0003), _n(at), 0.8)
    mix(out, decay(filt(noise(_n(0.22), seed + 9), "bp", 1300, RATE, 0.9), RATE, 22, 0.0005), _n(0.03))
    return widen(out, RATE, 4)


def hat(open_: bool = False, seed: int = 63) -> Stereo:
    return _st(decay(filt(noise(_n(0.5 if open_ else 0.08), seed), "hp", 7500, RATE), RATE, 9 if open_ else 75, 0.0003))


def rim(seed: int = 0) -> Stereo:
    out = decay(tone(820, _n(0.06), RATE), RATE, 70, 0.0003)
    mix(out, decay(tone(1740, _n(0.04), RATE, "square"), RATE, 110, 0.0003), 0, 0.3)
    return _st(out)


def snap(seed: int = 64) -> Stereo:
    out = decay(filt(noise(_n(0.05), seed), "bp", 2700, RATE, 2.5), RATE, 95, 0.0003)
    mix(out, decay(filt(noise(_n(0.02), seed + 1), "bp", 1800, RATE, 2.0), RATE, 200), _n(0.018), 0.5)
    return _st(out)


def drum_roll(seed: int = 65) -> Stereo:
    out: list[float] = []
    t, gap, k = 0.0, 0.085, 0
    while t < 1.5:
        mix(out, snare(seed + k)[0], _n(t), 0.25 + 0.5 * (t / 1.5))
        gap = max(0.028, gap * 0.94)
        t += gap
        k += 1
    l, r = _st(out)
    cl, cr = cymbal(False, 2.4, seed + 100)
    kd = kick()[0]
    return mix(mix(l, cl, _n(1.55), 0.9), kd, _n(1.55)), mix(mix(r, cr, _n(1.55), 0.9), kd, _n(1.55))


# ---------------------------------------------------------------- tension

def riser_tonal(seconds: float = 4.0, seed: int = 0) -> Stereo:
    n = _n(seconds)
    out = [0.0] * n
    for k in range(5):                                   # stacked octaves, each fading through
        f0 = 55.0 * 2 ** k
        layer = tone(f0, n, RATE, "sine", f0 * 4)
        mix(out, [x * math.sin(math.pi * min(1.0, (k + 2 * i / n) / 6)) for i, x in enumerate(layer)])
    return widen([x * (i / n) ** 1.5 for i, x in enumerate(out)], RATE, 10)


def downer(seconds: float = 2.6, seed: int = 71) -> Stereo:
    n = _n(seconds)
    body = [a + 0.5 * b for a, b in zip(tone(700, n, RATE, "sine", 45), sweep(noise(n, seed), "lp", 6000, 150, RATE))]
    return widen([x * (1 - i / n) ** 1.2 * min(1.0, i / 300) for i, x in enumerate(body)], RATE, 10)


def drone(seconds: float = 8.0, seed: int = 0) -> Stereo:
    n = _n(seconds)
    raw = [0.0] * n
    for f in (49.0, 49.4, 73.6, 98.3):
        mix(raw, tone(f, n, RATE, "saw"), 0, 0.3)
    body = filt(raw, "lp", 420, RATE, 1.2)
    lfo = [x * (0.75 + 0.25 * math.sin(TWO_PI * 0.23 * i / RATE)) for i, x in enumerate(body)]
    return widen(fade(lfo, RATE, 1.2, 1.5), RATE, 15)


def heartbeat(seconds: float = 4.0, bpm: float = 60.0, seed: int = 0) -> Stereo:
    out = [0.0] * _n(seconds)
    t = 0.1
    while t < seconds - 0.5:
        mix(out, decay(tone(70, _n(0.22), RATE, "sine", 42), RATE, 16, 0.004), _n(t))
        mix(out, decay(tone(62, _n(0.2), RATE, "sine", 40), RATE, 20, 0.004), _n(t + 0.27), 0.7)
        t += 60.0 / bpm
    return _st(out[:_n(seconds)])


def pulse(seconds: float = 6.0, bpm: float = 100.0, seed: int = 0) -> Stereo:
    out = [0.0] * _n(seconds)
    step = 30.0 / bpm
    k = 0
    while k * step < seconds - 0.3:
        note = filt(tone(55, _n(0.26), RATE, "saw"), "lp", 300 + 500 * (k * step / seconds), RATE, 2.0)
        mix(out, decay(note, RATE, 12, 0.003), _n(k * step), 1.0 if k % 4 == 0 else 0.6)
        k += 1
    return _st(fade(out[:_n(seconds)], RATE, 0.3, 0.4))


# ---------------------------------------------------------------- ambience beds (quiet loops)

def crackle(seconds: float = 10.0, seed: int = 81) -> Stereo:
    rnd = random.Random(seed)
    n = _n(seconds)
    left = [x * 0.012 for x in filt(noise(n, seed), "hp", 2500, RATE)]
    right = [x * 0.012 for x in filt(noise(n, seed + 1), "hp", 2500, RATE)]
    for _ in range(int(seconds * 14)):
        at = rnd.randrange(n - 200)
        amp = rnd.uniform(0.15, 1.0) ** 2
        p = rnd.uniform(-0.8, 0.8)
        for j in range(rnd.randint(2, 30)):
            v = rnd.uniform(-1, 1) * amp * math.exp(-j / 6)
            left[at + j] += v * math.sqrt((1 - p) / 2)
            right[at + j] += v * math.sqrt((1 + p) / 2)
    return left, right


def hiss(seconds: float = 10.0, seed: int = 82) -> Stereo:
    return (fade(filt(noise(_n(seconds), seed), "hp", 3000, RATE), RATE, 0.3, 0.3),
            fade(filt(noise(_n(seconds), seed + 1), "hp", 3000, RATE), RATE, 0.3, 0.3))


def wind(seconds: float = 10.0, seed: int = 83) -> Stereo:
    from ..dsp import Biquad
    out = []
    for ch in range(2):
        rnd = random.Random(seed + ch)
        bq = Biquad("bp", 400, RATE, 1.1)
        n = _n(seconds)
        ph = rnd.uniform(0, 6)
        sig = []
        for i in range(n):
            if i % 64 == 0:
                t = i / RATE
                gust = 0.5 + 0.3 * math.sin(0.55 * t + ph) + 0.2 * math.sin(1.37 * t + 2 * ph)
                bq.set(250 + 900 * gust, 1.1)
                level = 0.35 + 0.65 * gust
            sig.append(bq(rnd.uniform(-1, 1)) * level)
        out.append(fade(sig, RATE, 1.0, 1.0))
    return out[0], out[1]


def rain(seconds: float = 10.0, seed: int = 84) -> Stereo:
    rnd = random.Random(seed)
    n = _n(seconds)
    chans = []
    for ch in range(2):
        bed = filt(filt(noise(n, seed + ch), "hp", 1800, RATE), "lp", 9000, RATE)
        chans.append([x * 0.45 for x in bed])
    for _ in range(int(seconds * 45)):
        at = rnd.randrange(n - 400)
        drop = decay(tone(rnd.uniform(1800, 5200), 300, RATE, "sine", rnd.uniform(900, 1800)), RATE, 90, 0.0004)
        l, r = pan(drop, rnd.uniform(-1, 1))
        g = rnd.uniform(0.1, 0.5)
        mix(chans[0], l, at, g)
        mix(chans[1], r, at, g)
    return fade(chans[0][:n], RATE, 0.5, 0.5), fade(chans[1][:n], RATE, 0.5, 0.5)


def room(seconds: float = 10.0, seed: int = 85) -> Stereo:
    return (fade(filt(noise(_n(seconds), seed), "lp", 220, RATE), RATE, 0.5, 0.5),
            fade(filt(noise(_n(seconds), seed + 1), "lp", 220, RATE), RATE, 0.5, 0.5))


R = Callable[..., Stereo]
RECIPES: dict[str, tuple[R, dict, list[str], str]] = {
    "whoosh-whip": (whip, {}, ["whoosh", "whip", "transition", "fast", "pan"], "Whip pans and very fast cuts"),
    "whoosh-airy": (air, {}, ["whoosh", "air", "transition", "soft", "light"], "Soft transitions, text sliding in"),
    "whoosh-pass-by": (pass_by, {}, ["whoosh", "pass by", "doppler", "movement", "vehicle"], "Something rushing past the camera"),
    "swipe-short": (whip, {"seconds": 0.18, "seed": 35}, ["swipe", "ui", "transition", "short"], "Phone swipes, card changes"),
    "tape-stop": (tape_stop, {}, ["tape stop", "slow down", "transition", "retro", "freeze"], "Freeze frame, 'wait, what?' moments"),
    "tape-rewind": (rewind, {}, ["rewind", "tape", "transition", "back", "retro"], "Jumping back in time"),
    "power-down": (power, {}, ["power down", "off", "shutdown", "fail"], "Screens off, things failing"),
    "power-up": (power, {"up": True}, ["power up", "on", "start", "boot"], "Starting up, switching on"),
    "zap-laser": (zap, {}, ["zap", "laser", "electric", "tech"], "Tech accents, highlights jumping in"),
    "glitch-stutter": (stutter, {}, ["glitch", "stutter", "digital", "transition"], "Stutter cuts"),
    "record-scratch": (scratch, {}, ["scratch", "record", "stop", "comedy", "interrupt"], "Interrupting the story"),
    "cymbal-crash": (cymbal, {}, ["cymbal", "crash", "drum", "accent"], "Big accent on a downbeat"),
    "cymbal-reverse": (cymbal, {"reverse": True}, ["cymbal", "reverse", "riser", "build-up"], "Swell into a cut (ends on the cut)"),
    "impact-braam": (braam, {}, ["impact", "braam", "trailer", "cinematic", "brass"], "Trailer-style title hits"),
    "impact-slam": (slam, {}, ["impact", "slam", "hit", "text", "heavy"], "Words slamming onto the screen"),
    "impact-thud": (thud, {}, ["impact", "thud", "soft", "drop", "landing"], "Objects landing, soft accents"),
    "impact-boom-tail": (boom_tail, {}, ["impact", "boom", "reverb", "cinematic", "long"], "Final hit with a long tail"),
    "impact-cinematic-hit": (cinematic_hit, {}, ["impact", "hit", "cinematic", "logo", "reveal"], "Logo and title reveals"),
    "drum-kick": (kick, {}, ["drum", "kick", "beat", "accent"], "Single beat accents"),
    "drum-snare": (snare, {}, ["drum", "snare", "beat", "accent"], "Single beat accents"),
    "drum-clap": (clap, {}, ["drum", "clap", "beat", "accent"], "Claps on cuts"),
    "drum-hat": (hat, {}, ["drum", "hi-hat", "closed", "beat"], "Light rhythmic accents"),
    "drum-hat-open": (hat, {"open_": True}, ["drum", "hi-hat", "open", "beat"], "Open hat accent"),
    "drum-rim": (rim, {}, ["drum", "rim", "click", "beat"], "Dry rhythmic accent"),
    "finger-snap": (snap, {}, ["snap", "finger", "transition", "change"], "Snap transitions (outfit/scene change)"),
    "drum-roll-crash": (drum_roll, {}, ["drum roll", "crash", "reveal", "announcement"], "Announcement: roll, then reveal on the crash"),
    "riser-long-6s": (riser, {"seconds": 6.0, "seed": 25}, ["riser", "build-up", "long", "tension"], "Long build before the main reveal"),
    "riser-tonal": (riser_tonal, {}, ["riser", "tonal", "build-up", "rise"], "Musical build without noise"),
    "downer": (downer, {}, ["downer", "fall", "drop", "end"], "Energy falling away, scene endings"),
    "drone-dark-8s": (drone, {}, ["drone", "dark", "tension", "bed", "problem"], "Bed under a 'problem' section"),
    "heartbeat-4s": (heartbeat, {}, ["heartbeat", "tension", "suspense", "loop"], "Suspense; loops at 60 BPM"),
    "suspense-pulse-6s": (pulse, {}, ["pulse", "suspense", "tension", "bed", "countdown"], "Urgency under a countdown or deadline"),
    "ambience-vinyl-crackle": (crackle, {}, ["ambience", "vinyl", "crackle", "retro", "loop", "texture"], "Loop quietly under retro/lo-fi edits"),
    "ambience-tape-hiss": (hiss, {}, ["ambience", "tape", "hiss", "retro", "loop", "texture"], "Loop quietly under VHS/retro looks"),
    "ambience-wind": (wind, {}, ["ambience", "wind", "outdoor", "loop"], "Outdoor shots without usable sound"),
    "ambience-rain": (rain, {}, ["ambience", "rain", "weather", "calm", "loop"], "Rainy or cosy scenes"),
    "ambience-room-tone": (room, {}, ["ambience", "room tone", "silence", "loop", "fill"], "Fill gaps between voice clips"),
}

# Peak level per asset (default 0.89). Beds stay quiet so they can sit under a mix as they are.
PEAKS = {"ambience-vinyl-crackle": 0.35, "ambience-tape-hiss": 0.12, "ambience-wind": 0.4, "ambience-rain": 0.4,
         "ambience-room-tone": 0.1, "drone-dark-8s": 0.6, "heartbeat-4s": 0.7, "suspense-pulse-6s": 0.6}
