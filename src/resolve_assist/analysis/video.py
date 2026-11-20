"""Sample thumbnails and audio from video files with ffmpeg (required for video)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from ..imaging.png import PNG_SIGNATURE, Image, decode_png
from ..paths import find_ffmpeg

TIMEOUT_S = 600
MAX_FRAMES = 3000


class VideoError(RuntimeError):
    pass


def _ffmpeg() -> str:
    ff = find_ffmpeg()
    if not ff:
        raise VideoError("video analysis needs ffmpeg: brew install ffmpeg")
    return ff


def probe(path: Path) -> dict:
    ff = _ffmpeg()
    ffprobe = str(Path(ff).with_name("ffprobe"))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or ""
    if not ffprobe:
        raise VideoError("ffprobe not found next to ffmpeg")
    cmd = [ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_entries",
           "format=duration:stream=codec_type,width,height,r_frame_rate:stream_side_data=rotation",
           "-of", "json", "file:" + str(path)]
    proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise VideoError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or "ffprobe failed")
    data = json.loads(proc.stdout or b"{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = (video.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    w, h = video.get("width"), video.get("height")
    if abs(rotation) % 180 == 90:  # phones store portrait video sideways + a rotate flag
        w, h = h, w
    return {"duration": float(data.get("format", {}).get("duration") or 0.0),
            "width": w, "height": h, "stored_size": [video.get("width"), video.get("height")],
            "rotation": rotation, "orientation": "portrait" if (h or 0) > (w or 0) else "landscape",
            "fps": round(fps, 3),
            "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}


def _split_pngs(stream: bytes) -> list[bytes]:
    out, pos = [], 0
    while True:
        start = stream.find(PNG_SIGNATURE, pos)
        if start < 0:
            break
        end = stream.find(b"IEND", start)
        if end < 0:
            break
        end += 8  # IEND + CRC
        out.append(stream[start:end])
        pos = end
    return out


def sample_frames(path: Path, fps: float = 4.0, width: int = 112) -> list[tuple[float, Image]]:
    """Thumbnails every 1/fps seconds (black bars are kept; callers may crop)."""
    if not 0.1 <= fps <= 30:
        raise ValueError("fps must be 0.1..30")
    # -hwaccel auto: Apple's hardware decoder (VideoToolbox) makes 4K HEVC ~7x faster; ffmpeg
    # falls back to software decoding by itself when no hardware path exists.
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file",
           "-hwaccel", "auto", "-i", "file:" + str(path), "-vf", f"fps={fps},scale={width}:-2",
           "-frames:v", str(MAX_FRAMES),
           "-pix_fmt", "rgb24", "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as exc:
        raise VideoError("ffmpeg timed out while sampling frames") from exc
    if proc.returncode != 0:
        raise VideoError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or "ffmpeg failed")
    # ffmpeg already scaled them; don't shrink again (portrait frames are taller than `width`).
    return [(i / fps, decode_png(png, max_side=4096)) for i, png in enumerate(_split_pngs(proc.stdout))]


def extract_audio(path: Path, rate: int = 22050) -> Path:
    """Decode the audio track (or an mp3/m4a file) to a temporary 16-bit mono WAV."""
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file",
           "-i", "file:" + str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise VideoError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or "no audio track")
    tmp = Path(tempfile.mkdtemp(prefix="resolve-assist-")) / "audio.wav"
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(proc.stdout[: len(proc.stdout) // 2 * 2])
    return tmp

