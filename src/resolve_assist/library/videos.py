"""Overlay/transition video clips rendered with ffmpeg's built-in generators (needs ffmpeg).

Use them on a track above the cut with Composite Mode "Screen" (flashes, leaks, burns,
glitch) or "Overlay" (film grain).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..paths import find_ffmpeg

SIZE = "1920x1080"
FPS = 30


def _run(args: list[str], out: Path) -> None:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg is needed for video overlays: brew install ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-nostdin", "-hide_banner", "-v", "error", "-y", *args,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-movflags", "+faststart",
           str(out)]
    proc = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[-400:])


def flash(out: Path, color: str = "white", seconds: float = 0.6) -> None:
    _run(["-f", "lavfi", "-i", f"color=c={color}:s={SIZE}:d={seconds}:r={FPS}",
          "-vf", f"fade=t=in:st=0:d=0.08,fade=t=out:st=0.12:d={seconds - 0.12:.2f}"], out)


def film_grain(out: Path, seconds: float = 10.0, strength: int = 22) -> None:
    _run(["-f", "lavfi", "-i", f"color=c=0x808080:s={SIZE}:d={seconds}:r=24",
          "-vf", f"noise=alls={strength}:allf=t+u,format=gray"], out)


def leak_sweep(out: Path, still: Path, seconds: float = 2.0) -> None:
    """Pan across a light-leak still while it fades in and out."""
    vf = (f"scale=2560:1440,crop=1920:1080:x='(in_w-out_w)*t/{seconds}':y=180,"
          f"fade=t=in:st=0:d={seconds * 0.35:.2f},fade=t=out:st={seconds * 0.55:.2f}:d={seconds * 0.45:.2f}")
    _run(["-loop", "1", "-t", str(seconds), "-r", str(FPS), "-i", str(still), "-vf", vf], out)


def burn(out: Path, still: Path, seconds: float = 1.5) -> None:
    """Film-burn: a leak that zooms in fast and blows out to warm white."""
    frames = int(seconds * FPS)
    vf = (f"scale=3840:2160,zoompan=z='1+on*0.04':d={frames}:s={SIZE}:fps={FPS},"
          f"eq=brightness='0.0':gamma=1.2,fade=t=out:st={seconds * 0.6:.2f}:d={seconds * 0.4:.2f}")
    _run(["-loop", "1", "-i", str(still), "-frames:v", str(frames), "-vf", vf], out)


def glitch(out: Path, seconds: float = 0.5) -> None:
    vf = "noise=alls=100:allf=t,scale=1920:1080:flags=neighbor,rgbashift=rh=12:bv=8:gh=-6,eq=contrast=2.0"
    _run(["-f", "lavfi", "-i", f"color=c=black:s=240x135:d={seconds}:r={FPS}", "-vf", vf], out)
