"""Auto captions, fully local: ffmpeg → whisper.cpp → SRT (short, social-style lines).

whisper.cpp (`brew install whisper-cpp`) runs on Apple Silicon's GPU. Models are downloaded
once from the official whisper.cpp repository on Hugging Face into
~/Documents/resolve-assist/models. Audio never leaves the Mac.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import find_ffmpeg, output_dir

MODELS = {  # name: (file, approx MB)
    "tiny": ("ggml-tiny.bin", 75),
    "base": ("ggml-base.bin", 142),
    "small": ("ggml-small.bin", 466),
    "medium": ("ggml-medium.bin", 1500),
}
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file}"
_MAGICS = (b"lmgg", b"ggml", b"GGUF", b"ggjt")


class CaptionError(RuntimeError):
    pass


@dataclass
class Cue:
    start: float
    end: float
    text: str


def models_dir() -> Path:
    return output_dir() / "models"


def captions_dir() -> Path:
    return output_dir() / "captions"


def find_whisper() -> str | None:
    for name in ("whisper-cli", "whisper-cpp", "whisper"):
        found = shutil.which(name) or (f"/opt/homebrew/bin/{name}" if Path(f"/opt/homebrew/bin/{name}").is_file() else None)
        if found:
            return found
    return None


def ensure_model(name: str = "base", log=lambda m: None) -> Path:
    if name not in MODELS:
        raise ValueError(f"model must be one of {', '.join(MODELS)}")
    file, mb = MODELS[name]
    path = models_dir() / file
    if path.is_file() and _valid_model(path, mb):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    log(f"downloading whisper model '{name}' (~{mb} MB, once)...")
    req = urllib.request.Request(MODEL_URL.format(file=file), headers={"User-Agent": "resolve-assist"})
    with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1024 * 1024)
    if not _valid_model(part, mb):
        part.unlink(missing_ok=True)
        raise CaptionError("downloaded model looks invalid; try again")
    part.replace(path)
    return path


def _valid_model(path: Path, mb: int) -> bool:
    if path.stat().st_size < mb * 1024 * 1024 * 0.8:
        return False
    with path.open("rb") as fh:
        return fh.read(4) in _MAGICS


def _extract_wav(src: Path, start: float | None, duration: float | None, tmp: Path) -> Path:
    ff = find_ffmpeg()
    if not ff:
        raise CaptionError("captions need ffmpeg: brew install ffmpeg")
    out = tmp / "audio16k.wav"
    cmd = [ff, "-nostdin", "-hide_banner", "-v", "error", "-y", "-protocol_whitelist", "file"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", "file:" + str(src)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
    proc = subprocess.run(cmd, capture_output=True, timeout=900, check=False)
    if proc.returncode != 0 or not out.is_file():
        raise CaptionError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or "no audio track")
    return out


def transcribe(src: Path, model: str = "base", language: str = "auto", max_chars: int = 32,
               start: float | None = None, duration: float | None = None, log=lambda m: None) -> list[Cue]:
    whisper = find_whisper()
    if not whisper:
        raise CaptionError("captions need whisper.cpp: brew install whisper-cpp")
    if not re.fullmatch(r"[a-z]{2,3}|auto", language):
        raise ValueError("language must be 'auto' or a code like 'en', 'am', 'de'")
    model_path = ensure_model(model, log)
    with tempfile.TemporaryDirectory(prefix="resolve-assist-cap-") as d:
        tmp = Path(d)
        wav = _extract_wav(src, start, duration, tmp)
        base = tmp / "out"
        cmd = [whisper, "-m", str(model_path), "-f", str(wav), "-l", language, "-osrt", "-of", str(base),
               "-ml", str(max_chars), "-sow", "-np"]
        proc = subprocess.run(cmd, capture_output=True, timeout=3600, check=False)
        srt = base.with_suffix(".srt")
        if proc.returncode != 0 or not srt.is_file():
            raise CaptionError(proc.stderr.decode("utf-8", "replace").strip()[-400:] or "whisper failed")
        return parse_srt(srt.read_text(encoding="utf-8", errors="replace"))


_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            m = _TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = " ".join(lines[i + 1:]).strip()
                if body and not re.fullmatch(r"\[[^\]]*\]|\([^)]*\)", body):  # drop [MUSIC], (laughs)
                    cues.append(Cue(start, end, body))
                break
    return cues


def _fmt(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(cues: list[Cue]) -> str:
    return "".join(f"{i}\n{_fmt(c.start)} --> {_fmt(c.end)}\n{c.text}\n\n" for i, c in enumerate(cues, 1))


def shift(cues: list[Cue], offset: float, clip_from: float = 0.0, clip_to: float | None = None) -> list[Cue]:
    out = []
    for c in cues:
        s, e = max(c.start, clip_from), min(c.end, clip_to) if clip_to is not None else c.end
        if e > s:
            out.append(Cue(s + offset, e + offset, c.text))
    return out
