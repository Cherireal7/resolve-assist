"""Beat grid: plan a music-led video on a tempo where one sixteenth note is a whole number of frames.

The music comes first and the edit follows it. A plan is a list of sections (one per act), each a whole
number of beats long, so every cut, word and sound can sit on a frame that is also a hit in the music.

    tempos()   tempos that fit a frame rate
    plan()     sections -> frames, milliseconds, a music plan for a generator, the steps with a hit
    render()   a percussion track for the plan, made locally, exactly on the grid
    measure()  where the hits are in a track made elsewhere, and how far it is off the grid
    check()    a cue sheet against the rules of the edit
    mix()      the music plus one sound per cue, each on its frame, mastered for phones

Stdlib only; mix() and measure() decode through ffmpeg.
"""

from __future__ import annotations

import json
import math
import re
import struct
import subprocess
import wave
from pathlib import Path

from .dsp import decay, fade, filt, mix as dsp_mix, noise, reverb, soft_clip, tone

RATE = 48000
STEPS_PER_BEAT = 4
STEPS_PER_BAR = 16
MAX_WORDS = 4
SAFE_AREA_PX = 190          # top and bottom of a 1920-high frame that the feed covers
TARGET_LUFS = -14.0
TARGET_PEAK_DB = -1.5

KINDS = {
    "intro": ("A dry hand-drum hit on every beat over a dark, steady drone. No sub bass yet.",
              ["melody", "vocals", "sub bass"]),
    "groove": ("Playful syncopated hand percussion with claps and rimshots, energy rising.",
               ["melody", "vocals"]),
    "spin": ("Rolling toms that speed up, one heavy hit, a full stop, then silence.",
             ["melody", "vocals", "reverb tail over the silence"]),
    "drop": ("A huge sub bass hit, then relentless sixteenth-note percussion.",
             ["melody", "vocals", "breaks"]),
    "outro": ("One last heavy hit, a few sparse echoes, a clean ending.",
              ["melody", "vocals", "fade-out loop"]),
    "pulse": ("A dry hit on every beat, nothing else.", ["melody", "vocals"]),
    "silence": ("Silence.", []),
}
CUE_KINDS = ("text", "effect", "cut", "slide", "music-cut")


class GridError(ValueError):
    pass


# ------------------------------------------------------------------ tempo

def tempos(fps: float = 60.0, lo: float = 80.0, hi: float = 160.0) -> list[dict]:
    """Tempos between lo and hi where a sixteenth note is a whole number of frames."""
    out = []
    for frames in range(1, int(15 * fps / lo) + 1):
        bpm = 15.0 * fps / frames
        if lo <= bpm <= hi:
            out.append({"bpm": round(bpm, 3), "sixteenth_frames": frames, "beat_frames": frames * 4,
                        "bar_frames": frames * 16, "bar_seconds": round(frames * 16 / fps, 4)})
    return sorted(out, key=lambda t: t["bpm"])


def step_frames(fps: float, bpm: float) -> int:
    v = 15.0 * fps / bpm
    if abs(v - round(v)) > 1e-6 or round(v) < 1:
        near = sorted(tempos(fps, 40, 240), key=lambda t: abs(t["bpm"] - bpm))[:3]
        raise GridError(f"at {fps:g} fps a sixteenth at {bpm:g} bpm is {v:.3f} frames, not a whole number; "
                        "use " + ", ".join("%g" % t["bpm"] for t in sorted(near, key=lambda t: t["bpm"])) + " bpm")
    return int(round(v))


# ------------------------------------------------------------------ plan

def parse_sections(text: str) -> list[dict]:
    """'intro:4,groove:3,build=spin:3,drop:2,outro:2' -> sections (bars; name=kind when they differ)."""
    out = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        m = re.fullmatch(r"([^:=]+)(?:=([^:]+))?:([0-9.]+)", part)
        if not m:
            raise GridError(f"cannot read section '{part}'; write name:bars, for example drop:2")
        out.append({"name": m.group(1).strip(), "kind": (m.group(2) or m.group(1)).strip().lower(), "bars": float(m.group(3))})
    return out


def plan(fps: float = 60.0, bpm: float = 112.5, sections: list[dict] | None = None, title: str = "",
         key: str = "F minor") -> dict:
    """Lay the sections on the grid. Each section: name, kind (one of KINDS), bars (quarter bars allowed),
    optional music (a description for a music generator), exclude, silence_beats (empty beats at its end;
    one by default before a drop)."""
    sf = step_frames(fps, bpm)
    sections = sections or parse_sections("intro:4,groove:3,spin:3,drop:2,outro:2")
    out, step = [], 0
    for i, s in enumerate(sections):
        kind = str(s.get("kind") or s.get("name") or "pulse").lower()
        if kind not in KINDS:
            kind = "pulse"
        steps = float(s.get("bars", 0)) * STEPS_PER_BAR
        if steps < STEPS_PER_BEAT or abs(steps / STEPS_PER_BEAT - round(steps / STEPS_PER_BEAT)) > 1e-6:
            raise GridError(f"section '{s.get('name', kind)}' must be a whole number of beats (bars in quarters)")
        steps = int(round(steps))
        nxt = str((sections[i + 1].get("kind") or sections[i + 1].get("name") or "")).lower() if i + 1 < len(sections) else ""
        silence = s.get("silence_beats")
        silence = int(silence) if silence is not None else (1 if nxt == "drop" and kind != "silence" else 0)
        if silence * STEPS_PER_BEAT >= steps:
            raise GridError(f"section '{s.get('name', kind)}' is all silence; make it longer or lower silence_beats")
        out.append({"name": str(s.get("name") or kind), "kind": kind, "bars": steps / STEPS_PER_BAR,
                    "start_step": step, "steps": steps, "silence_steps": silence * STEPS_PER_BEAT,
                    "music": str(s.get("music") or KINDS[kind][0]),
                    "exclude": list(s.get("exclude") or KINDS[kind][1])})
        step += steps
    for s in out:
        a, b = s["start_step"] * sf, (s["start_step"] + s["steps"]) * sf
        s.update({"start_frame": a, "frames": b - a, "start_ms": round(a / fps * 1000),
                  "duration_ms": round(b / fps * 1000) - round(a / fps * 1000),
                  "seconds": round((b - a) / fps, 3)})
    p = {"title": title, "fps": fps, "bpm": bpm, "key": key, "sixteenth_frames": sf, "beat_frames": sf * 4,
         "bar_frames": sf * 16, "steps": step, "frames": step * sf, "seconds": round(step * sf / fps, 3),
         "safe_area_px": SAFE_AREA_PX, "max_words": MAX_WORDS, "sections": out}
    p["hits"] = {"source": "local track", "steps": hit_steps(p)}
    p["music_plan"] = music_plan(p)
    return p


def music_plan(p: dict) -> dict:
    """The plan as a music generator takes it: one section per act with its exact length in milliseconds.
    (The field names follow ElevenLabs' composition plan; check them against the tool's own schema.)"""
    tempo = f"{round(p['bpm'])} BPM" if abs(p["bpm"] - round(p["bpm"])) > 1e-6 else f"{p['bpm']:g} BPM"
    return {"positive_global_styles": ["instrumental", "percussion-driven", tempo, p.get("key") or "F minor",
                                       "tight, dry, punchy"],
            "negative_global_styles": ["vocals", "melody-led", "tempo changes", "swing", "long reverb"],
            "sections": [{"section_name": s["name"], "positive_local_styles": [s["music"]],
                          "negative_local_styles": s["exclude"], "duration_ms": s["duration_ms"], "lines": []}
                         for s in p["sections"]],
            "note": f"Exact tempo {p['bpm']:g} BPM; total {sum(s['duration_ms'] for s in p['sections'])} ms."}


def position(p: dict, step: int) -> str:
    """bar.beat.sixteenth, counted from 1."""
    return f"{step // 16 + 1}.{step % 16 // 4 + 1}.{step % 4 + 1}"


def section_at(p: dict, step: int) -> dict | None:
    return next((s for s in p["sections"] if s["start_step"] <= step < s["start_step"] + s["steps"]), None)


def silent_steps(p: dict) -> set[int]:
    out: set[int] = set()
    for s in p["sections"]:
        end = s["start_step"] + s["steps"]
        out.update(range(s["start_step"], end) if s["kind"] == "silence" else range(end - s["silence_steps"], end))
    return out


def table(p: dict) -> str:
    rows = ["| Section | Kind | Bars | Starts | Length | Frames | First step | Music |", "|---|---|---|---|---|---|---|---|"]
    for s in p["sections"]:
        rows.append(f"| {s['name']} | {s['kind']} | {s['bars']:g} | {s['start_ms'] / 1000:.3f} s | {s['duration_ms']} ms | "
                    f"{s['start_frame']}–{s['start_frame'] + s['frames'] - 1} | {s['start_step']} ({position(p, s['start_step'])}) | "
                    f"{s['music']}{' One beat of silence at the end.' if s['silence_steps'] else ''} |")
    head = (f"**{p['bpm']:g} bpm at {p['fps']:g} fps**: a sixteenth is {p['sixteenth_frames']} frames, a beat "
            f"{p['beat_frames']}, a bar {p['bar_frames']}. Total {p['steps']} steps, {p['frames']} frames, {p['seconds']:.3f} s.")
    return head + "\n\n" + "\n".join(rows) + "\n"


def grid_js(p: dict) -> str:
    """A small script for an HTML composition: GRID.t(step) in seconds, GRID.pos('3.1.1'), GRID.section(name)."""
    data = {k: p[k] for k in ("fps", "bpm", "sixteenth_frames", "beat_frames", "bar_frames", "steps", "frames", "seconds")}
    data["sections"] = [{k: s[k] for k in ("name", "kind", "start_step", "steps", "silence_steps")} for s in p["sections"]]
    data["hits"] = p["hits"]["steps"]
    return ("// Written by `resolve-assist grid plan`. Times are whole frames: use them for every tween and cut.\n"
            f"window.GRID = {json.dumps(data)};\n"
            "// A hair before the frame, never after it: a time that rounds up lands one frame late.\n"
            "GRID.t = (step) => Math.max(0, step * GRID.sixteenth_frames / GRID.fps - 1e-6);\n"
            "GRID.pos = (s) => { const [bar, beat = 1, six = 1] = String(s).split('.').map(Number);"
            " return GRID.t((bar - 1) * 16 + (beat - 1) * 4 + (six - 1)); };\n"
            "GRID.section = (name) => { const s = GRID.sections.find((x) => x.name === name);"
            " return { start: GRID.t(s.start_step), end: GRID.t(s.start_step + s.steps), step: (n) => GRID.t(s.start_step + n), steps: s.steps }; };\n")


# ------------------------------------------------------------------ the local track

GROOVE = {"slap": "x..x..x.x..x..x.", "clap": "....x.......x...", "rim": "..x..x....x..x.x", "kick": "x.........x.....",
          "shaker": "x.x.x.x.x.x.x.x."}
DROP = {"kick": "x..x..x.x..x..x.", "snare": "....x.......x...", "rim": "..x...x...x...x.", "hat": "xxxxxxxxxxxxxxxx"}
LEVEL = {"slap": 0.6, "clap": 0.6, "rim": 0.45, "kick": 0.9, "shaker": 0.2, "snare": 0.7, "hat": 0.36, "tom": 0.8,
         "tom_hi": 0.75, "tom_lo": 0.85, "boom": 1.0, "sub": 1.0}
PAN = {"slap": -0.15, "clap": 0.1, "rim": -0.3, "shaker": 0.35, "hat": 0.3, "tom_hi": -0.35, "tom_lo": 0.35}
AUDIBLE = 0.3               # a step counts as a hit when something at least this loud starts on it


def events(p: dict) -> list[tuple[int, str, float]]:
    """(step, instrument, gain) for the local track. The hits of the plan come from this list."""
    ev: list[tuple[int, str, float]] = []
    for s in p["sections"]:
        a, n, kind = s["start_step"], s["steps"], s["kind"]
        live = n - s["silence_steps"]
        if kind in ("intro", "pulse"):
            for k in range(0, live, 4):
                ev.append((a + k, "tom", 1.0 if k % 16 == 0 else 0.8))
                ev.append((a + k, "slap", 0.5))
        elif kind == "groove":
            for k in range(live):
                rise = 0.7 + 0.3 * k / max(1, live - 1)
                for inst, pat in GROOVE.items():
                    if pat[k % 16] == "x":
                        ev.append((a + k, inst, rise * (1.15 if k % 16 == 0 and inst == "kick" else 1.0)))
        elif kind == "spin":
            hit = max(0, live - 4)                       # the heavy hit rings for one beat, then the stop
            for k in range(hit):
                where = k / max(1, hit)
                every = 4 if where < 0.4 else (2 if where < 0.75 else 1)
                if k % every == 0:
                    ev.append((a + k, ("tom", "tom_hi", "tom_lo")[(k // every) % 3], 0.5 + 0.45 * where))
            ev.append((a + hit, "boom", 1.0))
        elif kind == "drop":
            for k in range(live):
                if k % 16 == 0:
                    ev.append((a + k, "sub", 1.0))
                for inst, pat in DROP.items():
                    if pat[k % 16] == "x":
                        ev.append((a + k, inst, 1.3 if inst == "hat" and k % 4 == 0 else 1.0))
        elif kind == "outro":
            ev.append((a, "boom", 1.0))
            ev.append((a, "sub", 0.8))
            for k, g in ((6, 0.75), (12, 0.6), (20, 0.52)):
                if k < live - 4:
                    ev.append((a + k, "slap", g))
    return ev


def hit_steps(p: dict) -> list[int]:
    return sorted({step for step, inst, g in events(p) if g * LEVEL[inst] >= AUDIBLE})


def _n(seconds: float) -> int:
    return int(seconds * RATE)


def _kit(seed: int) -> dict[str, list[float]]:
    kick = decay(tone(150, _n(0.4), RATE, "sine", 46), RATE, 11, 0.001)
    dsp_mix(kick, decay(filt(noise(_n(0.02), seed), "hp", 2500, RATE), RATE, 220, 0.0003), 0, 0.25)
    snare = decay(filt(noise(_n(0.24), seed + 1), "bp", 1900, RATE, 0.8), RATE, 18, 0.0005)
    dsp_mix(snare, decay(tone(205, _n(0.12), RATE, "sine", 165), RATE, 28), 0, 0.6)
    clap: list[float] = []
    for k, at in enumerate((0.0, 0.011, 0.023)):
        dsp_mix(clap, decay(filt(noise(_n(0.02), seed + 2 + k), "bp", 1500, RATE, 1.2), RATE, 140, 0.0003), _n(at), 0.8)
    dsp_mix(clap, decay(filt(noise(_n(0.18), seed + 6), "bp", 1300, RATE, 0.9), RATE, 26), _n(0.03))
    hat = decay(filt(noise(_n(0.06), seed + 7), "hp", 7500, RATE), RATE, 95, 0.0003)
    raw = filt(noise(_n(0.08), seed + 9), "bp", 5200, RATE, 1.0)
    shaker = [x * math.sin(math.pi * i / len(raw)) ** 2 for i, x in enumerate(raw)]
    rim = decay(tone(830, _n(0.05), RATE), RATE, 80, 0.0003)
    dsp_mix(rim, decay(filt(noise(_n(0.01), seed + 11), "bp", 3000, RATE, 2.0), RATE, 300, 0.0002), 0, 0.5)
    slap = decay(filt(noise(_n(0.09), seed + 10), "bp", 900, RATE, 2.0), RATE, 45, 0.0004)
    dsp_mix(slap, decay(tone(330, _n(0.08), RATE, "sine", 250), RATE, 40), 0, 0.6)

    def tom(freq: float) -> list[float]:                 # a dry hand drum: body, skin slap, short
        body = decay(tone(freq, _n(0.3), RATE, "sine", freq * 0.62), RATE, 13, 0.001)
        dsp_mix(body, decay(filt(noise(_n(0.03), seed + int(freq)), "bp", freq * 6, RATE, 1.5), RATE, 150, 0.0003), 0, 0.5)
        return body

    boom = decay(tone(110, _n(0.9), RATE, "sine", 40), RATE, 5.0, 0.001)
    dsp_mix(boom, decay(filt(noise(_n(0.25), seed + 12), "lp", 1400, RATE), RATE, 20, 0.0005), 0, 0.7)
    dsp_mix(boom, decay(tone(220, _n(0.3), RATE, "triangle", 90), RATE, 12, 0.001), 0, 0.4)
    boom = soft_clip(reverb(boom, RATE, tail=0.5, wet=0.2, size=0.8), 2.0)
    # A sub hit that a phone can still hear: the low sine is driven so it grows harmonics.
    sub = decay(tone(87.3, _n(1.6), RATE, "sine", 43.65), RATE, 2.6, 0.002)
    sub = soft_clip(sub, 3.0)
    dsp_mix(sub, decay(tone(174.6, _n(0.5), RATE, "triangle", 87.3), RATE, 7, 0.002), 0, 0.3)
    return {"kick": kick, "snare": snare, "clap": clap, "hat": hat, "shaker": shaker, "rim": rim, "slap": slap,
            "tom": tom(170), "tom_hi": tom(225), "tom_lo": tom(128), "boom": boom, "sub": sub}


def step_sample(p: dict, step: float) -> int:
    return int(round(step * p["sixteenth_frames"] / p["fps"] * RATE))


def render(p: dict, path: Path, seed: int = 7) -> dict:
    """A percussion track for the plan, every hit on its frame, hard silence where the plan says so."""
    total = step_sample(p, p["steps"])
    left, right = [0.0] * total, [0.0] * total
    kit = _kit(seed)
    for step, inst, g in events(p):
        at = step_sample(p, step)
        sound, level, pn = kit[inst], g * LEVEL[inst], PAN.get(inst, 0.0)
        gl, gr = level * math.sqrt((1 - pn) / 2) * 1.414, level * math.sqrt((1 + pn) / 2) * 1.414
        for i in range(min(len(sound), total - at)):
            x = sound[i]
            left[at + i] += x * gl
            right[at + i] += x * gr
    for s in p["sections"]:                               # the drone under an intro: steady, no rhythm of its own
        if s["kind"] != "intro":
            continue
        a, b = step_sample(p, s["start_step"]), step_sample(p, s["start_step"] + s["steps"] - s["silence_steps"])
        n = b - a
        drone = [x + 0.5 * y for x, y in zip(tone(87.31, n, RATE, "saw"), tone(130.81, n, RATE, "saw"))]
        drone = fade(filt(filt(drone, "lp", 420, RATE), "hp", 70, RATE), RATE, 0.4, 0.08)
        for i, x in enumerate(drone):
            left[a + i] += x * 0.10
            right[a + i] += x * 0.10
    cut = int(0.008 * RATE)
    for step in sorted(silent_steps(p)):                  # a full stop: nothing rings through the silence
        a, b = step_sample(p, step), step_sample(p, step + 1)
        first = step - 1 not in silent_steps(p)
        for i in range(a, min(b, total)):
            g = max(0.0, 1.0 - (i - a) / cut) if first else 0.0
            left[i] *= g
            right[i] *= g
    end = int(0.03 * RATE)
    for i in range(end):                                  # no click at the last sample
        g = i / end
        left[total - 1 - i] *= g
        right[total - 1 - i] *= g
    left, right = soft_clip(left, 1.2), soft_clip(right, 1.2)
    write_wav(path, left, right, 0.89)
    return {"path": str(path), "seconds": round(total / RATE, 3), "samples": total, "rate": RATE, "bpm": p["bpm"],
            "license": "generated locally by resolve-assist: free to use"}


def write_wav(path: Path, left: list[float], right: list[float], peak: float | None = 0.89) -> None:
    top = max(max(map(abs, left), default=0.0), max(map(abs, right), default=0.0)) or 1.0
    scale = (peak / top) if peak else 1.0
    frames = bytearray()
    for a, b in zip(left, right):
        frames += struct.pack("<hh", max(-32767, min(32767, int(a * scale * 32767))),
                              max(-32767, min(32767, int(b * scale * 32767))))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


# ------------------------------------------------------------------ cues and the rules of the edit

def resolve_cue(p: dict, cue: dict) -> dict:
    """Where a cue sits: give one of step, pos ('bar.beat.sixteenth'), frame, time, or section + step."""
    sf, fps = p["sixteenth_frames"], p["fps"]
    if "section" in cue and "pos" not in cue and "frame" not in cue and "time" not in cue:
        sec = next((s for s in p["sections"] if s["name"] == cue["section"]), None)
        if sec is None:
            raise GridError(f"no section named '{cue['section']}'")
        frame = (sec["start_step"] + float(cue.get("step", 0))) * sf
    elif "step" in cue:
        frame = float(cue["step"]) * sf
    elif "pos" in cue:
        parts = [float(x) for x in str(cue["pos"]).split(".")] + [1.0, 1.0]
        frame = ((parts[0] - 1) * 16 + (parts[1] - 1) * 4 + (parts[2] - 1)) * sf
    elif "frame" in cue:
        frame = float(cue["frame"])
    elif "time" in cue:
        frame = float(cue["time"]) * fps
    else:
        raise GridError(f"cue has no place (step, pos, frame, time or section): {cue}")
    step = frame / sf
    near = int(round(step))
    on = abs(frame - near * sf) < 1e-6
    sec = section_at(p, int(step))
    return {**cue, "frame": round(frame, 3), "time": round(frame / fps, 4), "step": near if on else round(step, 3),
            "on_grid": on, "pos": position(p, near) if on else "", "section_name": sec["name"] if sec else ""}


def check(p: dict, cues: list[dict]) -> dict:
    """The cue sheet against the rules. Returns the resolved cues and a list of problems, each with a fix."""
    sf = p["sixteenth_frames"]
    hits, silent = set(p["hits"]["steps"]), silent_steps(p)
    out, problems, used = [], [], {}

    def bad(i: int, rule: str, message: str, fix: str) -> None:
        problems.append({"cue": i + 1, "what": str(cues[i].get("what", ""))[:60], "rule": rule, "message": message, "fix": fix})

    def nearest_hit(step: float) -> int | None:
        free = [h for h in hits if h not in silent]
        return min(free, key=lambda h: (abs(h - step), h)) if free else None

    for i, cue in enumerate(cues):
        c = resolve_cue(p, cue)
        out.append(c)
        kind = str(c.get("kind", "effect"))
        if kind not in CUE_KINDS:
            bad(i, "kind", f"unknown kind '{kind}'", f"use one of: {', '.join(CUE_KINDS)}")
        if c["frame"] < 0 or c["frame"] >= p["frames"]:
            bad(i, "range", f"frame {c['frame']:g} is outside the video (0 to {p['frames'] - 1})", "move it inside a section")
            continue
        if not c["on_grid"]:
            near = int(round(c["frame"] / sf))
            bad(i, "on the grid", f"frame {c['frame']:g} is between two sixteenths",
                f"move to frame {near * sf} (step {near}, {position(p, near)})")
            continue
        step = int(c["step"])
        if step in silent:
            bad(i, "silence", f"step {step} ({c['pos']}) is in the beat of silence",
                "nothing happens there: move it to the downbeat after the silence, or before it")
        elif hits and step not in hits:
            h = nearest_hit(step)
            bad(i, "on a hit", f"step {step} ({c['pos']}) is an empty sixteenth: no hit to hear there",
                f"move to step {h} ({position(p, h)}), frame {h * sf}" if h is not None else "add a hit to the music")
        if step in used:
            bad(i, "one at a time", f"shares step {step} ({c['pos']}) with cue {used[step] + 1}",
                "text, then effect, then cut: give each its own hit")
        used.setdefault(step, i)
        words = len(str(c.get("text", "")).split())
        if words > p.get("max_words", MAX_WORDS):
            bad(i, "few words", f"{words} words on screen", f"at most {p.get('max_words', MAX_WORDS)} at a time")
        if kind == "music-cut" and step % 16:
            bar = (step + 8) // 16 * 16
            bad(i, "cut on the one", f"the music is cut mid-bar at {c['pos']}",
                f"cut at the end of a bar and restart on a downbeat: step {bar} ({position(p, bar)})")
    cuts = {int(c["step"]) for c in out if c.get("on_grid") and c.get("kind") in ("cut", "slide")}
    for s in p["sections"]:
        if s["kind"] != "drop":
            continue
        need = set(range(s["start_step"], s["start_step"] + s["steps"])) - silent
        missing = sorted(need - cuts)
        if missing:
            problems.append({"cue": 0, "what": s["name"], "rule": "the drop never holds",
                             "message": f"{len(missing)} of {len(need)} sixteenths in '{s['name']}' have no cut or slide",
                             "fix": "one cut per hit on the drop, starting on its downbeat (steps " +
                                    ", ".join(map(str, missing[:8])) + ("…" if len(missing) > 8 else "") + ")"})
    return {"ok": not problems, "cues": out, "problems": problems,
            "summary": f"{len(out)} cues, {len(problems)} problem{'s' if len(problems) != 1 else ''}"}


def starter_cues(p: dict) -> list[dict]:
    """A cue sheet to start from: one cut at the top of each section and one slide per sixteenth of a drop."""
    cues = []
    for s in p["sections"]:
        if s["kind"] == "silence":
            continue
        if s["kind"] == "drop":
            cues += [{"section": s["name"], "step": k, "kind": "slide", "what": f"slide {k + 1}", "sound": ""}
                     for k in range(s["steps"] - s["silence_steps"])]
        else:
            cues.append({"section": s["name"], "step": 0, "kind": "cut", "what": f"{s['name']} starts", "sound": ""})
    return cues


# ------------------------------------------------------------------ real audio: decode, measure, mix

def _decode(ffmpeg: str, path: Path, channels: int = 2, rate: int = RATE) -> list[list[float]]:
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file", "-i", "file:" + str(path),
           "-vn", "-ac", str(channels), "-ar", str(rate), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise GridError(f"cannot read the audio of {path.name}: " + proc.stderr.decode("utf-8", "replace").strip()[-200:])
    vals = struct.unpack("<%dh" % (len(proc.stdout) // 2), proc.stdout[: len(proc.stdout) // 2 * 2])
    return [[v / 32768.0 for v in vals[c::channels]] for c in range(channels)]


def measure(p: dict, mono: list[float], rate: int) -> dict:
    """Where the hits are in a track made elsewhere. Finds how far the track sits off the grid (so it can
    be shifted), then marks every sixteenth where the level jumps."""
    if rate > 24000:                                       # attacks of low drums vanish in the difference at high rates
        from .analysis.beats import resample
        mono, rate = resample(mono, rate, 22050), 22050
    win = max(1, int(0.012 * rate))
    sq, prev = [0.0], 0.0
    for x in mono:                                         # the first difference keeps the attacks, drops the bass
        sq.append(sq[-1] + (x - prev) ** 2)
        prev = x

    def energy(a: int, b: int) -> float:
        a, b = max(0, min(len(mono), a)), max(0, min(len(mono), b))
        return (sq[b] - sq[a]) / max(1, b - a)

    def rise(sample: int) -> float:
        after, before = math.sqrt(energy(sample, sample + win)), math.sqrt(energy(sample - win, sample - win // 4))
        return after if after > 1.5 * before else 0.0

    step_s = p["sixteenth_frames"] / p["fps"]
    steps = min(p["steps"], int(len(mono) / rate / step_s))
    if steps < 8:
        raise GridError("the track is shorter than two beats of the plan")
    beats = range(0, steps, 4)
    best, best_ms = -1.0, 0
    for ms in range(-60, 61, 2):
        score = sum(rise(int((k * step_s + ms / 1000) * rate)) for k in beats)
        if score > best:
            best, best_ms = score, ms
    rises = [rise(int((k * step_s + best_ms / 1000) * rate)) for k in range(steps)]
    top = sorted(rises)[-max(1, steps // 20)] or 1.0       # a strong hit, ignoring the single loudest
    hits = [k for k, r in enumerate(rises) if r >= 0.1 * top]
    on_beat = sum(1 for k in beats if k in hits) / max(1, len(beats))
    return {"offset_ms": best_ms, "steps_measured": steps, "hits": hits, "beats_with_a_hit": round(on_beat, 2),
            "track_seconds": round(len(mono) / rate, 3), "plan_seconds": p["seconds"],
            "advice": ([f"shift the track by {-best_ms} ms so its hits sit on the frames"] if abs(best_ms) > 8 else []) +
                      (["fewer than three beats in four carry a hit: the tempo may not be the plan's"] if on_beat < 0.75 else []) +
                      ([f"the track is {len(mono) / rate - p['seconds']:+.2f} s against the plan"]
                       if abs(len(mono) / rate - p["seconds"]) > 0.05 else [])}


def _loudness(ffmpeg: str, path: Path) -> tuple[float, float]:
    proc = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-protocol_whitelist", "file", "-i", "file:" + str(path),
                           "-af", "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, timeout=600, check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr.decode("utf-8", "replace"))
    if not m:
        raise GridError("ffmpeg could not measure the loudness")
    d = json.loads(m.group(0))
    return float(d["input_i"]), float(d["input_tp"])


def mix(p: dict, cues: list[dict], out: Path, ffmpeg: str, music: Path | None, find_sound, music_shift_ms: float = 0.0,
        sfx_db: float = -8.0) -> dict:
    """The music plus one sound per cue, each starting on its frame; nothing in the silence; mastered to
    about -14 LUFS with peaks near -1.5 dB. find_sound(name) returns the file of a named sound."""
    total = step_sample(p, p["steps"])
    left, right = [0.0] * total, [0.0] * total
    notes: list[str] = []
    if music is not None:
        ml, mr = _decode(ffmpeg, music)
        shift = int(round(music_shift_ms / 1000 * RATE))
        for i in range(total):
            j = i - shift
            if 0 <= j < len(ml):
                left[i], right[i] = ml[j], mr[j]
    silent = silent_steps(p)
    placed, cache = [], {}
    beat_s = p["beat_frames"] / p["fps"]
    for i, cue in enumerate(cues):
        name = str(cue.get("sound") or "").strip()
        if not name:
            continue
        c = resolve_cue(p, cue)
        if c["on_grid"] and int(c["step"]) in silent:
            notes.append(f"cue {i + 1}: '{name}' left out, it falls in the beat of silence")
            continue
        if name not in cache:
            cache[name] = _decode(ffmpeg, find_sound(name))
            mono = [abs(x) for x in cache[name][0]]
            late = mono.index(max(mono)) / RATE * 1000 if mono else 0.0
            if late > 20:
                notes.append(f"'{name}' is loudest {late:.0f} ms after it starts: against a drum hit that sounds like a "
                             "flam, not one hit; pick a sound with an instant attack for cues on a beat")
            if len(cache[name][0]) / RATE > 4 * beat_s:
                notes.append(f"'{name}' is {len(cache[name][0]) / RATE:.1f} s long: a sound longer than a bar brings a rhythm of its own")
        sl, sr = cache[name]
        g = 10 ** ((float(cue.get("gain_db", sfx_db))) / 20)
        at = int(round(c["frame"] / p["fps"] * RATE))
        for k in range(min(len(sl), total - at)):
            left[at + k] += sl[k] * g
            right[at + k] += sr[k] * g
        placed.append({"cue": i + 1, "sound": name, "frame": c["frame"], "time": c["time"]})
    cut = int(0.008 * RATE)
    for step in sorted(silent):                            # sounds that started earlier stop at the silence too
        a, b = step_sample(p, step), step_sample(p, step + 1)
        first = step - 1 not in silent
        for i in range(a, min(b, total)):
            g = max(0.0, 1.0 - (i - a) / cut) if first else 0.0
            left[i] *= g
            right[i] *= g
    write_wav(out, left, right, 0.7)
    loud, peak = _loudness(ffmpeg, out)
    gain_db = min(TARGET_LUFS - loud, TARGET_PEAK_DB - peak)
    g = 10 ** (gain_db / 20) * 0.7 / (max(max(map(abs, left), default=0.0), max(map(abs, right), default=0.0)) or 1.0)
    write_wav(out, [x * g for x in left], [x * g for x in right], None)
    loud2, peak2 = _loudness(ffmpeg, out)
    if loud2 < TARGET_LUFS - 1.0:
        notes.append(f"{loud2:.1f} LUFS: the peaks stop it from reaching {TARGET_LUFS:g}; that is normal for sparse percussion")
    return {"path": str(out), "seconds": round(total / RATE, 3), "lufs": round(loud2, 1), "peak_db": round(peak2, 1),
            "sounds": placed, "notes": notes}
