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


def build_draft(handoff: Path, name: str, log=lambda m: None) -> dict:
    """Create a new CapCut draft named `name` from a hand-off folder (manifest.json + media)."""
    from .analysis.video import probe
    if capcut_running():
        raise RuntimeError("Close CapCut first: it rewrites its project list when it quits.")
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
    (folder / MARKER).write_text("Created by resolve-assist (Tibeb). Safe to delete with: resolve-assist capcut-remove\n", encoding="utf-8")
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

    by_track: dict[str, list[dict]] = {}
    for it in manifest["items"]:
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
                pr = {}
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
            "media_bytes": size, "experimental": True,
            "next": "Open CapCut: the project should appear in the list. Open it and check every clip. If CapCut rejects it, run: resolve-assist capcut-remove"}


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
