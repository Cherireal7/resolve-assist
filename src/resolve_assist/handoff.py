"""Layered hand-off: turn a project's edit.json into separate files an editor can rebuild and change.

projects/<name>/handoff/
  video/   every picture clip, already cut (videos re-encoded, stills copied)
  motion/  every text clip as its own transparent .mov (needs Motion Studio), plus the end credit
  audio/   every sound clip as a WAV stem
  looks/   a .cube per graded clip (colour is not baked into the pictures)
  text/    titles.json (what each text says, when, in which style) and any captions (.srt)
  timeline.otio, timeline.fcpxml, manifest.json, README.md

Nothing is flattened: the editor gets layers. Colour, volume and fades are listed, not baked.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .paths import find_ffmpeg

FPS = 30
SIZES = {"9x16": (1080, 1920), "16x9": (1920, 1080)}
GRADE_KEYS = ("look", "lookStrength", "exposure", "contrast", "saturation", "temperature", "tint", "balance")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "project"


def _name(n: int, clip: dict, src: str | None = None) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", Path(src).stem if src else str(clip.get("text", clip["id"])))[:36].strip("-").lower()
    return f"{n:02d}-{stem or clip['id']}"


def _ff(args: list[str], out: Path) -> None:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("the hand-off needs ffmpeg: brew install ffmpeg")
    proc = subprocess.run([ff, "-nostdin", "-hide_banner", "-v", "error", "-y", "-protocol_whitelist", "file", *args, str(out)],
                          capture_output=True, timeout=3600, check=False)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[-300:] or f"ffmpeg could not write {out.name}")


def _lanes(clips: list[dict]) -> list[list[dict]]:
    """Clips that overlap in time cannot share one editor track: spread them over as few lanes as needed."""
    lanes: list[list[dict]] = []
    for c in sorted(clips, key=lambda x: x["start"]):
        lane = next((l for l in lanes if l[-1]["start"] + l[-1]["length"] <= c["start"] + 1e-6), None)
        if lane is None:
            lanes.append([c])
        else:
            lane.append(c)
    return lanes


def _rt(seconds: float) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(FPS), "value": float(round(seconds * FPS))}


def _range(start: float, length: float) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start), "duration": _rt(length)}


def otio_timeline(name: str, tracks: list[dict]) -> dict:
    """OpenTimelineIO JSON. `tracks` are bottom layer first: {name, kind: Video|Audio, items: [{file, start, length, name}]}."""
    children = []
    for t in tracks:
        kids, pos = [], 0.0
        for it in t["items"]:
            if it["start"] > pos + 1e-6:
                kids.append({"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": _range(0, it["start"] - pos), "effects": [], "markers": [], "metadata": {}})
            kids.append({"OTIO_SCHEMA": "Clip.2", "name": it["name"], "source_range": _range(0, it["length"]), "effects": [], "markers": [], "enabled": True,
                         "metadata": {"tibeb": it.get("meta", {})}, "active_media_reference_key": "DEFAULT_MEDIA",
                         "media_references": {"DEFAULT_MEDIA": {"OTIO_SCHEMA": "ExternalReference.1", "name": "", "metadata": {}, "target_url": it["file"],
                                                                "available_range": _range(0, it["length"]), "available_image_bounds": None}}})
            pos = it["start"] + it["length"]
        children.append({"OTIO_SCHEMA": "Track.1", "name": t["name"], "kind": t["kind"], "children": kids, "source_range": None, "effects": [], "markers": [], "enabled": True, "metadata": {}})
    return {"OTIO_SCHEMA": "Timeline.1", "name": name, "global_start_time": _rt(0), "metadata": {"made_with": "Tibeb / resolve-assist"},
            "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": children, "source_range": None, "effects": [], "markers": [], "enabled": True, "metadata": {}}}


def fcpxml(name: str, size: tuple[int, int], duration: float, tracks: list[dict], root: Path) -> str:
    """FCPXML 1.9: one gap as the main storyline, every clip connected to it on its own lane."""
    t = lambda s: f"{round(s * FPS)}/{FPS}s"
    assets, clips, n = [], [], 0
    video = [x for x in tracks if x["kind"] == "Video"]
    audio = [x for x in tracks if x["kind"] == "Audio"]
    for lane, tr in [(i + 1, x) for i, x in enumerate(video)] + [(-(i + 1), x) for i, x in enumerate(audio)]:
        for it in tr["items"]:
            n += 1
            aid = f"a{n}"
            uri = (root / it["file"]).resolve().as_uri()
            still = it["file"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            has_v, has_a = (tr["kind"] == "Video"), (tr["kind"] == "Audio" or it["file"].lower().endswith(".mp4"))
            fmt = ' format="r1"' if has_v else ""                      # no backslash inside an f-string expression: Python 3.10 and 3.11 reject it
            sound = ' audioSources="1" audioChannels="2" audioRate="48000"' if has_a and not still else ""
            assets.append(f'    <asset id="{aid}" name={quoteattr(it["name"])} start="0s" duration="{"0s" if still else t(it["length"])}" hasVideo="{int(has_v)}" hasAudio="{int(has_a and not still)}"'
                          f'{fmt}{sound}>\n'
                          f'      <media-rep kind="original-media" src={quoteattr(uri)}/>\n    </asset>')
            tag = "video" if still else "asset-clip"
            clips.append(f'            <{tag} ref="{aid}" lane="{lane}" offset="{t(it["start"])}" start="0s" duration="{t(it["length"])}" name={quoteattr(it["name"])}/>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.9">\n  <resources>\n'
            f'    <format id="r1" name="FFVideoFormatRateUndefined" frameDuration="1/{FPS}s" width="{size[0]}" height="{size[1]}"/>\n'
            + "\n".join(assets) + f'\n  </resources>\n  <library>\n    <event name={quoteattr(name)}>\n      <project name={quoteattr(name)}>\n'
            f'        <sequence format="r1" duration="{t(duration)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n          <spine>\n'
            f'          <gap name="Timeline" offset="0s" start="0s" duration="{t(duration)}">\n' + "\n".join(clips)
            + '\n          </gap>\n          </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n')


def _render_text(motion_dir: Path, cfg_path: Path, fmt: str) -> Path | None:
    """Render one transparent text overlay with Motion Studio (a login shell finds node as the terminal does)."""
    proc = subprocess.run(["/bin/zsh", "-ilc", 'exec node "$@"', "--", "scripts/render.mjs", str(cfg_path), "--format", fmt],
                          cwd=motion_dir, capture_output=True, timeout=1800, check=False)
    name = json.loads(cfg_path.read_text(encoding="utf-8"))["name"]
    out = motion_dir / "out" / f"{name}-{fmt}.mov"
    return out if proc.returncode == 0 and out.is_file() else None


def build(project_dir: Path, fmt: str = "9x16", motion_dir: Path | None = None, log=lambda m: None) -> dict:
    if fmt not in SIZES:
        raise ValueError("format must be 9x16 or 16x9")
    edit_file = project_dir / "edit.json"
    if not edit_file.is_file():
        raise ValueError("this project has no edit yet (open it in the editor first)")
    doc = json.loads(edit_file.read_text(encoding="utf-8"))
    prefix = f"projects/{_slug(project_dir.name)}/"
    out = project_dir / "handoff"
    if out.exists():
        shutil.rmtree(out)                  # generated folder: rebuilt from edit.json every time
    for d in ("video", "audio", "motion", "looks", "text"):
        (out / d).mkdir(parents=True)

    def source(src: str) -> Path:
        if not src.startswith(prefix):
            raise ValueError(f"only this project's own files can be handed off: {src}")
        p = (project_dir / src[len(prefix):]).resolve()
        if project_dir.resolve() not in p.parents or not p.is_file():
            raise ValueError(f"file not found in the project: {src}")
        return p

    duration = float(doc["duration"])
    n = 0
    items: list[dict] = []
    titles: list[dict] = []
    otio_video: list[dict] = []
    otio_audio: list[dict] = []
    notes: list[str] = []
    for track in reversed(doc["tracks"]):                       # bottom layer first, as editors stack them
        if track.get("muted"):
            notes.append(f"Track '{track['name']}' was muted and is left out.")
            continue
        for li, lane in enumerate(_lanes([c for c in track["clips"] if c["start"] < duration])):
            entries = []
            for c in lane:
                n += 1
                length = round(min(c["length"], duration - c["start"]), 3)
                meta = {"track": track["name"], "start": c["start"], "length": length}
                if c["kind"] in ("video", "image"):
                    src = source(c["src"])
                    if c["kind"] == "image":
                        rel = f"video/{_name(n, c, c['src'])}{src.suffix.lower()}"
                        shutil.copy2(src, out / rel)
                    else:
                        rel = f"video/{_name(n, c, c['src'])}.mp4"
                        _ff(["-ss", f"{c.get('in', 0):.3f}", "-t", f"{length:.3f}", "-i", "file:" + str(src), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"], out / rel)
                    meta.update({k: c[k] for k in ("volume", "fit", "scale", "x", "y", "opacity", "zoom") if k in c})
                    grade = {k: c[k] for k in GRADE_KEYS if c.get(k) not in (None, "")}
                    if grade:
                        meta["colour"] = grade
                        if grade.get("look"):
                            from .color.looks import LOOKS, look_transform
                            from .color.lut import LUT3D
                            cube = out / "looks" / f"{Path(rel).stem}.cube"
                            LUT3D.from_transform(look_transform(LOOKS[grade["look"]], float(grade.get("lookStrength", 1.0))), 33, title=grade["look"]).write(cube)
                            meta["lut"] = f"looks/{cube.name}"
                elif c["kind"] == "audio":
                    src = source(c["src"])
                    rel = f"audio/{_name(n, c, c['src'])}.wav"
                    _ff(["-ss", f"{c.get('in', 0):.3f}", "-t", f"{length:.3f}", "-i", "file:" + str(src), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le"], out / rel)
                    meta.update({k: c[k] for k in ("volume", "fadeIn", "fadeOut") if k in c})
                    if track.get("duck"):
                        meta["duck"] = track["duck"]
                else:
                    titles.append({"id": c["id"], **{k: c[k] for k in ("text", "start", "style", "typeface", "motion", "size", "color", "x", "y", "align") if k in c}, "length": length})
                    rel = ""
                    if motion_dir and (motion_dir / "scripts" / "render.mjs").is_file():
                        cfg = out / "text" / f"{_name(n, c)}.render.json"
                        cfg.write_text(json.dumps({"template": "Timeline", "format": fmt, "name": f"handoff-{_slug(project_dir.name)}-{n:02d}", "alpha": True,
                                                   "props": {"version": 1, "duration": max(1.0, length), "background": "#00000000", "credit": "",
                                                             "tracks": [{"id": "text", "name": "Text", "kind": "text", "clips": [{**c, "start": 0, "length": length}]}]}}), encoding="utf-8")
                        log(f"rendering text overlay {c['id']}…")
                        mov = _render_text(motion_dir, cfg, fmt)
                        cfg.unlink(missing_ok=True)
                        if mov:
                            rel = f"motion/{_name(n, c)}.mov"
                            shutil.move(str(mov), out / rel)
                    if not rel:
                        notes.append(f"Text '{str(c.get('text'))[:30]}' was not rendered (Motion Studio not available): recreate it from text/titles.json.")
                        continue
                    meta["text"] = c.get("text")
                item = {"id": c["id"], "track_id": track["id"], "file": rel, "kind": c["kind"], **meta}
                items.append(item)
                entries.append({"file": rel, "start": c["start"], "length": length, "name": Path(rel).stem, "meta": meta})
            if entries:
                (otio_audio if track["kind"] == "audio" else otio_video).append(
                    {"name": track["name"] + (f" {li + 1}" if li else ""), "kind": "Audio" if track["kind"] == "audio" else "Video", "items": entries})

    credit = doc.get("credit", "Edit by Cheri")
    if credit and motion_dir and (motion_dir / "scripts" / "render.mjs").is_file():
        cfg = out / "text" / "credit.render.json"
        cfg.write_text(json.dumps({"template": "Timeline", "format": fmt, "name": f"handoff-{_slug(project_dir.name)}-credit", "alpha": True,
                                   "props": {"version": 1, "duration": 2.2, "background": "#00000000", "credit": credit, "tracks": [{"id": "text", "name": "Text", "kind": "text", "clips": []}]}}), encoding="utf-8")
        mov = _render_text(motion_dir, cfg, fmt)
        cfg.unlink(missing_ok=True)
        if mov:
            shutil.move(str(mov), out / "motion" / "zz-credit.mov")
            entry = {"file": "motion/zz-credit.mov", "start": max(0.0, duration - 2.2), "length": min(2.2, duration), "name": "credit", "meta": {"text": credit}}
            items.append({"file": entry["file"], "kind": "text", "track": "Credit", "start": entry["start"], "length": entry["length"], "text": credit})
            otio_video.append({"name": "Credit", "kind": "Video", "items": [entry]})
    elif credit:
        notes.append(f"Add the end credit by hand: \"{credit}\".")
    for srt in sorted((project_dir / "captions").glob("*.srt")) if (project_dir / "captions").is_dir() else []:
        shutil.copy2(srt, out / "text" / srt.name)
    (out / "text" / "titles.json").write_text(json.dumps(titles, indent=1, ensure_ascii=False), encoding="utf-8")
    tracks = otio_video + otio_audio
    (out / "timeline.otio").write_text(json.dumps(otio_timeline(project_dir.name, tracks), indent=1), encoding="utf-8")
    (out / "timeline.fcpxml").write_text(fcpxml(project_dir.name, SIZES[fmt], duration, tracks, out), encoding="utf-8")
    manifest = {"project": project_dir.name, "format": fmt, "size": SIZES[fmt], "fps": FPS, "duration": duration, "items": items, "notes": notes}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "README.md").write_text(_readme(manifest), encoding="utf-8")
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    return {"handoff": str(out), "counts": counts, "notes": notes, "files": len(items),
            "next": "CapCut: new 9:16 project, import the handoff folder, place clips at the times in README.md. "
                    "Resolve: File → Import → Timeline → timeline.otio (or .fcpxml)."}


def _readme(m: dict) -> str:
    w, h = m["size"]
    rows = "\n".join(f"| {it['start']:.2f} | {it['length']:.2f} | {it['track']} | `{it['file']}` | "
                     + ", ".join(x for x in (f"volume {it['volume']}" if it.get("volume") not in (None, 1) else "",
                                             f"fade in {it['fadeIn']}s" if it.get("fadeIn") else "", f"fade out {it['fadeOut']}s" if it.get("fadeOut") else "",
                                             f"look: {it['lut']}" if it.get("lut") else "", "music dips under voice" if it.get("duck") else "") if x) + " |"
                     for it in sorted(m["items"], key=lambda i: (i["start"], i["track"])))
    notes = "".join(f"- {n}\n" for n in m["notes"]) or "- None.\n"
    return f"""# Hand-off: {m['project']}

{w}x{h}, {m['fps']} fps, {m['duration']} s. Every clip of the edit is a separate file, so it can be changed in any editor.
Colour, volume and fades are **not** baked in: they are listed below for you to apply (or not).

## CapCut
1. New project, ratio {'9:16' if h > w else '16:9'}, {m['fps']} fps.
2. Import this whole folder (Import → select `video`, `motion`, `audio`).
3. Put `video/` clips on the main track in the order below; `motion/` clips (transparent text) on tracks above, at their start times.
4. Put `audio/` clips on audio tracks at their start times; set volume and fades from the table.
5. Looks: Adjustment → LUT → import the `.cube` from `looks/` for the clip named in the table. Captions: Captions → Import file → `text/*.srt`.

## DaVinci Resolve (also Premiere, Final Cut)
File → Import → Timeline → `timeline.otio`. If the editor prefers XML, use `timeline.fcpxml`. Then relink to this folder if asked.
These two files were generated without being opened in an editor: if one is rejected, use the table below.

## Every clip

| Start (s) | Length (s) | Track | File | Apply |
|---|---|---|---|---|
{rows}

## Notes
{notes}"""
