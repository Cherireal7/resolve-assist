"""Service layer shared by the CLI and the MCP server. Returns plain dicts."""

from __future__ import annotations

import json
import os
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .analyze import Stats, analyze_image, crop_borders
from .color.cdl import CDL
from .color.correct import auto_balance, match_shot, verify
from .color.looks import LOOKS, list_looks, look_transform
from .color.lut import ALLOWED_SIZES, LUT3D
from .imaging.decode import decode
from .imaging.png import Image, encode_png
from .paths import (
    PathError,
    check_input_media,
    find_ffmpeg,
    output_dir,
    output_path,
    resolve_lut_dir,
    resolve_scripts_dir,
    safe_name,
    state_dir,
)

PROBE_SCRIPT_NAME = "resolve-assist Probe.lua"
PROBE_REPORT = "probe-report.json"


def _load(path: str, time_seconds: float | None) -> tuple[Image, Stats]:
    p = check_input_media(path)
    img, decoder = decode(p, time_seconds)
    img, border = crop_borders(img)  # balance/preview/verify all work on the real picture
    return img, analyze_image(img, decoder, crop=False, border=border)


def analyze(path: str, time_seconds: float | None = None) -> dict:
    _img, stats = _load(path, time_seconds)
    return stats.to_dict()


def balance(path: str, time_seconds: float | None = None, fix_exposure: bool = True) -> dict:
    img, stats = _load(path, time_seconds)
    cdl = auto_balance(stats, fix_exposure=fix_exposure)
    return {
        "cdl": cdl.to_dict(),
        "before": {"cast": stats.to_dict()["cast"], "median_luma": round(stats.luma.p50, 4)},
        "after": verify(cdl, img.pixels),
        "confidence": round(stats.confidence, 2),
        "warnings": stats.warnings,
        "how_to_apply": "Color page → node → CDL panel: paste Slope/Offset/Power/Sat, "
                        "or create a LUT from these values with make_lut and load it on the node.",
    }


def match(source_path: str, reference_path: str, strength: float = 1.0,
          source_time: float | None = None, reference_time: float | None = None) -> dict:
    src_img, src = _load(source_path, source_time)
    _ref_img, ref = _load(reference_path, reference_time)
    cdl = match_shot(src, ref, strength)
    after = verify(cdl, src_img.pixels)
    return {
        "cdl": cdl.to_dict(),
        "source_median_luma": round(src.luma.p50, 4),
        "reference_median_luma": round(ref.luma.p50, 4),
        "after": after,
    }


def _build_cdl(slope: Any, offset: Any, power: Any, saturation: float) -> CDL:
    return CDL.make(slope=slope, offset=offset, power=power, saturation=saturation)


def make_lut(
    name: str,
    look: str | None = None,
    strength: float = 1.0,
    slope: float | Sequence[float] | str = 1.0,
    offset: float | Sequence[float] | str = 0.0,
    power: float | Sequence[float] | str = 1.0,
    saturation: float = 1.0,
    size: int = 33,
    install_to_resolve: bool = False,
    overwrite: bool = False,
) -> dict:
    """CDL (correction) is applied first, then the optional look."""
    if size not in ALLOWED_SIZES:
        raise ValueError(f"size must be one of {ALLOWED_SIZES}")
    if look is not None and look not in LOOKS:
        raise ValueError(f"unknown look '{look}'. Available: {', '.join(LOOKS)}")
    base = _build_cdl(slope, offset, power, saturation)
    if look:
        fn = look_transform(LOOKS[look], strength, base=None if base.is_identity() else base)
    else:
        fn = base.blend(strength).apply
    title = safe_name(name)
    lut = LUT3D.from_transform(fn, size, title=title)
    target = output_path(title, ".cube", overwrite=overwrite)
    lut.write(target)
    result: dict[str, Any] = {"lut_path": str(target), "size": size, "look": look, "cdl": base.to_dict()}
    cc = target.with_suffix(".cc")
    if not cc.exists() or overwrite:
        cc.write_text(base.to_cc_xml(title), encoding="utf-8")
        result["cc_path"] = str(cc)
    result.update(_install_lut(target, overwrite) if install_to_resolve else {})
    result["how_to_apply"] = (
        "Resolve Color page → select node → right-click → LUT → resolve-assist → " + target.name
        if result.get("installed_path")
        else "Copy the .cube into Resolve's LUT folder (Project Settings → Color Management → "
             "Open LUT Folder), click 'Update Lists', then right-click a node → LUT."
    )
    return result


def _install_lut(src: Path, overwrite: bool) -> dict:
    lut_dir = resolve_lut_dir()
    if lut_dir is None:
        return {"install_error": "unknown Resolve LUT folder on this platform"}
    dest_dir = lut_dir / "resolve-assist"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists() and not overwrite:
            return {"install_error": f"{dest} exists; pass overwrite=true"}
        shutil.copyfile(src, dest)
        return {"installed_path": str(dest), "note": "In Resolve: Project Settings → Color Management → Update Lists"}
    except OSError as exc:
        return {"install_error": f"cannot write to {dest_dir}: {exc.strerror}. Copy the file manually."}


def preview(path: str, name: str, look: str | None = None, strength: float = 1.0,
            slope: Any = 1.0, offset: Any = 0.0, power: Any = 1.0, saturation: float = 1.0,
            time_seconds: float | None = None, overwrite: bool = True) -> dict:
    """Side-by-side before/after PNG rendered with our own engine (no Resolve needed)."""
    if look is not None and look not in LOOKS:
        raise ValueError(f"unknown look '{look}'")
    img, _stats = _load(path, time_seconds)
    base = _build_cdl(slope, offset, power, saturation)
    fn = look_transform(LOOKS[look], strength, base=base) if look else base.blend(strength).apply
    w, h = img.width, img.height
    gap = 4
    canvas = []
    for y in range(h):
        row = img.pixels[y * w:(y + 1) * w]
        canvas.extend(row)
        canvas.extend([(0.0, 0.0, 0.0)] * gap)
        canvas.extend(fn(p) for p in row)
    target = output_path(safe_name(name) + "-preview", ".png", subdir="previews", overwrite=overwrite)
    target.write_bytes(encode_png(2 * w + gap, h, canvas))
    return {"preview_path": str(target), "layout": "left = before, right = after", "width": 2 * w + gap, "height": h}


def looks() -> list[dict]:
    return list_looks()


def status() -> dict:
    scripts = resolve_scripts_dir()
    lut_dir = resolve_lut_dir()
    report = state_dir() / PROBE_REPORT
    try:
        import mcp  # noqa: F401
        has_mcp = True
    except ImportError:
        has_mcp = False
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "ffmpeg": find_ffmpeg() or "not found (PNG stills only; install with: brew install ffmpeg)",
        "mcp_sdk": has_mcp,
        "output_dir": str(output_dir()),
        "resolve_scripts_dir": str(scripts) if scripts else None,
        "resolve_scripts_dir_exists": bool(scripts and scripts.parent.parent.exists()),
        "probe_installed": bool(scripts and (scripts / PROBE_SCRIPT_NAME).exists()),
        "probe_report": str(report) if report.exists() else None,
        "resolve_lut_dir": str(lut_dir) if lut_dir else None,
        "resolve_lut_dir_writable": bool(lut_dir and lut_dir.exists() and os.access(lut_dir, os.W_OK)),
    }


def install_probe() -> dict:
    scripts = resolve_scripts_dir()
    if scripts is None:
        raise PathError("unknown Resolve scripts folder on this platform")
    source = resources.files("resolve_assist").joinpath("lua/probe.lua").read_text(encoding="utf-8")
    scripts.mkdir(parents=True, exist_ok=True)
    dest = scripts / PROBE_SCRIPT_NAME
    dest.write_text(source, encoding="utf-8")
    for d in probe_dirs():
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    return {
        "installed": str(dest),
        "next": "Open a project in Resolve (ideally with a clip on the timeline), then "
                "Workspace → Scripts → resolve-assist Probe. Then run: resolve-assist probe-report",
    }


def probe_dirs() -> list[Path]:
    """Where the probe may write. The App Store (sandboxed) Resolve can usually only
    reach ~/Movies or ~/Pictures, so the report may land there."""
    if os.environ.get("RESOLVE_ASSIST_HOME"):
        return [state_dir()]  # explicit override: one location only (also keeps tests hermetic)
    home = Path.home()
    return [state_dir(), home / "Movies" / "resolve-assist", home / "Pictures" / "resolve-assist"]


def probe_report() -> dict:
    """Read the probe result: JSON (io route) or Lua table (bmd.writefile fallback)."""
    candidates = [d / n for d in probe_dirs() for n in (PROBE_REPORT, "probe-report.lua")]
    existing = [c for c in candidates if c.exists()]
    for path in sorted(existing, key=lambda c: c.stat().st_mtime, reverse=True):
        parser = json.loads if path.suffix == ".json" else _parse_lua_json_field
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("probe report unexpectedly large")
        return {"found": True, "path": str(path), "report": parser(path.read_text(encoding="utf-8"))}
    return {"found": False, "hint": "Run the probe inside Resolve first (see install-probe). "
                                    "If no file appears, copy the JSON printed in Workspace → Console."}


def _parse_lua_json_field(text: str) -> dict:
    """Extract `json = "..."` from a bmd.writefile table without executing anything."""
    start = text.find("json")
    q = text.find('"', start)
    if start < 0 or q < 0:
        raise ValueError("no json field in Lua probe report")
    out = []
    i = q + 1
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'"}
    while i < len(text):
        c = text[i]
        if c == '"':
            return json.loads("".join(out))
        if c == "\\":
            nxt = text[i + 1]
            if nxt.isdigit():
                j = i + 1
                while j < len(text) and j < i + 4 and text[j].isdigit():
                    j += 1
                out.append(chr(int(text[i + 1:j])))
                i = j
                continue
            out.append(escapes.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    raise ValueError("unterminated json string in Lua probe report")
