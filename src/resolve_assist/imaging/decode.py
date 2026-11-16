"""Decoder chain: ffmpeg (any still/video) → sips (macOS stills) → built-in PNG decoder."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..paths import STILL_EXTS, find_ffmpeg
from .png import Image, PNGError, decode_png

FFMPEG_TIMEOUT_S = 60
MAX_PIPE_BYTES = 64 * 1024 * 1024


class DecodeError(RuntimeError):
    pass


def decode(path: Path, time_seconds: float | None = None, max_side: int = 512) -> tuple[Image, str]:
    """Return (image, decoder_name). `path` must already be validated by paths.check_input_media."""
    ffmpeg = find_ffmpeg()
    errors: list[str] = []
    if ffmpeg:
        try:
            return _decode_ffmpeg(ffmpeg, path, time_seconds, max_side), "ffmpeg"
        except DecodeError as exc:
            errors.append(f"ffmpeg: {exc}")
    sips = shutil.which("sips") if sys.platform == "darwin" else None
    if sips and path.suffix.lower() in STILL_EXTS:
        try:
            return _decode_sips(sips, path, max_side), "sips"
        except DecodeError as exc:
            errors.append(f"sips: {exc}")
    if path.suffix.lower() == ".png":
        try:
            return decode_png(path.read_bytes(), max_side), "builtin-png"
        except PNGError as exc:
            errors.append(f"builtin-png: {exc}")
    hint = ""
    if not ffmpeg:
        if path.suffix.lower() in STILL_EXTS:
            hint = " Export the still as PNG from Resolve, or install ffmpeg (brew install ffmpeg)."
        else:
            hint = " Video needs ffmpeg (brew install ffmpeg), or export a PNG still from Resolve."
    detail = "; ".join(errors) if errors else "no decoder available"
    raise DecodeError(f"could not decode {path.name}: {detail}.{hint}")


def _decode_sips(sips: str, path: Path, max_side: int) -> Image:
    """macOS built-in converter: any still → small PNG in a private temp dir."""
    src_w, src_h = _sips_size(sips, path)
    with tempfile.TemporaryDirectory(prefix="resolve-assist-") as tmp:
        out = Path(tmp) / "frame.png"
        resize = ["-Z", str(max_side)] if max(src_w, src_h) > max_side else []  # -Z also upscales
        cmd = [sips, *resize, "-s", "format", "png", str(path), "--out", str(out)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise DecodeError(f"sips failed: {exc}") from exc
        if proc.returncode != 0 or not out.is_file():
            msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise DecodeError(msg[-1] if msg else f"exit code {proc.returncode}")
        if out.stat().st_size > MAX_PIPE_BYTES:
            raise DecodeError("converted frame unexpectedly large")
        try:
            img = decode_png(out.read_bytes(), max_side)
        except PNGError as exc:
            raise DecodeError(str(exc)) from exc
    img.source_width, img.source_height = src_w, src_h
    return img


def _sips_size(sips: str, path: Path) -> tuple[int, int]:
    try:
        proc = subprocess.run([sips, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                              capture_output=True, timeout=30, check=False, text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise DecodeError(f"sips failed: {exc}") from exc
    dims = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.strip().partition(":")
        if key in ("pixelWidth", "pixelHeight") and value.strip().isdigit():
            dims[key] = int(value)
    if len(dims) != 2:
        raise DecodeError("sips could not read the image size")
    return dims["pixelWidth"], dims["pixelHeight"]


def _decode_ffmpeg(ffmpeg: str, path: Path, time_seconds: float | None, max_side: int) -> Image:
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-protocol_whitelist", "file"]
    if time_seconds is not None:
        if not (0 <= time_seconds < 10 * 3600):
            raise DecodeError("time_seconds out of range")
        cmd += ["-ss", f"{time_seconds:.3f}"]
    cmd += [
        "-i", "file:" + str(path),
        "-frames:v", "1",
        "-vf", f"scale=w={max_side}:h={max_side}:force_original_aspect_ratio=decrease",
        "-pix_fmt", "rgb48be",
        "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DecodeError("ffmpeg timed out") from exc
    except OSError as exc:
        raise DecodeError(f"ffmpeg failed to start: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DecodeError(msg[-1] if msg else f"exit code {proc.returncode}")
    if len(proc.stdout) > MAX_PIPE_BYTES:
        raise DecodeError("decoded frame unexpectedly large")
    try:
        img = decode_png(proc.stdout, max_side)
    except PNGError as exc:
        raise DecodeError(str(exc)) from exc
    img.source_width = img.source_height = 0  # ffmpeg already scaled: original size unknown
    return img
