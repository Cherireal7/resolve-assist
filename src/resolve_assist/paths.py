"""Configuration and path safety. Every file the tools touch goes through here."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

STILL_EXTS = {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".dpx", ".exr", ".bmp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mxf", ".mkv", ".avi", ".mts", ".m2ts"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".flac"}
MEDIA_EXTS = STILL_EXTS | VIDEO_EXTS
MAX_STILL_BYTES = 1024 * 1024 * 1024        # 1 GB
MAX_VIDEO_BYTES = 200 * 1024 * 1024 * 1024  # 200 GB (ffmpeg seeks, never reads it all)

_NAME_RE = re.compile(r"[^A-Za-z0-9 _.-]+")


class PathError(ValueError):
    pass


def state_dir() -> Path:
    """Private state: probe report, future bridge queue."""
    return Path(os.environ.get("RESOLVE_ASSIST_HOME", "~/.resolve-assist")).expanduser()


def output_dir() -> Path:
    return Path(os.environ.get("RESOLVE_ASSIST_OUTPUT", "~/Documents/resolve-assist")).expanduser()


def resolve_support_dir() -> Path | None:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/Blackmagic Design/DaVinci Resolve"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Blackmagic Design/DaVinci Resolve/Support" if appdata else None
    return home / ".local/share/DaVinciResolve"


def resolve_scripts_dir() -> Path | None:
    base = resolve_support_dir()
    return base / "Fusion/Scripts/Utility" if base else None


def resolve_lut_dir() -> Path | None:
    """Where Resolve looks for LUTs (system-wide on macOS)."""
    override = os.environ.get("RESOLVE_ASSIST_LUT_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT")
    if os.name == "nt":
        pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(pd) / "Blackmagic Design/DaVinci Resolve/Support/LUT"
    return Path("/opt/resolve/LUT")


def find_ffmpeg() -> str | None:
    override = os.environ.get("RESOLVE_ASSIST_FFMPEG")
    if override == "none":  # explicit off-switch (tests of the fallback decoders)
        return None
    if override and Path(override).is_file():
        return override
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(candidate).is_file():
            return candidate
    return None


def check_input_media(path: str) -> Path:
    """Validate a media path the AI asked us to read. Returns an absolute path."""
    if not path or "\x00" in path:
        raise PathError("empty or invalid path")
    if "://" in path:
        raise PathError("URLs are not allowed; give a local file path")
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathError(f"file not found: {path}") from exc
    if not p.is_file():
        raise PathError(f"not a regular file: {p}")
    ext = p.suffix.lower()
    if ext not in MEDIA_EXTS:
        raise PathError(f"unsupported file type '{ext}'. Allowed: {', '.join(sorted(MEDIA_EXTS))}")
    limit = MAX_VIDEO_BYTES if ext in VIDEO_EXTS else MAX_STILL_BYTES
    if p.stat().st_size > limit:
        raise PathError("file is larger than the safety limit")
    return p


def safe_name(name: str, default: str = "grade") -> str:
    cleaned = _NAME_RE.sub("", name or "").strip(" .")[:64]
    return cleaned or default


def output_path(name: str, ext: str, subdir: str = "LUTs", overwrite: bool = False) -> Path:
    """A path inside the output allowlist. Never escapes it."""
    base = (output_dir() / subdir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = (base / f"{safe_name(name)}{ext}").resolve()
    if target.parent != base:
        raise PathError("output path escapes the output folder")
    if target.exists() and not overwrite:
        raise PathError(f"{target.name} already exists; pass overwrite=true or choose another name")
    return target


def check_input_audio(path: str) -> Path:
    """Validate an audio (or video, for its soundtrack) path the AI asked us to read."""
    if not path or "\x00" in path or "://" in path:
        raise PathError("give a local file path")
    try:
        p = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathError(f"file not found: {path}") from exc
    if not p.is_file():
        raise PathError(f"not a regular file: {p}")
    if p.suffix.lower() not in AUDIO_EXTS | VIDEO_EXTS:
        raise PathError(f"unsupported audio type '{p.suffix}'")
    if p.stat().st_size > MAX_VIDEO_BYTES:
        raise PathError("file is larger than the safety limit")
    return p
