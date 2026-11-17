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


def _freq(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def generate(preset: str, seconds: float, path: Path, seed: int = 3, volume: float = 0.5) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}'. Available: {', '.join(PRESETS)}")
    if not 1.0 <= seconds <= 600.0:
        raise ValueError("seconds must be 1..600")
    cfg = PRESETS[preset]
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
