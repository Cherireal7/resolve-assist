"""Service layer shared by the CLI and the MCP server. Returns plain dicts."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from importlib import resources
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .analyze import Stats, analyze_image, crop_borders
from .color.cdl import CDL
from .color.correct import auto_balance, match_shot, verify
from .color.looks import LOOKS, compose, list_looks, look_as_cdl, look_transform
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


# --------------------------------------------------------------------------- Phase 2: live Resolve

def _bridge():
    from .bridge import Bridge
    return Bridge()


def bridge_install(copy_to_clipboard: bool = True) -> dict:
    from .bridge import install
    return install(copy_to_clipboard)


def bridge_status() -> dict:
    b = _bridge()
    st = b.status()
    if st.get("running"):
        try:
            st["resolve"] = b.call("status", timeout=10)
        except Exception as exc:  # status file fine but call failed: report, don't crash
            st["call_error"] = str(exc)
    return st


def bridge_stop() -> dict:
    return _bridge().call("stop", timeout=10)


def clips() -> dict:
    return _bridge().call("list_clips")


def grab_frame(target: str = "current") -> dict:
    res = _bridge().call("grab_frame", timeout=45, target=target)
    path = Path(res["path"])
    deadline = time.monotonic() + 10
    while not path.is_file() and time.monotonic() < deadline:  # export may finish after the reply
        time.sleep(0.1)
    if not path.is_file():
        raise RuntimeError("Resolve reported success but the frame file did not appear")
    return res


def analyze_clip(target: str = "current") -> dict:
    """Grab the frame under the playhead (or the middle of a clip) and analyze it."""
    frame = grab_frame(target)
    return {"clip": frame.get("clip"), "frame_path": frame["path"], "analysis": analyze(frame["path"])}


def apply_grade(
    target: str = "current",
    slope: Any = 1.0, offset: Any = 0.0, power: Any = 1.0, saturation: float = 1.0,
    look: str | None = None, strength: float = 1.0, node: int = 1,
    confirm: bool = False, verify: bool = True,
) -> dict:
    """Apply a correction (and optional look) to a clip in Resolve.

    Without a look: exact CDL via SetCDL (editable in Resolve's CDL panel).
    With a look: a .cube is generated (correction + look) and loaded on the node.
    confirm=False only returns the plan (dry run). Changes go into a separate
    'resolve-assist' grade version, so the original grade is kept for undo.
    """
    if look is not None and look not in LOOKS:
        raise ValueError(f"unknown look '{look}'. Available: {', '.join(LOOKS)}")
    if not (1 <= int(node) <= 64):
        raise ValueError("node must be 1..64")
    cdl = _build_cdl(slope, offset, power, saturation)
    method = "lut" if look else "cdl"
    plan: dict[str, Any] = {"target": target, "node": int(node), "method": method,
                            "version": "changes go into grade version 'resolve-assist' (undo restores yours)"}
    if method == "cdl":
        applied = cdl.blend(strength)
        plan["cdl"] = applied.resolve_strings()
    else:
        plan["look"] = look
        plan["strength"] = strength
        plan["correction_cdl"] = cdl.resolve_strings()
    if not confirm:
        return {"dry_run": True, "plan": plan,
                "next": "Show the plan (and a render_preview) to the user; call again with confirm=true if they agree."}
    b = _bridge()
    if method == "cdl":
        s = applied.resolve_strings()
        res = b.call("apply_cdl", target=target, node=int(node), slope=s["Slope"], offset=s["Offset"],
                     power=s["Power"], saturation=s["Saturation"])
    else:
        # Correction as exact CDL, look as a LUT on the same node.
        s = cdl.resolve_strings()
        res = b.call("apply_cdl", target=target, node=int(node), slope=s["Slope"], offset=s["Offset"],
                     power=s["Power"], saturation=s["Saturation"])
        if not res.get("ok"):
            raise RuntimeError(f"Resolve did not accept the correction: {res}")
        lut = make_lut(f"ra-{look}-{int(time.time())}", look=look, strength=strength, size=33)
        plan["lut_path"] = lut["lut_path"]
        lut_res = b.call("apply_lut", target=target, node=int(node), lut=Path(lut["lut_path"]).name)
        plan["lut_attempts"] = lut_res.get("attempts")
        if lut_res.get("ok"):
            plan["method"] = "cdl+lut"
            res = lut_res
        else:
            # Fallback: Resolve refused the LUT. Fold an approximation of the look into the CDL.
            approx = compose(cdl, look_as_cdl(LOOKS[look], strength)) if cdl.power == (1.0, 1.0, 1.0) \
                else look_as_cdl(LOOKS[look], strength)
            a = approx.resolve_strings()
            res = b.call("apply_cdl", target=target, node=int(node), slope=a["Slope"], offset=a["Offset"],
                         power=a["Power"], saturation=a["Saturation"])
            res.setdefault("previous_version", lut_res.get("previous_version"))
            plan["method"] = "cdl-approximation"
            plan["cdl"] = a
            plan["note"] = "Resolve refused the LUT; the look was approximated with CDL values (no S-curve)."
    if not res.get("ok"):
        raise RuntimeError(f"Resolve did not accept the change: {res}")
    b.remember_previous(res.get("clip") or {}, res.get("previous_version"))
    out: dict[str, Any] = {"applied": True, "plan": plan, "resolve": res}
    if verify:
        try:
            after = analyze_clip(target)
            out["after"] = {"frame_path": after["frame_path"], "cast": after["analysis"]["cast"],
                            "median_luma": after["analysis"]["luma"]["p50"],
                            "warnings": after["analysis"]["warnings"]}
        except Exception as exc:
            out["verify_error"] = str(exc)
    return out


def undo_grade(target: str = "current") -> dict:
    """Switch the clip back to the grade version it had before resolve-assist changed it."""
    b = _bridge()
    clip = b.call("clip_info", target=target)
    previous = b.previous_version(clip) or "Version 1"
    res = b.call("undo", target=target, version=previous)
    return {"restored_version": previous, "resolve": res}


def stabilize(target: str = "current") -> dict:
    """Run Resolve's stabilizer on a clip (inside the resolve-assist grade version)."""
    b = _bridge()
    res = b.call("stabilize", timeout=600, target=target)
    b.remember_previous(res.get("clip") or {}, res.get("previous_version"))
    return res


AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff"}


def add_music(file: str) -> dict:
    """Put a music file from ~/Documents/resolve-assist/media under the timeline (on a timeline copy)."""
    from .bridge import media_dir
    name = Path(file).name  # only names inside the media folder
    src = media_dir() / name
    if src.suffix.lower() not in AUDIO_EXTS:
        raise ValueError(f"music must be one of {', '.join(sorted(AUDIO_EXTS))}")
    if not src.is_file():
        raise ValueError(f"put the file into {media_dir()} first (not found: {name})")
    b = _bridge()
    copy = b.call("duplicate_timeline")
    res = b.call("add_music", timeout=60, file=name)
    return {"timeline": copy, "music": res}


def add_title(text: str, at_seconds: float = 0.0, duration: float = 5.0, target: str = "1:1") -> dict:
    """Add a Text+ title over a clip (composited inside the clip with Fusion, so the edit never
    changes) on the timeline copy, fading in at at_seconds for duration seconds. '|' = new line."""
    if not 1 <= len(text) <= 200 or any(c in text for c in "\t\r\n"):
        raise ValueError("text must be 1..200 characters on one line (use | for a line break)")
    b = _bridge()
    copy = b.call("duplicate_timeline")
    res = b.call("add_title", timeout=60, text=text, at=f"{float(at_seconds):.3f}",
                 duration=f"{float(duration):.3f}", target=target)
    return {"timeline": copy, "title": res}


def make_music(preset: str = "calm-lofi", seconds: float | None = None) -> dict:
    """Generate a royalty-free preset track into the media folder. Without seconds, it matches
    the current timeline length (needs the bridge) or falls back to 30 s."""
    from .audio import generate
    from .bridge import media_dir
    if seconds is None:
        try:
            info = clips()
            frames = max(c["end"] for c in info["clips"]) - min(c["start"] for c in info["clips"])
            seconds = frames / float(info["fps"])
        except Exception:
            seconds = 30.0
    return generate(preset, float(seconds), media_dir() / f"{safe_name(preset)}-preset.wav")


def reset_copy() -> dict:
    """Delete the resolve-assist timeline copy (only a copy, never the original) and reopen the original."""
    return _bridge().call("reset_copy", timeout=60)


# --------------------------------------------------------------------------- Phase 4: analysis engine

def _video_shots(path: Path, fps: float):
    from .analysis.shots import detect_shots
    from .analysis.video import sample_frames
    from .analyze import apply_box
    frames = sample_frames(path, fps=fps)
    if not frames:
        raise ValueError("no frames could be read from the video")
    _img, border = crop_borders(frames[len(frames) // 2][1])
    if border:
        frames = [(t, apply_box(img, border["box"])) for t, img in frames]
    return frames, detect_shots(frames), border


def _contact_sheet(name: str, frames, shots) -> str:
    """One thumbnail per shot (its sharpest frame), left to right."""
    thumbs = []
    for s in shots:
        t, img = min(frames, key=lambda f: abs(f[0] - s.best_time))
        thumbs.append(img)
    h = min(i.height for i in thumbs)
    gap = 4
    w_total = sum(i.width for i in thumbs) + gap * (len(thumbs) - 1)
    rows = []
    for y in range(h):
        for k, img in enumerate(thumbs):
            rows.extend(img.pixels[y * img.width:(y + 1) * img.width])
            if k < len(thumbs) - 1:
                rows.extend([(0.0, 0.0, 0.0)] * gap)
    target = output_path(safe_name(name) + "-shots", ".png", subdir="previews", overwrite=True)
    target.write_bytes(encode_png(w_total, h, rows))
    return str(target)


def analyze_video(path: str, fps: float = 4.0, top_match_cuts: int = 5) -> dict:
    """Shots, best frame per shot, match-cut candidates and a contact sheet for one video."""
    from .analysis.shots import match_cuts
    from .analysis.video import probe
    p = check_input_media(path)
    info = probe(p)
    frames, shots, border = _video_shots(p, fps)
    return {
        "video": info, "black_bars": border, "sampled_fps": fps, "shots": [s.to_dict() for s in shots],
        "match_cuts": match_cuts(shots, top=top_match_cuts),
        "contact_sheet": _contact_sheet(p.stem, frames, shots),
    }


def analyze_music(path: str) -> dict:
    """Tempo (BPM), beat and downbeat times of a music file or a video's soundtrack."""
    from .analysis.beats import analyze_audio
    from .analysis.video import extract_audio
    from .paths import check_input_audio
    p = check_input_audio(path)
    if p.suffix.lower() == ".wav":
        try:
            return analyze_audio(p)
        except ValueError:
            pass  # not 16-bit: decode through ffmpeg below
    tmp = extract_audio(p)
    try:
        return analyze_audio(tmp)
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def beat_edit_plan(videos: list[str], music: str, beats_per_cut: int = 2, order: str = "match",
                   max_seconds: float | None = None, fps: float = 4.0) -> dict:
    """Cut list for a music-driven edit: cuts on beats, shots ordered for match cuts."""
    from .analysis.plan import plan_cuts
    if order not in ("match", "original"):
        raise ValueError("order must be 'match' or 'original'")
    from .analysis.shots import windows
    m = analyze_music(music)
    if not m["bpm"]:
        raise ValueError("no beat found in the music")
    seg_len = 60.0 / m["bpm"] * beats_per_cut
    shots_by_source = []
    for v in videos:
        p = check_input_media(v)
        frames, shots, _b = _video_shots(p, fps)
        shots_by_source.append((str(p), windows(frames, shots, seg_len)))  # beat-length moments
    duration = min(m["duration"], max_seconds) if max_seconds else m["duration"]
    plan = plan_cuts(shots_by_source, m["beats"], m["downbeats"], duration, beats_per_cut, order)
    plan["music"] = {"path": music, "bpm": m["bpm"], "confidence": m["confidence"], "duration": duration}
    return plan


# --------------------------------------------------------------------------- asset library

def library_build(force: bool = False) -> dict:
    """Generate (or complete) the royalty-free asset library in ~/Documents/resolve-assist/library."""
    from .library.build import build_library
    return build_library(force=force)


def library_search(query: str = "", category: str | None = None, limit: int = 20) -> dict:
    """Find assets by words (e.g. 'whoosh', 'light leak warm', 'vertical background')."""
    from .library.build import library_dir, search
    hits = search(query, category, limit)
    return {"root": str(library_dir()), "count": len(hits),
            "items": [{**h, "path": str(library_dir() / h["file"])} for h in hits]}


def _library_rel(name_or_file: str) -> str:
    from .library.build import library_dir, load_manifest
    for it in load_manifest().get("items", []):
        if name_or_file in (it["id"], it["file"]):
            return it["file"]
    p = (library_dir() / name_or_file).resolve()
    if p.parent != p and library_dir().resolve() in p.parents and p.is_file():
        return str(p.relative_to(library_dir().resolve()))
    raise ValueError(f"not in the library: {name_or_file} (try library_search)")


def import_assets(names: list[str]) -> dict:
    """Import library assets (ids or relative files) into the Media Pool bin 'resolve-assist library'."""
    if not 1 <= len(names) <= 30:
        raise ValueError("give 1..30 assets")
    rels = [_library_rel(n) for n in names]
    return _bridge().call("import_media", timeout=120, files="|".join(rels))


def apply_powergrade(file: str, target: str = "current", mode: int = 0) -> dict:
    """Apply a PowerGrade (.drx from library/powergrades) to a clip, in the resolve-assist grade version."""
    rel = _library_rel(file if file.startswith("powergrades/") else f"powergrades/{Path(file).name}")
    b = _bridge()
    res = b.call("apply_drx", target=target, file=rel, mode=int(mode))
    b.remember_previous(res.get("clip") or {}, res.get("previous_version"))
    return res


# --------------------------------------------------------------------------- formats & captions

def make_format(format: str = "9x16") -> dict:
    """Make a copy of the current timeline in a social format (9x16, 4x5, 1x1, 16x9), clips scaled to fit."""
    if format not in ("9x16", "4x5", "1x1", "16x9"):
        raise ValueError("format must be 9x16, 4x5, 1x1 or 16x9")
    return _bridge().call("make_format", timeout=60, format=format)


def captions_for_file(path: str, model: str = "base", language: str = "auto", max_chars: int = 32) -> dict:
    """Transcribe a video/audio file locally and write an SRT next to the other outputs."""
    from .captions import captions_dir, to_srt, transcribe
    from .paths import check_input_audio
    p = check_input_audio(path)
    cues = transcribe(p, model, language, max_chars)
    out = output_path(p.stem, ".srt", subdir="captions", overwrite=True)
    out.write_text(to_srt(cues), encoding="utf-8")
    result = {"srt": str(out), "cues": len(cues), "preview": [c.text for c in cues[:8]], "folder": str(captions_dir())}
    if not cues:
        result["note"] = ("No clear speech found (only music/background noise, or a language the model can't "
                          "read). Try language='en' or another code, or model='small'. Whisper is weak at Amharic.")
    return result


def captions_for_timeline(model: str = "base", language: str = "auto", max_chars: int = 32,
                          add_to_resolve: bool = True) -> dict:
    """Caption the current timeline: transcribe each clip's used part of its source file, shift it to
    timeline time, write one SRT, and (optionally) add it to a resolve-assist timeline copy."""
    from .captions import shift, to_srt, transcribe
    b = _bridge()
    info = b.call("list_clips")
    fps = float(info["fps"])
    t0 = info.get("start_frame") or min(c["start"] for c in info["clips"])
    cues, skipped = [], []
    for c in info["clips"]:
        f = c.get("file")
        if not f or not Path(f).is_file():
            skipped.append(f"{c['name']}: source file not found")
            continue
        src_in = (c.get("source_offset") or 0) / fps
        dur = (c["end"] - c["start"]) / fps
        try:
            part = transcribe(Path(f), model, language, max_chars, start=src_in, duration=dur)
        except Exception as exc:
            skipped.append(f"{c['name']}: {exc}")
            continue
        cues += shift(part, (c["start"] - t0) / fps, 0.0, dur)
    cues.sort(key=lambda q: q.start)
    name = safe_name(info["timeline"]) + "-captions"
    out = output_path(name, ".srt", subdir="captions", overwrite=True)
    out.write_text(to_srt(cues), encoding="utf-8")
    result = {"srt": str(out), "cues": len(cues), "preview": [q.text for q in cues[:8]], "skipped": skipped}
    if add_to_resolve and cues:
        result["copy"] = b.call("duplicate_timeline")
        result["resolve"] = b.call("import_subtitles", timeout=60, file=out.name)
    return result


# --------------------------------------------------------------------------- workspace

def doctor() -> dict:
    from .workspace import doctor as _doctor
    return _doctor()


def init_workspace() -> dict:
    from .workspace import init_workspace as _init
    return _init()


def new_project(name: str) -> dict:
    from .workspace import new_project as _new
    return _new(name)


# --------------------------------------------------------------------------- Phase 5: assembly

def _plan_line(*fields: Any) -> str:
    text = [str(f) for f in fields]
    for t in text:
        if any(c in t for c in "\t\r\n\x00"):
            raise ValueError("plan values may not contain tabs or newlines")
    return "\t".join(text) + "\n"


def build_edit(segments: list[dict], title: str = "Beat edit", music: str | None = None,
               sfx_on_cuts: str | None = None, sfx_lead: float = 0.4) -> dict:
    """Assemble segments [{source, source_in, source_out}] into a NEW '(resolve-assist)' timeline,
    with optional music on A1, an SFX from the library on every cut (A2) and a marker per cut."""
    from .bridge import bridge_dir
    if not segments:
        raise ValueError("no segments")
    lines = [_plan_line("title", safe_name(title).replace(".", "")[:50] or "Beat edit")]
    t = 0.0
    cuts = []
    for s in segments:
        src = str(Path(s["source"]).expanduser().resolve())
        a, b = float(s["source_in"]), float(s["source_out"])
        if b <= a:
            raise ValueError(f"segment out <= in for {src}")
        lines.append(_plan_line("seg", src, f"{a:.3f}", f"{b:.3f}"))
        t += b - a
        cuts.append(t)
    cuts = cuts[:-1]
    if music:
        mp = Path(music).expanduser()
        if not mp.is_absolute():
            mp = (Path(output_dir()) / "library" / _library_rel(music))
        lines.append(_plan_line("music", str(mp.resolve())))
    if sfx_on_cuts:
        sfx_path = (output_dir() / "library" / _library_rel(sfx_on_cuts)).resolve()
        for c in cuts:
            lines.append(_plan_line("sfx", str(sfx_path), f"{max(0.0, c - sfx_lead):.3f}"))
    for c in cuts:
        lines.append(_plan_line("marker", f"{c:.3f}", "cut"))
    name = f"edit-{int(time.time() * 1000)}.plan"
    plans = bridge_dir() / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / name).write_text("".join(lines), encoding="utf-8")
    return _bridge().call("build_edit", timeout=180, file=name)


def assemble_beat_edit(videos: list[str], music: str, beats_per_cut: int = 2, order: str = "match",
                       max_seconds: float | None = None, sfx_on_cuts: str | None = "whoosh-medium",
                       title: str = "Beat edit") -> dict:
    """Plan (beats + match cuts) and build it in Resolve in one go."""
    plan = beat_edit_plan(videos, music, beats_per_cut, order, max_seconds)
    segs = [{"source": s["source"], "source_in": s["source_in"], "source_out": s["source_out"]}
            for s in plan["segments"]]
    music_path = str(Path(music).expanduser().resolve())
    built = build_edit(segs, title=title, music=music_path, sfx_on_cuts=sfx_on_cuts)
    return {"plan": plan, "resolve": built}
