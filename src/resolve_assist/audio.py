"""Royalty-free preset music, synthesized locally (stdlib only).

Generated tracks contain no third-party material, so they are safe to use in
published videos. Presets are simple but pleasant: chord pads, a soft bass and
an optional light beat, with fades so they can be trimmed to any length.
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RATE = 44100

# MIDI note numbers per chord.
PRESETS: dict[str, dict] = {
    "calm-lofi": {"bpm": 84, "chords": [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]],
                  "beat": True, "brightness": 0.35, "description": "Warm, relaxed lo-fi pads with a soft beat"},
    "bright-pop": {"bpm": 112, "chords": [[60, 64, 67, 72], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]],
                   "beat": True, "brightness": 0.6, "description": "Upbeat, cheerful pop chords for promos"},
    "house-groove": {"bpm": 124, "chords": [[57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 65], [52, 55, 59, 64]],
                     "beat": True, "four": True, "brightness": 0.5, "description": "Four-on-the-floor house groove, energetic"},
    "cinematic-pulse": {"bpm": 70, "chords": [[45, 52, 57, 60], [41, 48, 53, 57], [43, 50, 55, 58], [40, 47, 52, 55]],
                        "beat": True, "four": True, "brightness": 0.15, "description": "Dark, slow cinematic pulse for trailers/reveals"},
    "ambient": {"bpm": 60, "chords": [[48, 55, 60, 64], [45, 52, 57, 60], [41, 48, 53, 57], [43, 50, 55, 59]],
                "beat": False, "brightness": 0.2, "description": "Slow, airy pads without drums"},
}

# Sequenced presets (see sequencer.py): one bar of step patterns over a chord per bar.
# 'x' = hit, 'X' = accent, '.' = rest; bass also takes 'o' (octave up) and '5' (fifth).
_FOUR = "x...x...x...x..."
_BACK = "....x.......x..."
_EIGHTHS = "x.x.x.x.x.x.x.x."
_OFF = "..x...x...x...x."
MAJ_PENTA, MIN_PENTA = [0, 2, 4, 7, 9], [0, 3, 5, 7, 10]
TIZITA_MINOR, AMBASSEL = [0, 2, 3, 7, 8], [0, 1, 5, 7, 8]      # Ethiopian qenet (pentatonic modes)

PRESETS.update({
    "uplift-corporate": {
        "bpm": 120, "brightness": 0.5, "description": "Bright, optimistic plucks for product and brand videos",
        "chords": [[60, 64, 67, 72], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]],
        "seq": {"drums": {"kick": _FOUR, "clap": _BACK, "hat": _OFF}, "fill": "tom", "bass": ("x.......x.x.....", "sub"),
                "pad": ("warm", 0.035), "arp": {"pattern": _EIGHTHS, "voice": "pluck", "order": [0, 2, 1, 3]},
                "lead": {"voice": "keys", "scale": MAJ_PENTA, "root": 60, "rhythm": "x...x.x...x.x...", "gain": 0.22},
                "sidechain": 0.3}},
    "fast-cut-energy": {
        "bpm": 128, "brightness": 0.6, "description": "Driving dance energy for sizzle reels and fast cuts",
        "chords": [[52, 55, 59, 64], [48, 55, 60, 64], [55, 59, 62, 67], [50, 57, 62, 66]],
        "seq": {"drums": {"kick": _FOUR, "clap": _BACK, "ohat": _OFF, "hat": "xxxxxxxxxxxxxxxx"}, "fill": "snare",
                "bass": (_OFF, "saw"), "bass_gain": 0.45, "pad": ("strings", 0.05),
                "arp": {"pattern": "xxxxxxxxxxxxxxxx", "voice": "square", "order": [0, 1, 2, 3, 2, 1], "gain": 0.1, "length": 0.25},
                "lead": {"voice": "square", "scale": MIN_PENTA, "root": 64, "rhythm": "x..x..x...x.x...", "gain": 0.16},
                "sidechain": 0.6, "intro": 2}},
    "chill-house": {
        "bpm": 118, "brightness": 0.35, "description": "Smooth, warm house for lifestyle, fashion and beauty",
        "chords": [[53, 57, 60, 64], [57, 60, 64, 67], [50, 53, 57, 60], [48, 52, 55, 59]],
        "seq": {"kit": "soft", "drums": {"kick": _FOUR, "clap": _BACK, "ohat": _OFF, "shaker": "x.xxx.xxx.xxx.xx"},
                "bass": (_OFF, "sub"), "pad": ("warm", 0.04),
                "arp": {"pattern": "..x..x....x..x..", "voice": "keys", "order": [3, 2, 1, 2], "gain": 0.22, "length": 0.8},
                "sidechain": 0.5}},
    "lofi-keys": {
        "bpm": 78, "swing": 0.18, "brightness": 0.3, "description": "Dusty lo-fi electric piano with vinyl crackle, for vlogs and study clips",
        "chords": [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]],
        "seq": {"kit": "soft", "drums": {"kick": "x.....x...x.....", "snare": _BACK, "hat": _EIGHTHS},
                "bass": ("x.........x.....", "sub"), "pad": ("warm", 0.03),
                "arp": {"pattern": "x..x..x...x.x...", "voice": "keys", "order": [0, 2, 3, 1], "gain": 0.26, "length": 1.1},
                "vinyl": 0.03, "reverb": 0.3}},
    "trap-bounce": {
        "bpm": 140, "brightness": 0.2, "description": "Half-time trap with a deep 808, for streetwear, sport and bold hooks",
        "chords": [[48, 55, 60, 63], [44, 51, 56, 60], [46, 53, 58, 62], [43, 50, 55, 58]],
        "seq": {"drums": {"kick": "x.....x...x.....", "snare": "........x.......", "hat": "x.x.x.x.x.xxx.x.", "ohat": "..............x."},
                "bass": ("x.....x...x.....", "808"), "bass_gain": 0.55, "pad": ("warm", 0.02),
                "lead": {"voice": "bell", "scale": MIN_PENTA, "root": 60, "rhythm": "x..x..x.....x...", "gain": 0.2}}},
    "synthwave-drive": {
        "bpm": 100, "brightness": 0.5, "description": "80s synthwave: pulsing bass, arpeggio and big snare, for tech and night shots",
        "chords": [[57, 60, 64, 69], [53, 57, 60, 65], [48, 55, 60, 64], [55, 59, 62, 67]],
        "seq": {"drums": {"kick": _FOUR, "snare": _BACK, "hat": _EIGHTHS}, "fill": "tom",
                "bass": (_EIGHTHS, "saw"), "bass_gain": 0.42, "pad": ("strings", 0.05),
                "arp": {"pattern": "xxxxxxxxxxxxxxxx", "voice": "square", "order": [0, 1, 2, 3, 2, 1], "gain": 0.11, "length": 0.3},
                "lead": {"voice": "saw", "scale": [0, 2, 3, 5, 7, 8, 10], "root": 57, "rhythm": "x.....x.x.......", "gain": 0.2, "length": 1.2},
                "sidechain": 0.3, "reverb": 0.35}},
    "afro-groove": {
        "bpm": 108, "brightness": 0.4, "description": "Syncopated afro-pop groove with plucked melody, sunny and danceable",
        "chords": [[53, 57, 60, 65], [48, 55, 60, 64], [50, 57, 62, 65], [46, 53, 58, 62]],
        "seq": {"drums": {"kick": "x..x..x...x..x..", "rim": "..x..x....x..x..", "shaker": "x.xxx.xxx.xxx.xx", "clap": _BACK},
                "bass": ("x..x....x.x..o..", "pluck"), "bass_gain": 0.6, "pad": ("warm", 0.025),
                "arp": {"pattern": _OFF, "voice": "keys", "order": [1, 2, 3, 2], "gain": 0.18},
                "lead": {"voice": "pluck", "scale": MAJ_PENTA, "root": 65, "rhythm": "x.x..x.x..x.x...", "gain": 0.34}}},
    "dembow-heat": {
        "bpm": 96, "brightness": 0.35, "description": "Latin dembow rhythm with a minor melody, for food, dance and nightlife",
        "chords": [[57, 60, 64, 69], [55, 59, 62, 67], [53, 57, 60, 65], [52, 56, 59, 64]],
        "seq": {"drums": {"kick": _FOUR, "snare": "...x..x....x..x.", "shaker": "xxxxxxxxxxxxxxxx"},
                "bass": ("x.....x.x.....x.", "808"), "pad": ("warm", 0.025),
                "lead": {"voice": "pluck", "scale": [0, 2, 3, 5, 7, 8, 11], "root": 57, "rhythm": "x..x..x...x.x...", "gain": 0.32}}},
    "funk-pop": {
        "bpm": 110, "brightness": 0.5, "description": "Bouncy funk bass and key stabs, playful and upbeat",
        "chords": [[50, 53, 57, 60], [55, 59, 62, 65], [48, 52, 55, 59], [45, 52, 55, 60]],
        "seq": {"drums": {"kick": "x..x....x.x.....", "snare": _BACK, "hat": "x.xxx.xxx.xxx.xx", "clap": _BACK}, "fill": "snare",
                "bass": ("x..x..o.x...x.5.", "pluck"), "bass_gain": 0.65,
                "arp": {"pattern": "..x..x....x..x..", "voice": "keys", "order": [3, 2, 3, 1], "gain": 0.24, "length": 0.4}}},
    "acoustic-warm": {
        "bpm": 92, "brightness": 0.3, "description": "Finger-picked strings with a light shaker, honest and personal",
        "chords": [[55, 59, 62, 67], [50, 57, 62, 66], [52, 55, 59, 64], [48, 55, 60, 64]],
        "seq": {"kit": "soft", "drums": {"kick": "x.........x.....", "shaker": _OFF, "rim": _BACK},
                "bass": ("x.......x.......", "pluck"), "bass_gain": 0.55,
                "arp": {"pattern": _EIGHTHS, "voice": "pluck", "order": [0, 2, 1, 3, 2, 3, 1, 2], "octave": 0, "gain": 0.34, "length": 1.4},
                "lead": {"voice": "pluck", "scale": MAJ_PENTA, "root": 67, "rhythm": "x.....x...x.....", "gain": 0.3, "length": 1.4},
                "reverb": 0.3}},
    "piano-emotional": {
        "bpm": 72, "brightness": 0.2, "description": "Slow keys and strings without drums, for origin stories and testimonials",
        "chords": [[57, 60, 64, 69], [53, 57, 60, 65], [48, 55, 60, 64], [55, 59, 62, 67]],
        "seq": {"bass": ("x...............", "sub"), "pad": ("strings", 0.045),
                "arp": {"pattern": _EIGHTHS, "voice": "keys", "order": [0, 1, 2, 3, 2, 1, 2, 3], "octave": 0, "gain": 0.3, "length": 1.6},
                "lead": {"voice": "bell", "scale": MIN_PENTA, "root": 69, "rhythm": "x.......x.....x.", "gain": 0.13, "length": 1.6},
                "reverb": 0.4, "intro": 0}},
    "explainer-pulse": {
        "bpm": 116, "brightness": 0.3, "description": "Light, neutral pulse that stays out of the way of a voiceover",
        "chords": [[60, 64, 67, 72], [57, 60, 64, 69], [53, 57, 60, 65], [55, 59, 62, 67]],
        "seq": {"kit": "soft", "drums": {"kick": "x.......x.......", "rim": _BACK, "hat": _EIGHTHS},
                "bass": ("x.x.....x.x.....", "sub"), "pad": ("warm", 0.03),
                "arp": {"pattern": _EIGHTHS, "voice": "pluck", "order": [0, 1, 2, 1], "gain": 0.2, "length": 0.35}}},
    "trailer-epic": {
        "bpm": 90, "brightness": 0.3, "description": "Big drums, low strings and a driving ostinato, for launches and reveals",
        "chords": [[38, 45, 50, 53], [34, 41, 46, 50], [41, 48, 53, 57], [36, 43, 48, 52]],
        "seq": {"kit": "big", "drums": {"kick": "X.....x...x.x...", "snare": "........X.......", "tom": "..............xx"},
                "bass": (_EIGHTHS, "saw"), "bass_gain": 0.4, "pad": ("strings", 0.07),
                "arp": {"pattern": "x.xx.xx.x.xx.xx.", "voice": "saw", "order": [0, 1, 2, 1], "octave": 12, "gain": 0.16, "length": 0.22},
                "reverb": 0.4}},
    "deep-focus": {
        "bpm": 60, "brightness": 0.15, "description": "Still, spacious pads with sparse bell notes, for calm explainers and timelapses",
        "chords": [[48, 55, 60, 64], [45, 52, 57, 60], [41, 48, 53, 57], [43, 50, 55, 59]],
        "seq": {"bass": ("x...............", "sub"), "bass_gain": 0.35, "pad": ("warm", 0.06),
                "lead": {"voice": "bell", "scale": MAJ_PENTA, "root": 72, "rhythm": "x.....x.....x...", "gain": 0.14, "length": 2.0},
                "reverb": 0.5, "intro": 0}},
    "ethio-tizita": {
        "bpm": 100, "steps": 12, "brightness": 0.3,
        "description": "Ethiopian-inspired: tizita minor scale on a plucked krar-like string over a 6/8 chikchika-style groove",
        "chords": [[48, 55, 60, 63], [44, 51, 56, 60], [48, 55, 60, 63], [43, 50, 55, 62]],
        "seq": {"drums": {"kick": "x.....x..x..", "slap": "...x.....x..", "shaker": "x.xx.xx.xx.x"}, "fill": "tom",
                "bass": ("x.....x..5..", "pluck"), "bass_gain": 0.6, "pad": ("warm", 0.025),
                "lead": {"voice": "pluck", "scale": TIZITA_MINOR, "root": 60, "rhythm": "x.xx.x..x.x.", "gain": 0.4, "length": 1.0},
                "reverb": 0.3}},
    "ethio-ambassel": {
        "bpm": 84, "steps": 12, "brightness": 0.2,
        "description": "Ethiopian-inspired: slow, reflective ambassel scale melody on plucked strings with soft hand drums",
        "chords": [[48, 55, 60, 67], [41, 53, 56, 60], [49, 56, 61, 65], [48, 55, 60, 65]],
        "seq": {"kit": "soft", "drums": {"kick": "x.....x.....", "shaker": "x..x..x..x..", "slap": ".........x.."},
                "bass": ("x.....x.....", "pluck"), "bass_gain": 0.5, "pad": ("strings", 0.04),
                "lead": {"voice": "pluck", "scale": AMBASSEL, "root": 60, "rhythm": "x..x.x..x...", "gain": 0.42, "length": 1.4},
                "reverb": 0.4}},
    "ethio-bati-jazz": {
        "bpm": 112, "brightness": 0.35,
        "description": "Ethio-jazz inspired: bati minor melody on vibes-like keys over a syncopated groove",
        "chords": [[45, 52, 57, 60], [48, 55, 60, 64], [50, 57, 62, 67], [52, 55, 59, 64]],
        "seq": {"drums": {"kick": "x..x..x...x.x...", "snare": _BACK, "hat": _EIGHTHS, "rim": "..x......x......"},
                "bass": ("x..x..o...x.5...", "saw"), "bass_gain": 0.4, "pad": ("warm", 0.025),
                "arp": {"pattern": "..x...x..x....x.", "voice": "keys", "order": [1, 3, 2, 3], "gain": 0.2},
                "lead": {"voice": "bell", "scale": MIN_PENTA, "root": 57, "rhythm": "x..x.x....x.x...", "gain": 0.2, "length": 1.0},
                "swing": 0.0, "reverb": 0.3}},
})


def _freq(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def generate(preset: str, seconds: float, path: Path, seed: int = 3, volume: float = 0.5) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}'. Available: {', '.join(PRESETS)}")
    if not 1.0 <= seconds <= 600.0:
        raise ValueError("seconds must be 1..600")
    cfg = PRESETS[preset]
    if "seq" in cfg:
        from .sequencer import render
        left, right = render(cfg, seconds, seed)
        fi, fo = int(min(0.05, seconds / 6) * RATE), int(min(1.5, seconds / 4) * RATE)
        m = len(left)
        for i in range(m):
            g = min(1.0, i / fi if fi else 1.0, (m - i) / fo if fo else 1.0)
            left[i] *= g
            right[i] *= g
        return _write(path, left, right, preset, seconds, cfg, volume)
    rnd = random.Random(seed)
    n = int(seconds * RATE)
    beat_s = 60.0 / cfg["bpm"]
    bar_s = beat_s * 4
    chords = cfg["chords"]
    bright = cfg["brightness"]
    fade_in, fade_out = min(0.6, seconds / 6), min(1.5, seconds / 4)
    two_pi = 2 * math.pi
    left = [0.0] * n
    right = [0.0] * n

    for i in range(n):
        t = i / RATE
        bar = int(t / bar_s)
        chord = chords[bar % len(chords)]
        tb = t - bar * bar_s
        # Pad: chord tones, slight detune for width, soft attack each bar.
        env = min(1.0, tb / 0.35)
        pad_l = pad_r = 0.0
        for k, note in enumerate(chord):
            f = _freq(note)
            s = math.sin(two_pi * f * t) + bright * 0.5 * math.sin(two_pi * 2 * f * t)
            pad_l += s * (1.0 if k % 2 else 0.8)
            pad_r += math.sin(two_pi * f * 1.003 * t) * (0.8 if k % 2 else 1.0) + bright * 0.5 * math.sin(two_pi * 2 * f * t)
        pad_l *= 0.07 * env
        pad_r *= 0.07 * env
        # Bass: root an octave down, pulsing on beats.
        tbeat = t % beat_s
        bass = math.sin(two_pi * _freq(chord[0] - 12) * t) * 0.18 * math.exp(-tbeat * 2.5)
        drums = 0.0
        if cfg["beat"]:
            beat_idx = int(t / beat_s) % 4
            kick = cfg.get("four") or beat_idx in (0, 2)
            if kick:                # kick: falling sine (every beat for four-on-the-floor)
                drums += math.sin(two_pi * (50 + 90 * math.exp(-tbeat * 30)) * tbeat) * math.exp(-tbeat * 9) * 0.35
            if beat_idx in (1, 3):  # soft snare/clap: noise burst
                drums += (rnd.random() * 2 - 1) * math.exp(-tbeat * 18) * 0.10
            th = t % (beat_s / 2)   # hi-hat on eighths
            drums += (rnd.random() * 2 - 1) * math.exp(-th * 60) * 0.035
        g = 1.0
        if t < fade_in:
            g = t / fade_in
        elif t > seconds - fade_out:
            g = max(0.0, (seconds - t) / fade_out)
        left[i] = (pad_l + bass + drums) * g
        right[i] = (pad_r + bass + drums) * g

    return _write(path, left, right, preset, seconds, cfg, volume)


def _write(path: Path, left: list, right: list, preset: str, seconds: float, cfg: dict, volume: float) -> dict:
    peak = max(max(map(abs, left)), max(map(abs, right))) or 1.0
    scale = volume * 0.9 / peak
    frames = bytearray()
    for a, b in zip(left, right):
        frames += struct.pack("<hh", int(a * scale * 32767), int(b * scale * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return {"path": str(path), "preset": preset, "seconds": round(seconds, 3),
            "description": cfg["description"], "license": "generated locally by resolve-assist: free to use"}
