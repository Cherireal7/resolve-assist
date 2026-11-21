"""More synthesized sound effects: interface sounds, sparkles and comedy cues (stdlib only)."""

from __future__ import annotations

import math
import random
from typing import Callable

from ..dsp import TWO_PI, Stereo, decay, filt, mix, noise, pan, pluck, reverb, tone, widen
from .sfx import RATE, _n

PENTA = (0, 2, 4, 7, 9)


def _st(mono: list[float]) -> Stereo:
    return mono, list(mono)


def _bell(freq: float, seconds: float, bright: float = 1.0, rate_d: float = 5.0) -> list[float]:
    """Struck-bar tone: fundamental plus quickly dying inharmonic partials."""
    out = []
    for i in range(_n(seconds)):
        t = i / RATE
        v = math.sin(TWO_PI * freq * t) * math.exp(-t * rate_d)
        v += 0.35 * bright * math.sin(TWO_PI * freq * 3.98 * t) * math.exp(-t * rate_d * 3)
        v += 0.15 * bright * math.sin(TWO_PI * freq * 9.1 * t) * math.exp(-t * rate_d * 6)
        out.append(v * min(1.0, i / 48))
    return out


def _notes(freqs: list[float], gap: float, length: float, bright: float = 1.0, rate_d: float = 5.0) -> list[float]:
    out: list[float] = []
    for k, f in enumerate(freqs):
        mix(out, _bell(f, length, bright, rate_d), _n(k * gap))
    return out


def _hz(semitones: float, base: float = 523.25) -> float:
    return base * 2 ** (semitones / 12)


def notification(seed: int = 0) -> Stereo:
    return widen(_notes([_hz(7), _hz(12)], 0.13, 0.8), RATE, 6)


def success(seed: int = 0) -> Stereo:
    return widen(_notes([_hz(12), _hz(16), _hz(19), _hz(24)], 0.075, 0.9, 0.7), RATE, 6)


def error(seed: int = 0) -> Stereo:
    out: list[float] = []
    for k in range(2):
        buzz = filt(tone(175, _n(0.13), RATE, "square"), "lp", 1400, RATE)
        mix(out, decay(buzz, RATE, 6, 0.004), _n(k * 0.19))
    return _st(out)


def blip(f0: float = 620, f1: float = 930, seconds: float = 0.09, seed: int = 0) -> Stereo:
    return _st(decay(tone(f0, _n(seconds), RATE, "sine", f1), RATE, 22, 0.003))


def tick(freq: float = 2600, seed: int = 0) -> Stereo:
    body = filt(noise(_n(0.04), seed + 3), "bp", freq, RATE, 6.0)
    return _st(decay(body, RATE, 160, 0.0005))


def clock(seconds: float = 5.0, seed: int = 0) -> Stereo:
    out = [0.0] * _n(seconds)
    k = 0
    while k * 0.5 < seconds - 0.1:
        mix(out, tick(2700 if k % 2 == 0 else 1900)[0], _n(k * 0.5), 1.0 if k % 2 == 0 else 0.8)
        k += 1
    return _st(out[:_n(seconds)])


def countdown(seed: int = 0) -> Stereo:
    out: list[float] = []
    for k in range(3):
        mix(out, decay(tone(880, _n(0.14), RATE), RATE, 5, 0.004), _n(k * 1.0))
    mix(out, decay(tone(1320, _n(0.7), RATE), RATE, 3, 0.004), _n(3.0))
    return _st(out)


def coin(seed: int = 0) -> Stereo:
    out: list[float] = []
    for f, a, d in ((2093, 1.0, 9), (3340, 0.6, 12), (5270, 0.35, 16), (7900, 0.2, 22)):
        mix(out, decay(tone(f, _n(0.7), RATE), RATE, d, 0.001), 0, a)
        mix(out, decay(tone(f * 1.19, _n(0.5), RATE), RATE, d * 1.4, 0.001), _n(0.055), a * 0.7)
    return widen(out, RATE, 5)


def cash_register(seed: int = 0) -> Stereo:
    out: list[float] = []
    rnd = random.Random(seed + 5)
    for k in range(4):                               # drawer mechanism
        mix(out, decay(filt(noise(_n(0.03), rnd.randrange(999)), "bp", 1500 + 500 * k, RATE, 2.0), RATE, 120), _n(0.035 * k), 0.5)
    mix(out, _bell(2350, 1.1, 1.2, 4.0), _n(0.16))
    mix(out, _bell(3136, 0.9, 1.0, 5.0), _n(0.19), 0.6)
    return widen(out, RATE, 7)


def level_up(seed: int = 0) -> Stereo:
    out: list[float] = []
    for k in range(8):
        f = _hz(PENTA[k % 5] + 12 * (k // 5))
        mix(out, decay(filt(tone(f, _n(0.16), RATE, "square"), "lp", 3500, RATE), RATE, 14, 0.002), _n(k * 0.055), 0.6)
    mix(out, _bell(_hz(24), 0.9, 0.8), _n(8 * 0.055))
    return widen(out, RATE, 6)


def message(sent: bool = True, seed: int = 0) -> Stereo:
    if sent:
        return _st(decay(tone(480, _n(0.2), RATE, "sine", 1150), RATE, 9, 0.01))
    out = decay(tone(980, _n(0.1), RATE, "sine", 760), RATE, 25)
    mix(out, decay(tone(760, _n(0.14), RATE, "sine", 600), RATE, 20), _n(0.1))
    return _st(out)


def like(seed: int = 0) -> Stereo:
    out = decay(tone(420, _n(0.16), RATE, "sine", 1050), RATE, 18, 0.002)
    mix(out, _bell(2637, 0.5, 0.6, 9), _n(0.07), 0.35)
    return widen(out, RATE, 5)


def key(heavy: bool = False, seed: int = 0) -> Stereo:
    lo = decay(filt(noise(_n(0.05), seed + 1), "lp", 900 if heavy else 1400, RATE), RATE, 90)
    hi = decay(filt(noise(_n(0.02), seed + 2), "hp", 3500, RATE), RATE, 260)
    out = mix(lo, hi, 0, 0.6)
    if heavy:
        mix(out, decay(tone(140, _n(0.08), RATE, "sine", 90), RATE, 40), 0, 0.8)
    return _st(out)


def mouse_click(seed: int = 0) -> Stereo:
    out = list(tick(3200, seed)[0])
    mix(out, tick(2400, seed + 1)[0], _n(0.07), 0.7)
    return _st(out)


def beeps(freq: float = 2600, count: int = 2, seconds: float = 0.07, seed: int = 0) -> Stereo:
    out: list[float] = []
    for k in range(count):
        mix(out, decay(tone(freq, _n(seconds), RATE), RATE, 4, 0.003), _n(k * (seconds + 0.06)))
    return _st([x * 0.8 for x in out])


def bubble_pops(seconds: float = 1.0, seed: int = 4) -> Stereo:
    rnd = random.Random(seed)
    left: list[float] = [0.0] * _n(seconds)
    right = list(left)
    t = 0.0
    while t < seconds - 0.15:
        f = rnd.uniform(350, 900)
        p = decay(tone(f, _n(0.12), RATE, "sine", f * rnd.uniform(1.8, 3.0)), RATE, 40, 0.001)
        l, r = pan(p, rnd.uniform(-0.7, 0.7))
        mix(left, l, _n(t))
        mix(right, r, _n(t))
        t += rnd.uniform(0.07, 0.2)
    return left, right


# ---------------------------------------------------------------- sparkle

def shimmer(seconds: float = 1.6, seed: int = 12) -> Stereo:
    rnd = random.Random(seed)
    left: list[float] = [0.0] * _n(seconds)
    right = list(left)
    for _ in range(int(seconds * 28)):
        f = rnd.uniform(3000, 9000)
        ping = decay(tone(f, _n(0.25), RATE), RATE, rnd.uniform(14, 30), 0.001)
        l, r = pan(ping, rnd.uniform(-0.9, 0.9))
        at = _n(rnd.uniform(0, seconds - 0.26) ** 1.0)
        g = rnd.uniform(0.2, 0.7) * (1 - at / _n(seconds)) ** 0.5
        mix(left, l, at, g)
        mix(right, r, at, g)
    return left[:_n(seconds)], right[:_n(seconds)]


def magic_chime(seed: int = 0) -> Stereo:
    freqs = [_hz(PENTA[k % 5] + 12 * (k // 5), 1046.5) for k in range(12)]
    dry = _notes(freqs, 0.065, 0.9, 0.8, 6)
    wet = reverb(dry, RATE, 1.6, 0.35)
    sl, sr = shimmer(1.2, seed + 3)
    l, r = widen(wet, RATE, 9)
    return mix(l, sl, _n(0.5), 0.35), mix(r, sr, _n(0.5), 0.35)


def harp_gliss(seed: int = 0) -> Stereo:
    major = (0, 2, 4, 5, 7, 9, 11)
    out: list[float] = []
    for k in range(15):
        f = _hz(major[k % 7] + 12 * (k // 7), 261.63)
        mix(out, pluck(f, 1.6, RATE, seed + k, 0.997, 0.5), _n(k * 0.06), 0.7)
    return widen(reverb(out, RATE, 1.5, 0.3), RATE, 9)


def twinkle(seed: int = 0) -> Stereo:
    return widen(reverb(_notes([_hz(28), _hz(31), _hz(36)], 0.11, 0.7, 0.6, 8), RATE, 1.0, 0.3), RATE, 7)


def wind_chimes(seconds: float = 4.0, seed: int = 8) -> Stereo:
    rnd = random.Random(seed)
    left: list[float] = [0.0] * _n(seconds)
    right = list(left)
    t = 0.0
    while t < seconds - 1.2:
        b = _bell(_hz(rnd.choice(PENTA) + rnd.choice((12, 24)), 1046.5), 1.2, 0.9, 3.5)
        l, r = pan(b, rnd.uniform(-0.8, 0.8))
        g = rnd.uniform(0.3, 0.8)
        mix(left, l, _n(t), g)
        mix(right, r, _n(t), g)
        t += rnd.uniform(0.08, 0.5)
    return left[:_n(seconds)], right[:_n(seconds)]


# ---------------------------------------------------------------- comedy / reactions

def boing(seed: int = 0) -> Stereo:
    out = []
    phase = 0.0
    for i in range(_n(0.9)):
        t = i / RATE
        f = 150 + 260 * math.exp(-t * 3.5) * (0.5 + 0.5 * math.sin(TWO_PI * 13 * t))
        phase += TWO_PI * f / RATE
        out.append((math.sin(phase) + 0.3 * math.sin(2 * phase)) * math.exp(-t * 3.5) * min(1.0, i / 60))
    return _st(out)


def slide_whistle(up: bool = True, seed: int = 0) -> Stereo:
    a, b = (420, 1700) if up else (1700, 420)
    body = tone(a, _n(0.65), RATE, "sine", b, vibrato=(7.0, 0.012))
    air = filt(noise(_n(0.65), seed + 2), "bp", 2500, RATE, 1.2)
    out = [(x + 0.08 * y) for x, y in zip(body, air)]
    return _st([x * min(1.0, i / 800) * min(1.0, (len(out) - i) / 2400) for i, x in enumerate(out)])


def fail_trombone(seed: int = 0) -> Stereo:
    out: list[float] = []
    at = 0.0
    for k, (semi, dur) in enumerate(((-2, 0.38), (-3, 0.38), (-4, 0.38), (-5, 1.1))):
        f = _hz(semi, 233.08)
        last = k == 3
        raw = tone(f, _n(dur), RATE, "saw", f * 0.84 if last else None, vibrato=(5.5, 0.02 if last else 0.006))
        body = filt(raw, "lp", 1100, RATE, 1.2)
        n = len(body)
        mix(out, [x * min(1.0, i / 1400) * min(1.0, (n - i) / (9000 if last else 2400)) for i, x in enumerate(body)], _n(at))
        at += dur
    return _st(out)


def tada(seed: int = 0) -> Stereo:
    out: list[float] = []

    def brass(semi: float, dur: float) -> list[float]:
        f = _hz(semi, 261.63)
        raw = [a + b for a, b in zip(tone(f, _n(dur), RATE, "saw"), tone(f * 1.006, _n(dur), RATE, "saw"))]
        body = filt(raw, "lp", 2400, RATE, 0.9)
        n = len(body)
        return [x * min(1.0, i / 700) * min(1.0, (n - i) / 5000) for i, x in enumerate(body)]

    for semi in (0, 4, 7):
        mix(out, brass(semi, 0.16), 0, 0.3)
    for semi in (0, 4, 7, 12, 16):
        mix(out, brass(semi, 1.3), _n(0.22), 0.25)
    return widen(reverb(out, RATE, 1.0, 0.2), RATE, 8)


def cork_pop(seed: int = 0) -> Stereo:
    out = decay(tone(1100, _n(0.12), RATE, "sine", 260), RATE, 45, 0.0005)
    mix(out, decay(noise(_n(0.02), seed + 1), RATE, 300), 0, 0.5)
    return _st(out)


def jingle(win: bool = True, seed: int = 0) -> Stereo:
    semis = (0, 4, 7, 12) if win else (7, 3, 0, -5)
    out = _notes([_hz(s) for s in semis], 0.12, 0.6, 0.7, 6)
    chord = (0, 4, 7, 12) if win else (-5, 0, 3)
    for s in chord:
        mix(out, _bell(_hz(s), 1.4, 0.5, 3.0), _n(0.5), 0.5)
    return widen(reverb(out, RATE, 1.2, 0.25), RATE, 8)


R = Callable[..., Stereo]
RECIPES: dict[str, tuple[R, dict, list[str], str]] = {
    "ui-notification": (notification, {}, ["ui", "notification", "alert", "message"], "A notification appears on screen"),
    "ui-success": (success, {}, ["ui", "success", "done", "complete", "positive"], "Order placed, task done, payment ok"),
    "ui-error": (error, {}, ["ui", "error", "wrong", "negative", "buzz"], "Something failed or is the wrong way"),
    "ui-toggle-on": (blip, {}, ["ui", "toggle", "switch", "on", "blip"], "Switches, selections, small confirmations"),
    "ui-toggle-off": (blip, {"f0": 930, "f1": 620}, ["ui", "toggle", "switch", "off", "blip"], "Deselect, switch off"),
    "ui-tick": (tick, {}, ["ui", "tick", "counter", "list"], "List items or numbers appearing one by one"),
    "ui-tock": (tick, {"freq": 1700}, ["ui", "tock", "counter"], "Alternate with ui-tick"),
    "ui-mouse-click": (mouse_click, {}, ["ui", "mouse", "click", "screen recording"], "Clicks in screen recordings"),
    "ui-key-press": (key, {}, ["ui", "key", "keyboard", "typing", "single"], "One key per letter in typed text"),
    "ui-key-return": (key, {"heavy": True}, ["ui", "key", "keyboard", "enter", "return"], "End of a typed line"),
    "ui-message-sent": (message, {}, ["ui", "message", "chat", "sent", "whoop"], "Chat bubble sent"),
    "ui-message-received": (message, {"sent": False}, ["ui", "message", "chat", "received"], "Chat bubble received"),
    "ui-like-pop": (like, {}, ["ui", "like", "heart", "pop", "social"], "Like/heart animations, stickers"),
    "ui-coin": (coin, {}, ["ui", "coin", "money", "reward", "price"], "Prices, savings, rewards"),
    "ui-cash-register": (cash_register, {}, ["ui", "cash", "register", "money", "sale", "ka-ching"], "Sale made, offer reveal"),
    "ui-level-up": (level_up, {}, ["ui", "level up", "achievement", "game", "upgrade"], "Milestones, upgrades, before/after"),
    "ui-countdown-3-2-1": (countdown, {}, ["ui", "countdown", "beep", "timer", "start"], "3-2-1 countdown (one beep per second)"),
    "ui-focus-beep": (beeps, {}, ["camera", "focus", "beep", "photo"], "Camera focus lock before a shutter"),
    "ui-rec-beep": (beeps, {"freq": 1000, "count": 1, "seconds": 0.22}, ["camera", "record", "beep", "rec"], "Recording starts"),
    "clock-ticking-5s": (clock, {}, ["clock", "ticking", "time", "waiting", "loop"], "Time passing, deadlines; loops cleanly"),
    "bubble-pops": (bubble_pops, {}, ["pop", "bubbles", "cute", "stickers", "many"], "Several items popping in at once"),
    "sparkle-shimmer": (shimmer, {}, ["sparkle", "shimmer", "shine", "glitter", "beauty"], "Shine sweeps, clean/new, beauty shots"),
    "sparkle-magic-chime": (magic_chime, {}, ["sparkle", "magic", "chime", "reveal", "transformation"], "Before → after reveals"),
    "sparkle-twinkle": (twinkle, {}, ["sparkle", "twinkle", "star", "cute"], "A small highlight or star"),
    "harp-gliss": (harp_gliss, {}, ["harp", "glissando", "dream", "reveal", "flashback"], "Dreamy reveal, flashback"),
    "wind-chimes-4s": (wind_chimes, {}, ["chimes", "calm", "ambience", "spa"], "Calm, spa and wellness moments"),
    "fun-boing": (boing, {}, ["fun", "boing", "spring", "cartoon", "bounce"], "Bounces, silly moments"),
    "fun-slide-whistle-up": (slide_whistle, {}, ["fun", "slide whistle", "up", "cartoon", "rise"], "Something going up"),
    "fun-slide-whistle-down": (slide_whistle, {"up": False}, ["fun", "slide whistle", "down", "cartoon", "fall"], "Something falling"),
    "fun-fail-trombone": (fail_trombone, {}, ["fun", "fail", "trombone", "sad", "joke"], "A joke that fails"),
    "fun-tada": (tada, {}, ["fun", "tada", "fanfare", "reveal", "celebrate"], "Proud reveal"),
    "fun-cork-pop": (cork_pop, {}, ["fun", "cork", "pop", "bottle", "celebrate"], "Openings, launches"),
    "jingle-win": (jingle, {}, ["jingle", "win", "positive", "logo", "end card"], "Short positive sting for an end card"),
    "jingle-lose": (jingle, {"win": False}, ["jingle", "lose", "negative", "sad"], "Short negative sting"),
}
