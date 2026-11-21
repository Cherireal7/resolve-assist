"""Narration: script text -> voice audio + word timings + cue times (for captions and scene timing).

Script format: paragraphs separated by a blank line become segments with a short pause between them.
A marker such as {map} placed right before a word records the time that word is spoken as cue "map".

Providers:
- "edge": Microsoft neural voices through the optional `edge-tts` package. Natural voices in many
  languages (incl. Amharic). The script text is sent to Microsoft's speech service.
- "say": the macOS system voice. Fully local, plainer sound; word times come from local transcription.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .paths import find_ffmpeg

RATE = 48000
PUNCT = ".,:;?!።፣፤፦"
DEFAULT_VOICES = {"am": "am-ET-AmehaNeural", "en": "en-GB-RyanNeural"}


def language_of(text: str) -> str:
    return "am" if re.search(r"[ሀ-፿]", text) else "en"


def split_script(text: str) -> list[tuple[str, list[tuple[str, int]]]]:
    """[(clean text, [(cue name, character position)])] per paragraph."""
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        marks, clean = [], ""
        for part in re.split(r"(\{\w+\})", " ".join(para.split())):
            if re.fullmatch(r"\{\w+\}", part):
                marks.append((part[1:-1], len(clean)))
            else:
                clean += part
        if clean.strip():
            out.append((clean, marks))
    return out


def _pcm(ff: str, src: Path) -> bytes:
    proc = subprocess.run([ff, "-nostdin", "-v", "error", "-i", "file:" + str(src), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                          capture_output=True, timeout=600, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or "could not decode the voice audio")
    return proc.stdout


def _edge(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    import asyncio

    import edge_tts  # optional dependency: pip install 'resolve-assist[tts]'

    async def run() -> list[dict]:
        words = []
        com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        with out.open("wb") as fh:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    fh.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append({"text": ch["text"], "start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7})
        return words
    last: Exception | None = None
    for attempt in range(4):                 # the voice service sometimes answers a paragraph with no audio
        try:
            words = asyncio.run(run())
            if out.is_file() and out.stat().st_size > 1000:
                return words
            last = RuntimeError("the voice service returned no audio")
        except Exception as exc:             # network hiccup or an empty reply: try again
            last = exc
        import time
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"the online voice did not answer after several tries ({last}). Try again, or use the offline voice.")


def _say(text: str, voice: str | None, out: Path) -> list[dict]:
    if not shutil.which("say"):
        raise RuntimeError("the local voice needs macOS 'say'")
    cmd = ["say", "-o", str(out)] + (["-v", voice] if voice else []) + ["--", text]
    proc = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[-200:] or "'say' failed")
    from .captions import transcribe
    return [{"text": c.text.strip(), "start": c.start, "end": c.end} for c in transcribe(out, max_chars=1)]


def locate(clean: str, spoken: list[dict]) -> list[int]:
    """Character position of every spoken token in the script (tokens can span several words)."""
    pos, cursor = [], 0
    low = clean.lower()
    for w in spoken:
        j = low.find(w["text"].lower().strip(PUNCT + " "), cursor)
        if j < 0:
            j = cursor
        pos.append(j)
        cursor = j + max(1, len(w["text"].strip()))
    return pos


def narrate(text: str, audio_out: Path, data_out: Path, voice: str | None = None, rate: str = "+0%",
            provider: str = "auto", pause: float = 0.35, max_words: int = 4) -> dict:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("narration needs ffmpeg: brew install ffmpeg")
    if not re.fullmatch(r"[+-]\d{1,2}%", rate):
        raise ValueError("rate looks like +8% or -5%")
    segments = split_script(text)
    if not segments:
        raise ValueError("the script is empty")
    if sum(len(c) for c, _ in segments) > 12000:
        raise ValueError("the script is too long for one narration (12,000 characters)")
    if provider == "auto":
        try:
            import edge_tts  # noqa: F401
            provider = "edge"
        except ImportError:
            provider = "say"
    if provider not in ("edge", "say"):
        raise ValueError("provider must be auto, edge or say")
    lang = language_of(text)
    if provider == "edge":
        voice = voice or DEFAULT_VOICES[lang]
        if not re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z]+Neural", voice):
            raise ValueError("voice looks like en-GB-RyanNeural")
    elif voice and not re.fullmatch(r"[A-Za-z][A-Za-z ()-]{0,40}", voice):
        raise ValueError("unknown local voice name")

    pcm = bytearray()
    t = 0.0
    cues: dict[str, float] = {}
    words: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="resolve-assist-tts-") as d:
        for i, (clean, marks) in enumerate(segments):
            part = Path(d) / (f"seg{i}.mp3" if provider == "edge" else f"seg{i}.aiff")
            spoken = _edge(clean, voice, rate, part) if provider == "edge" else _say(clean, voice, part)
            audio = _pcm(ff, part)
            gap = pause if i else 0.25
            pcm += b"\0\0" * int(gap * RATE)
            t += gap
            where = locate(clean, spoken)
            for key, at in marks:
                k = next((n for n, j in enumerate(where) if j >= at), len(spoken) - 1)
                if spoken:
                    cues[key] = round(t + spoken[k]["start"], 3)
            for w, j in zip(spoken, where):
                end = j + len(w["text"])
                trail = clean[end:end + 1] if clean[end:end + 1] in PUNCT and clean[end:end + 1] else ""
                words.append({"text": w["text"].strip() + trail, "start": round(t + w["start"], 3), "end": round(t + w["end"], 3), "seg": i})
            pcm += audio
            t += len(audio) / 2 / RATE
    pcm += b"\0\0" * int(1.0 * RATE)
    t += 1.0

    line, n = 0, 0                     # caption lines: a few words, broken at punctuation and paragraphs
    for k, w in enumerate(words):
        w["line"] = line
        n += 1
        nxt = words[k + 1] if k + 1 < len(words) else None
        if nxt is None or nxt["seg"] != w["seg"] or n >= max_words or w["text"][-1:] in PUNCT:
            line, n = line + 1, 0
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(pcm))
    data = {"audio": str(audio_out), "provider": provider, "voice": voice or "system default", "rate": rate, "language": lang,
            "duration": round(t, 3), "cues": cues, "words": words,
            "script": "\n\n".join(c for c, _ in segments)}
    data_out.parent.mkdir(parents=True, exist_ok=True)
    data_out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return {k: data[k] for k in ("audio", "provider", "voice", "language", "duration", "cues")} | {
        "word_count": len(words), "lines": line, "data": str(data_out),
        "note": "Text was sent to Microsoft's speech service." if provider == "edge" else "Made locally with the system voice."}
