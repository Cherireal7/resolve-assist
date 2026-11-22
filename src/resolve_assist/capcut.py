"""EXPERIMENTAL: write a CapCut desktop project (draft) from a layered hand-off.

CapCut has no public project format. This writer copies the structure of a project that CapCut itself
created on this machine (any existing draft is used as the template, so version and platform fields
match the installed app) and adds tracks, segments and materials for the hand-off's files.

Safety rules:
- only ever creates a NEW draft folder; never edits a draft it did not create;
- refuses to run while CapCut is open (CapCut rewrites its project list on exit);
- media is copied into the new draft folder, so the project does not depend on other locations;
- `remove` deletes only folders that carry this writer's marker file.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

MARKER = ".tibeb-draft"
US = 1_000_000
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
STILL_DURATION = 10_800_000_000        # CapCut gives stills a nominal three hours


def _still_size(path: Path) -> tuple[int, int] | tuple[()]:
    """Pixel size of a still when ffprobe is missing: the PNG header, else sips on macOS."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        sips = shutil.which("sips")
        if sips:
            from .imaging.decode import _sips_size
            return _sips_size(sips, path)
    except Exception:
        pass
    return ()


def drafts_dir() -> Path:
    return Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def capcut_running() -> bool:
    return subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True, check=False).returncode == 0


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _us(seconds: float) -> int:
    return int(round(seconds * US))


def find_template() -> Path:
    """Any draft CapCut made itself (not one of ours), newest first."""
    root = drafts_dir()
    if not root.is_dir():
        raise RuntimeError("CapCut's projects folder was not found. Open CapCut once and create a project.")
    own = sorted((d for d in root.iterdir() if d.is_dir() and (d / "draft_info.json").is_file() and not (d / MARKER).exists()),
                 key=lambda d: d.stat().st_mtime, reverse=True)
    if not own:
        raise RuntimeError("Create one (even empty) project in CapCut first: it is used as the template for the file format.")
    return own[0]


def _video_material(path: Path, name: str, duration_us: int, w: int, h: int, still: bool, has_audio: bool) -> dict:
    return {"aigc_type": "none", "audio_fade": None, "category_id": "", "category_name": "local", "check_flag": 62978047,
            "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                     "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
            "crop_ratio": "free", "crop_scale": 1.0, "duration": duration_us, "extra_type_option": 0, "formula_id": "", "freeze": None,
            "has_audio": has_audio, "height": h, "id": _uid(), "intensifies_audio_path": "", "intensifies_path": "", "is_ai_generate_content": False,
            "is_copyright": False, "is_unified_beauty_mode": False, "local_id": "", "local_material_id": "", "material_id": "", "material_name": name,
            "material_url": "", "media_path": "", "origin_material_id": "", "path": str(path), "picture_from": "none", "request_id": "",
            "reverse_intensifies_path": "", "reverse_path": "", "source_platform": 0, "team_id": "", "type": "photo" if still else "video",
            "video_algorithm": {"algorithms": [], "path": ""}, "width": w}


def _audio_material(path: Path, name: str, duration_us: int) -> dict:
    return {"app_id": 0, "category_id": "", "category_name": "local", "check_flag": 1, "copyright_limit_type": "none", "duration": duration_us,
            "effect_id": "", "formula_id": "", "id": _uid(), "intensifies_path": "", "is_ai_clone_tone": False, "is_text_edit_overdub": False, "is_ugc": False,
            "local_material_id": "", "music_id": "", "name": name, "path": str(path), "query": "", "request_id": "", "resource_id": "", "search_id": "",
            "source_from": "", "source_platform": 0, "team_id": "", "text_id": "", "tone_category_id": "", "tone_category_name": "", "tone_effect_id": "",
            "tone_effect_name": "", "tone_platform": "", "tone_second_category_id": "", "tone_second_category_name": "", "tone_speaker": "", "tone_type": "",
            "type": "extract_music", "video_id": "", "wave_points": []}


def _segment(material_id: str, start: float, length: float, refs: list[str], render_index: int, track_index: int, volume: float,
             visual: bool, scale: float = 1.0, alpha: float = 1.0) -> dict:
    seg = {"caption_info": None, "cartoon": False, "common_keyframes": [], "enable_adjust": True, "enable_color_correct_adjust": False,
           "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_lut": True,
           "enable_smart_color_adjust": False, "extra_material_refs": refs, "group_id": "", "id": _uid(), "intensifies_audio": False,
           "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 1.0, "material_id": material_id,
           "render_index": render_index, "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
           "reverse": False, "source_timerange": {"duration": _us(length), "start": 0}, "speed": 1.0,
           "target_timerange": {"duration": _us(length), "start": _us(start)}, "template_id": "", "template_scene": "default",
           "track_attribute": 0, "track_render_index": track_index, "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": volume}
    seg["clip"] = {"alpha": alpha, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": scale, "y": scale},
                   "transform": {"x": 0.0, "y": 0.0}} if visual else None
    seg["hdr_settings"] = {"intensity": 1.0, "mode": 1, "nits": 1000} if visual else None
    return seg


def _rgb(hex_color: str) -> list[float]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        return [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]
    except ValueError:
        return [1.0, 1.0, 1.0]


def _text_material(title: dict) -> dict:
    """A plain, editable CapCut text. Our animated styles do not exist in CapCut; the styled version is
    kept in the media bin as a transparent clip."""
    text = str(title.get("text", ""))
    size = round(max(4.0, min(60.0, float(title.get("size", 8)) * 1.5)), 2)
    color = _rgb(str(title.get("color", "#FFFFFF")))
    align = {"left": 0, "center": 1, "right": 2}.get(str(title.get("align", "center")), 1)
    content = {"text": text, "styles": [{"range": [0, len(text.encode("utf-16-le")) // 2], "size": size, "bold": True, "italic": False, "underline": False,
                                           "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": color}}},
                                           "font": {"id": "", "path": ""}}]}
    return {"add_type": 0, "alignment": align, "background_alpha": 1.0, "background_color": "", "background_style": 0, "bold_width": 0.0, "border_alpha": 1.0,
            "border_color": "", "border_width": 0.08, "check_flag": 7, "content": json.dumps(content, ensure_ascii=False), "font_name": "", "font_path": "", "font_size": size,
            "has_shadow": False, "id": _uid(), "italic_degree": 0, "letter_spacing": 0.0, "line_feed": 1, "line_max_width": 0.82, "line_spacing": 0.02,
            "shadow_alpha": 0.9, "shadow_color": "", "text_alpha": 1.0, "text_color": "#" + "".join(f"{round(v * 255):02X}" for v in color), "type": "text",
            "typesetting": 0, "underline": False, "use_effect_default_color": True, "words": {"end_time": [], "start_time": [], "text": []}}


def build_draft(handoff: Path, name: str, native_text: bool = True, log=lambda m: None) -> dict:
    """Create a new CapCut draft named `name` from a hand-off folder (manifest.json + media).
    native_text: titles become CapCut text you can retype (plain look); the styled, animated versions stay
    in the media bin as transparent clips. False = put the styled clips on the timeline instead."""
    from .analysis.video import probe
    running = capcut_running()      # a new folder is harmless while CapCut is open; it shows up after a restart
    manifest = json.loads((handoff / "manifest.json").read_text(encoding="utf-8"))
    template = find_template()
    info = json.loads((template / "draft_info.json").read_text(encoding="utf-8"))
    meta = json.loads((template / "draft_meta_info.json").read_text(encoding="utf-8"))
    root = drafts_dir()
    clean = "".join(c for c in name if c.isalnum() or c in " -_").strip()[:60] or "Tibeb project"
    folder = root / clean
    n = 2
    while folder.exists():
        folder = root / f"{clean} {n}"
        n += 1
    media_dir = folder / "Resources" / "tibeb"
    media_dir.mkdir(parents=True)
    (folder / MARKER).write_text(json.dumps({"note": "Created by resolve-assist (Tibeb). Delete with: resolve-assist capcut-remove",
                                              "handoff": str(handoff.resolve()), "project": manifest.get("project", "")}), encoding="utf-8")
    for sub in ("adjust_mask", "matting", "qr_upload", "smart_crop", "Resources/audioAlg", "Resources/videoAlg", "Resources/digitalHuman/audio",
                "Resources/digitalHuman/bsinfo", "Resources/digitalHuman/video"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    if (template / "common_attachment").is_dir():
        shutil.copytree(template / "common_attachment", folder / "common_attachment")
    for f in ("draft_agency_config.json", "draft_biz_config.json", "performance_opt_info.json", "attachment_editing.json"):
        if (template / f).is_file():
            shutil.copy2(template / f, folder / f)

    w, h = manifest["size"]
    duration = float(manifest["duration"])
    draft = copy.deepcopy(info)
    for key in draft["materials"]:
        draft["materials"][key] = []
    now_us = int(time.time() * US)
    draft.update({"id": _uid(), "name": folder.name, "duration": _us(duration), "tracks": [], "fps": float(manifest["fps"]),
                  "create_time": 0, "update_time": 0, "path": "", "cover": None})
    draft["canvas_config"] = {**draft.get("canvas_config", {}), "width": w, "height": h, "ratio": "9:16" if h > w else "16:9"}
    mats = draft["materials"]

    titles = []
    if native_text and (handoff / "text" / "titles.json").is_file():
        titles = json.loads((handoff / "text" / "titles.json").read_text(encoding="utf-8"))
    title_ids = {t["id"] for t in titles}
    by_track: dict[str, list[dict]] = {}
    spare: list[dict] = []          # styled text clips kept in the media bin only
    for it in manifest["items"]:
        if it["kind"] == "text" and it.get("id") in title_ids:
            spare.append(it)
        else:
            by_track.setdefault(it["track"], []).append(it)
    order = sorted(by_track, key=lambda t: (by_track[t][0]["kind"] == "audio", ))      # picture tracks first (bottom to top), then audio
    bin_items, ti = [], 0
    for tname in order:
        items = sorted(by_track[tname], key=lambda i: i["start"])
        is_audio = items[0]["kind"] == "audio"
        track = {"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False, "name": tname, "segments": [], "type": "audio" if is_audio else "video"}
        for it in items:
            src = handoff / it["file"]
            dst = media_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
            still = dst.suffix.lower() in IMAGE_EXT
            try:
                pr = probe(dst)
            except Exception:
                pr = dict(zip(("width", "height"), _still_size(dst))) if still else {}
            mw, mh = int(pr.get("width") or w), int(pr.get("height") or h)
            length = float(it["length"])
            speed = {"curve_speed": None, "id": _uid(), "mode": 0, "speed": 1.0, "type": "speed"}
            mats["speeds"].append(speed)
            refs = [speed["id"]]
            if is_audio:
                mat = _audio_material(dst, dst.name, _us(pr.get("duration") or length))
                mats["audios"].append(mat)
                if it.get("fadeIn") or it.get("fadeOut"):
                    fade = {"fade_in_duration": _us(it.get("fadeIn") or 0), "fade_out_duration": _us(it.get("fadeOut") or 0), "fade_type": 0, "id": _uid(), "type": "audio_fade"}
                    mats["audio_fades"].append(fade)
                    refs.append(fade["id"])
                seg = _segment(mat["id"], it["start"], length, refs, 0, ti, float(it.get("volume", 1.0)), visual=False)
            else:
                mat = _video_material(dst, dst.name, STILL_DURATION if still else _us(pr.get("duration") or length), mw, mh, still, bool(pr.get("has_audio")) and not still)
                mats["videos"].append(mat)
                canvas = {"album_image": "", "blur": 0.0, "color": "", "id": _uid(), "image": "", "image_id": "", "image_name": "", "source_platform": 0, "team_id": "", "type": "canvas_color"}
                chan = {"audio_channel_mapping": 0, "id": _uid(), "is_config_open": False, "type": ""}
                mats["canvases"].append(canvas)
                mats["sound_channel_mappings"].append(chan)
                refs += [canvas["id"], chan["id"]]
                # CapCut fits a clip inside the frame; "cover" in our edit means it must fill it
                fit, fill = min(w / mw, h / mh), max(w / mw, h / mh)
                scale = round(fill / fit * float(it.get("scale", 1.0)), 4) if it.get("fit", "cover") == "cover" else float(it.get("scale", 1.0))
                seg = _segment(mat["id"], it["start"], length, refs, ti, ti, float(it.get("volume", 1.0)), visual=True, scale=scale, alpha=float(it.get("opacity", 1.0)))
            track["segments"].append(seg)
            bin_items.append({"ai_group_type": "", "create_time": int(time.time()), "duration": mat["duration"] if not still else 5 * US, "enter_from": 0,
                              "extra_info": dst.name, "file_Path": str(dst), "height": mh if not is_audio else 0, "id": str(uuid.uuid4()), "import_time": int(time.time()),
                              "import_time_ms": now_us, "item_source": 1, "material_color_tag": "", "md5": "", "metetype": "music" if is_audio else ("photo" if still else "video"),
                              "roughcut_time_range": {"duration": mat["duration"] if not still else 5 * US, "start": 0}, "sub_time_range": {"duration": -1, "start": -1},
                              "type": 0, "width": mw if not is_audio else 0})
        draft["tracks"].append(track)
        ti += 1

    for it in spare:                # copy the styled overlays and list them in the bin
        src = handoff / it["file"]
        dst = media_dir / src.name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)
            bin_items.append({"ai_group_type": "", "create_time": int(time.time()), "duration": _us(it["length"]), "enter_from": 0, "extra_info": dst.name, "file_Path": str(dst),
                              "height": h, "id": str(uuid.uuid4()), "import_time": int(time.time()), "import_time_ms": now_us, "item_source": 1, "material_color_tag": "", "md5": "",
                              "metetype": "video", "roughcut_time_range": {"duration": _us(it["length"]), "start": 0}, "sub_time_range": {"duration": -1, "start": -1}, "type": 0, "width": w})
    if titles:
        track = {"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False, "name": "Titles", "segments": [], "type": "text"}
        for li, t in enumerate(sorted(titles, key=lambda x: x["start"])):
            mat = _text_material(t)
            mats.setdefault("texts", []).append(mat)
            seg = _segment(mat["id"], float(t["start"]), float(t["length"]), [], 14000 + li, ti, 1.0, visual=True)
            seg["clip"]["transform"] = {"x": round(float(t.get("x", 50)) / 50 - 1, 4), "y": round(-(float(t.get("y", 50)) / 50 - 1), 4)}
            seg["hdr_settings"] = None
            seg["tibeb_id"] = t["id"]
            track["segments"].append(seg)
        draft["tracks"].append(track)

    text = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
    (folder / "draft_info.json").write_text(text, encoding="utf-8")
    (folder / "draft_info.json.bak").write_text(text, encoding="utf-8")
    size = sum(f.stat().st_size for f in media_dir.iterdir())
    meta.update({"draft_fold_path": str(folder), "draft_id": _uid(), "draft_name": folder.name, "draft_root_path": str(root), "tm_draft_create": now_us,
                 "tm_draft_modified": now_us, "tm_duration": _us(duration), "draft_timeline_materials_size_": size, "draft_cover": "draft_cover.jpg",
                 "draft_materials": [{"type": 0, "value": bin_items}] + [{"type": t, "value": []} for t in (1, 2, 3, 6, 7, 8)]})
    (folder / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (folder / "draft_virtual_store.json").write_text(json.dumps({"draft_materials": [], "draft_virtual_store": [
        {"type": 0, "value": [{"creation_time": 0, "display_name": "", "filter_type": 0, "id": "", "import_time": 0, "import_time_us": 0, "material_color_tag": "", "sort_sub_type": 0, "sort_type": 0, "subdraft_filter_type": 0}]},
        {"type": 1, "value": [{"child_id": b["id"], "parent_id": ""} for b in bin_items]}, {"type": 2, "value": []}]}, separators=(",", ":")), encoding="utf-8")
    (folder / "timeline_layout.json").write_text(json.dumps({"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [draft["id"]], "timelineNames": [draft["id"]]}], "layoutOrientation": 1}, separators=(",", ":")), encoding="utf-8")
    now = int(time.time())
    (folder / "draft_settings").write_text(f"[General]\ndraft_create_time={now}\ndraft_last_edit_time={now}\nreal_edit_keys=1\nreal_edit_seconds=1\n", encoding="utf-8")
    first = next((media_dir / Path(i["file"]).name for i in manifest["items"] if i["kind"] in ("video", "image")), None)
    if first:
        from .paths import find_ffmpeg
        ff = find_ffmpeg()
        if ff:
            subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", str(first), "-frames:v", "1", "-vf", "scale=480:-2", str(folder / "draft_cover.jpg")],
                           capture_output=True, timeout=60, check=False)
    return {"draft": str(folder), "name": folder.name, "template": template.name, "tracks": [{"name": t["name"], "type": t["type"], "clips": len(t["segments"])} for t in draft["tracks"]],
            "media_bytes": size, "experimental": True, "editable_titles": len(titles),
            "next": ("Restart CapCut to see the project in its list." if running else "Open CapCut: the project is in the list.")
                    + " Titles are plain CapCut text; the styled versions are in the media bin."}


def list_projects() -> list[dict]:
    """Drafts this tool created, newest first, with the studio project each came from."""
    out = []
    for n in list_ours():
        d = drafts_dir() / n
        try:
            origin = json.loads((d / MARKER).read_text(encoding="utf-8"))
        except ValueError:
            origin = {}
        out.append({"name": n, "project": origin.get("project", ""), "modified": int((d / "draft_info.json").stat().st_mtime)})
    return sorted(out, key=lambda x: -x["modified"])


def list_ours() -> list[str]:
    root = drafts_dir()
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / MARKER).exists()) if root.is_dir() else []


def remove(name: str | None = None) -> dict:
    """Delete drafts created by this writer (all of them, or one by name). Never touches other drafts."""
    if capcut_running():
        raise RuntimeError("Close CapCut first.")
    removed = []
    for n in list_ours():
        if name is None or n == name:
            shutil.rmtree(drafts_dir() / n)
            removed.append(n)
    return {"removed": removed}


def inspect(name: str) -> dict:
    """Summary of a draft as it is on disk now (after CapCut opened and saved it, this shows what CapCut kept)."""
    d = drafts_dir() / name
    info = json.loads((d / "draft_info.json").read_text(encoding="utf-8"))
    return {"name": name, "duration_s": info.get("duration", 0) / US, "canvas": info.get("canvas_config"), "version": info.get("version"), "new_version": info.get("new_version"),
            "tracks": [{"type": t.get("type"), "name": t.get("name"), "clips": len(t.get("segments", []))} for t in info.get("tracks", [])],
            "materials": {k: len(v) for k, v in info.get("materials", {}).items() if v}, "ours": (d / MARKER).exists()}


def pull(name: str, apply: bool = False) -> dict:
    """Compare a CapCut project this tool created with the edit it came from, and report what was changed
    in CapCut: clips moved, trimmed, deleted, volume or text changed, new clips added. With apply=True the
    changes are written into the project's edit.json (the previous version is kept next to it)."""
    folder = drafts_dir() / name
    if not (folder / MARKER).is_file():
        raise ValueError("only projects created by this tool can be read back")
    try:
        origin = json.loads((folder / MARKER).read_text(encoding="utf-8"))
        handoff = Path(origin["handoff"])
    except (ValueError, KeyError) as exc:
        raise ValueError("this project was made by an older version and does not record where it came from") from exc
    manifest = json.loads((handoff / "manifest.json").read_text(encoding="utf-8"))
    edit_file = handoff.parent / "edit.json"
    doc = json.loads(edit_file.read_text(encoding="utf-8"))
    info = json.loads((folder / "draft_info.json").read_text(encoding="utf-8"))
    clips = {c["id"]: c for t in doc["tracks"] for c in t["clips"]}
    by_file = {Path(i["file"]).name: i for i in manifest["items"] if i.get("id")}
    known = {Path(i["file"]).name for i in manifest["items"]}        # e.g. the credit overlay: ours, but not a clip of the edit
    paths = {m["id"]: Path(m.get("path", "")).name for kind in ("videos", "audios") for m in info["materials"].get(kind, [])}
    texts = {m["id"]: m for m in info["materials"].get("texts", [])}
    titles = sorted((c for c in clips.values() if c["kind"] == "text"), key=lambda c: c["start"])
    frame = 1 / float(manifest.get("fps", 30))

    seen: set[str] = set()
    changes: list[dict] = []
    foreign: list[dict] = []

    def note(cid: str, field: str, old, new) -> None:
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and abs(old - new) < frame * 0.99:
            return
        if old != new:
            changes.append({"clip": cid, "field": field, "from": old, "to": new})

    for track in info["tracks"]:
        text_n = 0
        for seg in sorted(track.get("segments", []), key=lambda s: s["target_timerange"]["start"]):
            start = round(seg["target_timerange"]["start"] / US, 3)
            length = round(seg["target_timerange"]["duration"] / US, 3)
            if track.get("type") == "text":
                mat = texts.get(seg.get("material_id"), {})
                try:
                    said = json.loads(mat.get("content", "{}")).get("text", "")
                except ValueError:
                    said = ""
                cid = seg.get("tibeb_id") or (titles[text_n]["id"] if text_n < len(titles) else None)   # CapCut may drop our id: fall back to order
                text_n += 1
                if cid in clips and cid not in seen:
                    seen.add(cid)
                    note(cid, "start", clips[cid]["start"], start)
                    note(cid, "length", clips[cid]["length"], length)
                    note(cid, "text", clips[cid].get("text"), said)
                else:
                    foreign.append({"kind": "text", "text": said, "start": start, "length": length})
                continue
            item = by_file.get(paths.get(seg.get("material_id"), ""))
            if not item and paths.get(seg.get("material_id"), "") in known:
                continue
            if not item or item["id"] in seen:
                foreign.append({"kind": track.get("type"), "file": paths.get(seg.get("material_id"), "?"), "start": start, "length": length})
                continue
            cid = item["id"]
            seen.add(cid)
            if cid == "" or cid not in clips:
                continue
            c = clips[cid]
            note(cid, "start", c["start"], start)
            note(cid, "length", min(c["length"], float(item["length"])), length)
            offset = round(seg["source_timerange"]["start"] / US, 3)
            if offset >= frame and c["kind"] != "image":
                note(cid, "in", c.get("in", 0), round(c.get("in", 0) + offset, 3))      # trimmed from the front in CapCut
            if c["kind"] != "image" and "volume" in c:
                note(cid, "volume", c["volume"], round(float(seg.get("volume", 1.0)), 3))
    deleted = sorted(i["id"] for i in manifest["items"] if i.get("id") in clips and i["id"] not in seen
                     and not (clips[i["id"]]["kind"] == "text" and any(t.get("type") == "text" for t in info["tracks"]) and i["id"] in seen))
    deleted = [d for d in deleted if not (clips[d]["kind"] == "text" and d in seen)]
    result = {"project": manifest.get("project"), "draft": name, "changes": changes, "deleted": deleted, "added_in_capcut": foreign,
              "summary": f"{len(changes)} change(s), {len(deleted)} clip(s) removed, {len(foreign)} clip(s) added in CapCut"}
    if apply and (changes or deleted):
        backup = edit_file.with_name(f"edit.before-capcut-{time.strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(edit_file, backup)
        for ch in changes:
            clips[ch["clip"]][ch["field"]] = ch["to"]
        for t in doc["tracks"]:
            t["clips"] = [c for c in t["clips"] if c["id"] not in deleted]
        edit_file.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        result.update({"applied": True, "backup": str(backup)})
        if foreign:
            result["note"] = "Clips added in CapCut are listed but not brought into the edit."
    return result
