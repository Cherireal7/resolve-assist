"""Step sequencer for the richer music presets (stdlib only).

A preset describes one bar as step patterns ('x' = hit, 'X' = accent, '.' = rest) for drums, bass,
an arpeggio and a seeded lead melody over a chord per bar. Voices are rendered once per distinct
note and mixed at their step positions, so a 30 s track takes a few seconds.
"""

from __future__ import annotations

import math
import random

from .dsp import TWO_PI, decay, filt, midi_freq, mix, noise, pluck, reverb, tone

RATE = 44100


def _n(seconds: float) -> int:
    return int(seconds * RATE)


# ------------------------------------------------------------------ drum kit (rendered once)

def _kit(style: str, seed: int) -> dict[str, list[float]]:
    big = style == "big"
    soft = style == "soft"
    kick = decay(tone(120 if big else 150, _n(0.9 if big else 0.42), RATE, "sine", 38 if big else 46),
                 RATE, 4.5 if big else (13 if soft else 10), 0.001)
    if big:
        mix(kick, decay(filt(noise(_n(0.2), seed), "lp", 900, RATE), RATE, 22), 0, 0.5)
    snare = decay(filt(noise(_n(0.26), seed + 1), "bp", 1900, RATE, 0.8), RATE, 22 if soft else 16, 0.0005)
    mix(snare, decay(tone(205, _n(0.12), RATE, "sine", 165), RATE, 28), 0, 0.6)
    clap: list[float] = []
    for k, at in enumerate((0.0, 0.011, 0.023)):
        mix(clap, decay(filt(noise(_n(0.02), seed + 2 + k), "bp", 1500, RATE, 1.2), RATE, 140, 0.0003), _n(at), 0.8)
    mix(clap, decay(filt(noise(_n(0.2), seed + 6), "bp", 1300, RATE, 0.9), RATE, 24), _n(0.03))
    hat = decay(filt(noise(_n(0.07), seed + 7), "hp", 7500, RATE), RATE, 85, 0.0003)
    ohat = decay(filt(noise(_n(0.4), seed + 8), "hp", 7000, RATE), RATE, 11, 0.0003)
    shaker_raw = filt(noise(_n(0.09), seed + 9), "bp", 5200, RATE, 1.0)
    shaker = [x * math.sin(math.pi * i / len(shaker_raw)) ** 2 for i, x in enumerate(shaker_raw)]
    rim = decay(tone(830, _n(0.05), RATE), RATE, 80, 0.0003)
    tom = decay(tone(170, _n(0.45), RATE, "sine", 85), RATE, 8, 0.001)
    slap = decay(filt(noise(_n(0.09), seed + 10), "bp", 900, RATE, 2.0), RATE, 45, 0.0004)
    mix(slap, decay(tone(330, _n(0.08), RATE, "sine", 250), RATE, 40), 0, 0.6)
    return {"kick": kick, "snare": snare, "clap": clap, "hat": hat, "ohat": ohat, "shaker": shaker,
            "rim": rim, "tom": tom, "slap": slap}


DRUM_MIX = {  # gain, pan
    "kick": (0.95, 0.0), "snare": (0.5, 0.0), "clap": (0.45, 0.05), "hat": (0.22, 0.3), "ohat": (0.2, 0.3),
    "shaker": (0.2, -0.35), "rim": (0.35, -0.2), "tom": (0.6, 0.2), "slap": (0.45, -0.15),
}


# ------------------------------------------------------------------ pitched voices

def _voice(kind: str, note: float, seconds: float, seed: int) -> list[float]:
    f = midi_freq(note)
    n = _n(seconds)
    if kind == "pluck":                       # guitar / harp / krar-like string
        return pluck(f, seconds, RATE, seed, 0.9965, 0.55)
    if kind in ("keys", "bell"):              # 2-operator FM: electric piano or bell
        ratio, index, d = (1.0, 1.6, 4.0) if kind == "keys" else (3.5, 2.2, 3.0)
        out = []
        for i in range(n):
            t = i / RATE
            mod = math.sin(TWO_PI * f * ratio * t) * index * math.exp(-t * 6)
            out.append(math.sin(TWO_PI * f * t + mod) * math.exp(-t * d) * min(1.0, i / 90))
        return out
    if kind == "square":
        return decay(filt(tone(f, n, RATE, "square"), "lp", min(6000.0, f * 5), RATE), RATE, 7, 0.003)
    if kind == "sub":
        raw = [a + 0.2 * b for a, b in zip(tone(f, n, RATE), tone(f * 2, n, RATE))]
        return [x * min(1.0, i / 200) * min(1.0, (n - i) / 900) * math.exp(-i / RATE * 2.5) for i, x in enumerate(raw)]
    if kind == "808":
        raw = tone(f * 1.6, n, RATE, "sine", f) if n < 3000 else \
            tone(f * 1.6, 3000, RATE, "sine", f) + tone(f, n - 3000, RATE)
        return [math.tanh(1.8 * x * math.exp(-i / RATE * 2.2)) * min(1.0, i / 60) * min(1.0, (n - i) / 900)
                for i, x in enumerate(raw)]
    # "saw": two detuned saws through a closing low-pass (synth bass / stab)
    raw = [a + b for a, b in zip(tone(f, n, RATE, "saw"), tone(f * 1.007, n, RATE, "saw"))]
    body = filt(raw, "lp", min(5000.0, f * 6), RATE, 1.3)
    return [x * 0.5 * min(1.0, i / 120) * min(1.0, (n - i) / 900) * math.exp(-i / RATE * 3.0) for i, x in enumerate(body)]


def _pad(kind: str, chord: list[int], seconds: float, bright: float) -> tuple[list[float], list[float]]:
    """One bar of sustained chord with soft edges; left and right are detuned for width."""
    n = _n(seconds * 1.12)                     # overlap into the next bar
    att, rel = _n(0.35 if kind != "strings" else 0.6), _n(seconds * 0.24)
    chans = []
    for det in (1.0, 1.004):
        buf = [0.0] * n
        for k, note in enumerate(chord):
            f = midi_freq(note) * det
            if kind == "strings":
                raw = [a + b for a, b in zip(tone(f, n, RATE, "saw"), tone(f * 0.994, n, RATE, "saw"))]
                mix(buf, filt(raw, "lp", 1400 + 2200 * bright, RATE), 0, 0.3)
            else:
                for h, a in ((1, 1.0), (2, 0.5 * bright), (3, 0.25 * bright)):
                    mix(buf, tone(f * h, n, RATE), 0, a * (0.9 if (k + int(det > 1)) % 2 else 1.0))
        chans.append([x * min(1.0, i / att) * min(1.0, (n - i) / rel) for i, x in enumerate(buf)])
    return chans[0], chans[1]


# ------------------------------------------------------------------ melody

def _scale_notes(root: int, scale: list[int], lo: int, hi: int) -> list[int]:
    return [n for n in range(lo, hi + 1) if (n - root) % 12 in scale]


def _melody(lead: dict, chords: list[list[int]], bars: int, rnd: random.Random) -> list[tuple[int, int, int]]:
    """(bar, step, midi note): a two-bar contour repeated over the chords, varied every 4th bar."""
    notes = _scale_notes(lead["root"], lead["scale"], lead.get("low", 60), lead.get("high", 84))
    rhythm = lead["rhythm"]
    steps = [i for i, c in enumerate(rhythm) if c in "xX"]
    contour = []
    pos = 0
    for _ in range(len(steps) * 2):
        pos = max(-3, min(5, pos + rnd.choice((-2, -1, -1, 1, 1, 2, 0))))
        contour.append(pos)
    out = []
    for bar in range(bars):
        chord_pcs = {n % 12 for n in chords[bar % len(chords)]}
        anchor = min(range(len(notes)), key=lambda i: (notes[i] % 12 not in chord_pcs, abs(notes[i] - lead.get("center", 72))))
        phrase = contour[(bar % 2) * len(steps):(bar % 2 + 1) * len(steps)]
        if bar % 4 == 3:
            phrase = phrase[::-1]
        for step, deg in zip(steps, phrase):
            idx = max(0, min(len(notes) - 1, anchor + deg))
            out.append((bar, step, notes[idx]))
    return out


# ------------------------------------------------------------------ render

def render(cfg: dict, seconds: float, seed: int = 3) -> tuple[list[float], list[float]]:
    rnd = random.Random(seed)
    seq = cfg["seq"]
    steps = cfg.get("steps", 16)
    beat = 60.0 / cfg["bpm"]
    bar_s = beat * 4
    step_s = bar_s / steps
    swing = cfg.get("swing", 0.0) * step_s
    chords = cfg["chords"]
    bars = int(math.ceil(seconds / bar_s))
    n = _n(seconds)
    intro = seq.get("intro", 2) if seconds >= 12 else 0
    L, R = [0.0] * n, [0.0] * n
    wet: list[float] = [0.0] * n               # reverb send
    cache: dict = {}

    def at(bar: int, step: int) -> int:
        return _n(bar * bar_s + step * step_s + (swing if step % 2 else 0.0))

    def put(sig: list[float], pos: int, g: float, p: float = 0.0, send: float = 0.0) -> None:
        if pos >= n:
            return
        sig = sig[:n - pos]
        mix(L, sig, pos, g * math.sqrt((1 - p) / 2) * 1.414)
        mix(R, sig, pos, g * math.sqrt((1 + p) / 2) * 1.414)
        if send:
            mix(wet, sig, pos, g * send)

    def note(kind: str, midi: float, dur: float) -> list[float]:
        key = (kind, midi, round(dur, 3))
        if key not in cache:
            cache[key] = _voice(kind, midi, dur, seed + int(midi))
        return cache[key]

    kit = _kit(seq.get("kit", "normal"), seed)
    duck = [1.0] * n                            # side-chain: pads and bass dip on every kick
    depth = seq.get("sidechain", 0.0)
    for bar in range(bars):
        chord = chords[bar % len(chords)]
        drums_on = bar >= intro
        fill = drums_on and bar % 4 == 3 and seq.get("fill")
        for name, pattern in seq.get("drums", {}).items():
            if not drums_on and name not in ("shaker", "hat"):
                continue
            g0, p = DRUM_MIX[name]
            for step, c in enumerate(pattern):
                if c == ".":
                    continue
                pos = at(bar, step)
                put(kit[name], pos, g0 * (1.0 if c == "X" else 0.72) * (0.6 if not drums_on else 1.0), p,
                    0.25 if name in ("snare", "clap", "rim", "slap") else 0.0)
                if name == "kick" and depth:
                    for i in range(pos, min(n, pos + _n(0.22))):
                        duck[i] = min(duck[i], 1.0 - depth * math.exp(-(i - pos) / RATE * 14))
        if fill:
            for k, step in enumerate(range(steps - steps // 4, steps)):
                put(kit[seq["fill"]], at(bar, step), 0.3 + 0.12 * k, 0.3 - 0.2 * k)

        if "bass" in seq and (bar >= intro // 2):
            pattern, kind = seq["bass"]
            hits = [i for i, c in enumerate(pattern) if c != "."]
            for j, step in enumerate(hits):
                c = pattern[step]
                nxt = hits[j + 1] if j + 1 < len(hits) else steps
                dur = min((nxt - step) * step_s * (1.0 if kind in ("808", "sub") else 0.9), bar_s)
                midi = chord[0] - 12 + {"o": 12, "5": 7}.get(c, 0)
                while midi > 50:
                    midi -= 12
                put(note(kind, midi, dur), at(bar, step), seq.get("bass_gain", 0.5))

        if "arp" in seq:
            a = seq["arp"]
            order = a.get("order", [0, 1, 2, 3])
            k = 0
            for step, c in enumerate(a["pattern"]):
                if c == ".":
                    continue
                midi = chord[order[k % len(order)] % len(chord)] + a.get("octave", 12)
                put(note(a["voice"], midi, a.get("length", 0.6)), at(bar, step),
                    a.get("gain", 0.2) * (1.0 if c == "X" else 0.8), 0.45 if k % 2 else -0.45, a.get("send", 0.3))
                k += 1

    if "pad" in seq:
        kind, pgain = seq["pad"]
        pads: dict = {}
        for bar in range(bars):
            chord = chords[bar % len(chords)]
            key = tuple(chord)
            if key not in pads:
                pads[key] = _pad(kind, chord, bar_s, cfg.get("brightness", 0.3))
            pl, pr = pads[key]
            pos = _n(bar * bar_s)
            if pos < n:
                mix(L, pl[:n - pos], pos, pgain)
                mix(R, pr[:n - pos], pos, pgain)

    if "lead" in seq:
        lead = seq["lead"]
        start_bar = intro + (2 if seconds >= 20 else 0)
        for k, (bar, step, midi) in enumerate(_melody(lead, chords, bars, rnd)):
            if bar < start_bar:
                continue
            put(note(lead["voice"], midi, lead.get("length", 0.9)), at(bar, step), lead.get("gain", 0.3),
                0.15 if k % 2 else -0.15, lead.get("send", 0.35))

    if depth:                                   # duck everything a little; drums re-added on top would
        L = [x * (0.6 + 0.4 * d) for x, d in zip(L, duck)]   # be costlier, and a light global dip
        R = [x * (0.6 + 0.4 * d) for x, d in zip(R, duck)]   # still gives the pumping feel
    if seq.get("vinyl"):
        crk = random.Random(seed + 77)
        for _ in range(int(seconds * 9)):
            pos = crk.randrange(max(1, n - 40))
            amp = seq["vinyl"] * crk.uniform(0.3, 1.0)
            for j in range(crk.randint(2, 20)):
                v = crk.uniform(-1, 1) * amp * math.exp(-j / 5)
                L[pos + j] += v
                R[pos + j] += v * 0.7
    rv = seq.get("reverb", 0.25)
    if rv:
        tail = reverb(wet, RATE, 1.4, 1.0, 1.1)[:n]
        d = _n(0.013)
        for i in range(n):
            L[i] += tail[i] * rv
            R[i] += tail[i - d] * rv if i >= d else 0.0
    return L, R
