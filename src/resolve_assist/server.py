"""MCP server (stdio). Thin wrappers over api.py; errors come back as readable text."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from mcp.server.fastmcp import FastMCP

from . import api

mcp = FastMCP(
    "resolve-assist",
    instructions=(
        "Color assistant for DaVinci Resolve Free. Workflow: the user exports a still "
        "(Resolve: right-click viewer → Grab Still → Gallery → Export, PNG preferred) "
        "or gives a video path. Use analyze_frame first, then suggest_balance / match_shots, "
        "render_preview to check the result visually, and make_lut to deliver a .cube. "
        "Live Resolve (Phase 2): if bridge_status says running, use analyze_clip to grab and "
        "measure frames yourself, apply_grade to change a clip (ALWAYS dry run first, show the "
        "plan and a preview, and only call with confirm=true after the user agrees), and "
        "undo_grade to restore. Never claim a change happened unless apply_grade returned applied=true. "
        "Report confidence and warnings honestly. "
        "Recording source footage (OBS): obs_status first; obs_start_recording only when the user asks "
        "to record; obs_stop_recording returns the file and indexes it for import_assets."
    ),
)


def _run(fn: Callable[..., Any], **kwargs: Any) -> str:
    try:
        return json.dumps(fn(**kwargs), indent=1, ensure_ascii=False)
    except Exception as exc:  # surfaced to the AI as a readable error, never a crash
        return json.dumps({"error": type(exc).__name__, "message": str(exc)})


@mcp.tool()
def environment_status() -> str:
    """Show what's available: ffmpeg, output folder, Resolve script/LUT folders, probe report."""
    return _run(api.status)


@mcp.tool()
def analyze_frame(path: str, time_seconds: Optional[float] = None) -> str:
    """Measure exposure, contrast, white balance cast, clipping and saturation of a still
    (PNG best; other formats/video need ffmpeg). time_seconds picks a video frame."""
    return _run(api.analyze, path=path, time_seconds=time_seconds)


@mcp.tool()
def suggest_balance(path: str, time_seconds: Optional[float] = None, fix_exposure: bool = True) -> str:
    """Compute a neutral correction (CDL slope/offset/power/sat) and verify it by re-measuring."""
    return _run(api.balance, path=path, time_seconds=time_seconds, fix_exposure=fix_exposure)


@mcp.tool()
def match_shots(source_path: str, reference_path: str, strength: float = 1.0,
                source_time: Optional[float] = None, reference_time: Optional[float] = None) -> str:
    """CDL that makes the source shot's color/contrast match the reference shot."""
    return _run(api.match, source_path=source_path, reference_path=reference_path, strength=strength,
                source_time=source_time, reference_time=reference_time)


@mcp.tool()
def list_looks() -> str:
    """List the built-in creative looks (use their names with make_lut / render_preview)."""
    return _run(api.looks)


@mcp.tool()
def render_preview(path: str, name: str, look: Optional[str] = None, strength: float = 1.0,
                   slope: str = "1 1 1", offset: str = "0 0 0", power: str = "1 1 1",
                   saturation: float = 1.0, time_seconds: Optional[float] = None) -> str:
    """Render a before/after PNG (left before, right after) into the previews folder.
    The CDL is applied first, then the look. Open the PNG to judge the result."""
    return _run(api.preview, path=path, name=name, look=look, strength=strength, slope=slope,
                offset=offset, power=power, saturation=saturation, time_seconds=time_seconds)


@mcp.tool()
def make_lut(name: str, look: Optional[str] = None, strength: float = 1.0,
             slope: str = "1 1 1", offset: str = "0 0 0", power: str = "1 1 1",
             saturation: float = 1.0, size: int = 33,
             install_to_resolve: bool = False, overwrite: bool = False) -> str:
    """Write a .cube LUT (+ .cc CDL file) to ~/Documents/resolve-assist/LUTs.
    CDL correction first, then the optional look. install_to_resolve copies it into
    Resolve's LUT folder when writable. Sizes: 17, 33, 65."""
    return _run(api.make_lut, name=name, look=look, strength=strength, slope=slope, offset=offset,
                power=power, saturation=saturation, size=size,
                install_to_resolve=install_to_resolve, overwrite=overwrite)


@mcp.tool()
def resolve_probe_report() -> str:
    """Read what the in-Resolve probe found out about this Resolve install's scripting API."""
    return _run(api.probe_report)


@mcp.tool()
def bridge_status() -> str:
    """Is the in-Resolve bridge running? Shows project, timeline and the clip under the playhead."""
    return _run(api.bridge_status)


@mcp.tool()
def list_clips() -> str:
    """List video clips on the current timeline with their target ids ('track:index')."""
    return _run(api.clips)


@mcp.tool()
def analyze_clip(target: str = "current") -> str:
    """Grab the current frame (or the middle of clip 'track:index') from Resolve and analyze it."""
    return _run(api.analyze_clip, target=target)


@mcp.tool()
def apply_grade(target: str = "current", slope: str = "1 1 1", offset: str = "0 0 0", power: str = "1 1 1",
                saturation: float = 1.0, look: Optional[str] = None, strength: float = 1.0, node: int = 1,
                confirm: bool = False) -> str:
    """Apply a CDL correction (and optional look via LUT) to a clip in Resolve.
    confirm=false returns the plan only. Use confirm=true only after the user approved.
    Changes go to a separate 'resolve-assist' grade version; the result is re-measured."""
    return _run(api.apply_grade, target=target, slope=slope, offset=offset, power=power,
                saturation=saturation, look=look, strength=strength, node=node, confirm=confirm)


@mcp.tool()
def stabilize_clip(target: str = "current") -> str:
    """Run Resolve's stabilizer on a clip (goes into the resolve-assist grade version; undo restores)."""
    return _run(api.stabilize, target=target)


@mcp.tool()
def make_music(preset: str = "calm-lofi", seconds: Optional[float] = None) -> str:
    """Create royalty-free background music of any length in the media folder (as long as the timeline
    by default). Presets: calm-lofi, bright-pop, house-groove, cinematic-pulse, ambient, uplift-corporate,
    fast-cut-energy, chill-house, lofi-keys, trap-bounce, synthwave-drive, afro-groove, dembow-heat,
    funk-pop, acoustic-warm, piano-emotional, explainer-pulse, trailer-epic, deep-focus, ethio-tizita,
    ethio-ambassel, ethio-bati-jazz. Then use add_music with the returned file name."""
    return _run(api.make_music, preset=preset, seconds=seconds)


@mcp.tool()
def add_music(file: str) -> str:
    """Place a music file (from ~/Documents/resolve-assist/media) under the video, trimmed to the
    timeline. Works on a copy named '<timeline> (resolve-assist)'; the original stays untouched."""
    return _run(api.add_music, file=file)


@mcp.tool()
def add_title(text: str, at_seconds: float = 0.0, duration: float = 5.0, target: str = "1:1") -> str:
    """Add a Text+ title over a clip on the timeline copy (Fusion, inside the clip: the edit never
    changes), fading in at at_seconds for duration seconds. '|' = new line."""
    return _run(api.add_title, text=text, at_seconds=at_seconds, duration=duration, target=target)


@mcp.tool()
def reset_timeline_copy() -> str:
    """Delete the '(resolve-assist)' timeline copy and reopen the original (never deletes originals)."""
    return _run(api.reset_copy)


@mcp.tool()
def undo_grade(target: str = "current") -> str:
    """Restore the clip's grade version from before resolve-assist changed it."""
    return _run(api.undo_grade, target=target)


@mcp.tool()
def analyze_video(path: str, fps: float = 4.0, top_match_cuts: int = 5) -> str:
    """Find shots, the sharpest frame of each, match-cut candidates (composition/shape/position/
    color rhymes) and write a contact sheet PNG. Needs ffmpeg."""
    return _run(api.analyze_video, path=path, fps=fps, top_match_cuts=top_match_cuts)


@mcp.tool()
def analyze_music(path: str) -> str:
    """Tempo (BPM), beats and downbeats of a music file or a video's soundtrack."""
    return _run(api.analyze_music, path=path)


@mcp.tool()
def beat_edit_plan(videos: list[str], music: str, beats_per_cut: int = 2, order: str = "match",
                   max_seconds: Optional[float] = None) -> str:
    """Plan a music edit: cut on every N beats, pick shot segments around their best frame,
    order shots to create match cuts ('match') or keep source order ('original')."""
    return _run(api.beat_edit_plan, videos=videos, music=music, beats_per_cut=beats_per_cut,
                order=order, max_seconds=max_seconds)


@mcp.tool()
def library_build(force: bool = False) -> str:
    """Generate the royalty-free asset library (SFX, music beds, LUTs, overlays, backgrounds,
    transition clips) in ~/Documents/resolve-assist/library. Existing files are kept unless force."""
    return _run(api.library_build, force=force)


@mcp.tool()
def library_search(query: str = "", category: Optional[str] = None, limit: int = 20) -> str:
    """Search the asset library by words ('9:16' finds vertical versions). Categories: sfx, music, luts,
    overlays, backgrounds, textures, graphics, fonts, footage,
    transitions. Each result says how to use it (e.g. Composite Mode: Screen)."""
    return _run(api.library_search, query=query, category=category, limit=limit)


@mcp.tool()
def import_assets(names: list[str]) -> str:
    """Import library assets (ids from library_search) into Resolve's Media Pool bin
    'resolve-assist library'. Needs the bridge."""
    return _run(api.import_assets, names=names)


@mcp.tool()
def apply_powergrade(file: str, target: str = "current", mode: int = 0) -> str:
    """Apply a downloaded PowerGrade (.drx in library/powergrades) to a clip. Goes into the
    'resolve-assist' grade version (undo_grade restores). mode 0 = ignore keyframes."""
    return _run(api.apply_powergrade, file=file, target=target, mode=mode)


@mcp.tool()
def make_format(format: str = "9x16") -> str:
    """Copy the current timeline into a social format: 9x16 (Reels/TikTok/Shorts), 4x5 (feed),
    1x1, or 16x9. Clips are scaled to fit; the original timeline is untouched."""
    return _run(api.make_format, format=format)


@mcp.tool()
def auto_captions(path: Optional[str] = None, model: str = "base", language: str = "auto",
                  max_chars: int = 32, add_to_resolve: bool = True) -> str:
    """Local speech-to-text captions (whisper.cpp, nothing uploaded). With path: caption that file.
    Without: caption the current Resolve timeline and add the subtitles to a timeline copy.
    model: tiny/base/small/medium (bigger = more accurate, slower). language: auto or 'en','am',..."""
    if path:
        return _run(api.captions_for_file, path=path, model=model, language=language, max_chars=max_chars)
    return _run(api.captions_for_timeline, model=model, language=language, max_chars=max_chars,
                add_to_resolve=add_to_resolve)


@mcp.tool()
def assemble_beat_edit(videos: list[str], music: str, beats_per_cut: int = 2, order: str = "match",
                       max_seconds: Optional[float] = None, sfx_on_cuts: Optional[str] = "whoosh-medium",
                       title: str = "Beat edit") -> str:
    """Analyze footage + music and BUILD the edit in Resolve: a new '(resolve-assist)' timeline cut on
    the beat in match-cut order, music on A1, an SFX from the library on every cut (None = no SFX),
    a marker per cut. Footage already in the Media Pool is reused."""
    return _run(api.assemble_beat_edit, videos=videos, music=music, beats_per_cut=beats_per_cut,
                order=order, max_seconds=max_seconds, sfx_on_cuts=sfx_on_cuts, title=title)


@mcp.tool()
def build_edit(segments: list[dict], title: str = "Edit", music: Optional[str] = None,
               sfx_on_cuts: Optional[str] = None) -> str:
    """Build a new '(resolve-assist)' timeline from segments [{source, source_in, source_out}] in
    seconds (e.g. from beat_edit_plan or your own selection of best moments / match cuts)."""
    return _run(api.build_edit, segments=segments, title=title, music=music, sfx_on_cuts=sfx_on_cuts)


@mcp.tool()
def obs_status() -> str:
    """OBS Studio (recording source footage): connected?, current scene, recording on/off, where
    recordings go. Works when OBS is off too (connected=false with the fix)."""
    return _run(api.obs_status)


@mcp.tool()
def obs_list_scenes() -> str:
    """List OBS scenes in the order of the OBS Scenes dock, and the current one."""
    return _run(api.obs_scenes)


@mcp.tool()
def obs_switch_scene(name: str) -> str:
    """Switch OBS to a scene by name (e.g. 'App screen', 'Talking head', 'Voiceover')."""
    return _run(api.obs_switch_scene, name=name)


@mcp.tool()
def obs_start_recording(scene: Optional[str] = None) -> str:
    """Start recording in OBS (switching to scene first if given). Only when the user asked to record:
    it captures their screen/camera/mic. Files go to ~/Documents/resolve-assist/library/footage/obs."""
    return _run(api.obs_start_recording, scene=scene)


@mcp.tool()
def obs_stop_recording(refresh_library: bool = True) -> str:
    """Stop the OBS recording, wait until the file is finished and return its path. With
    refresh_library the clip is indexed so import_assets can bring it into Resolve."""
    return _run(api.obs_stop_recording, refresh_library=refresh_library)


@mcp.tool()
def doctor() -> str:
    """Check the whole setup (Resolve, bridge version, ffmpeg, whisper, library, Claude connection)
    and return exact fixes. Run this when something doesn't work."""
    return _run(api.doctor)


@mcp.tool()
def new_project(name: str) -> str:
    """Create ~/Documents/resolve-assist/projects/<name>/ with footage, music, stills, exports,
    captions, kit folders and a notes.md checklist."""
    return _run(api.new_project, name=name)


@mcp.tool()
def narrate(project: str, text: str, name: str = "narration", voice: Optional[str] = None, rate: str = "+0%",
            provider: str = "auto") -> str:
    """Script -> narration audio (projects/<project>/voice/<name>.wav) with word timings and cue times
    (prep/<name>.narration.json) for captions and scene timing. Blank lines separate paragraphs (short
    pause); a marker like {map} right before a word records when that word is spoken. provider: 'edge'
    = natural Microsoft voices incl. Amharic (the text is sent to Microsoft; say so to the user), 'say' =
    local system voice, 'auto' = edge when installed. Voices look like en-GB-RyanNeural, am-ET-AmehaNeural."""
    return _run(api.narrate, project=project, text=text, name=name, voice=voice, rate=rate, provider=provider)


@mcp.tool()
def commons_search(query: str, limit: int = 12) -> str:
    """Search Wikimedia Commons for real pictures (paintings, portraits, documents, maps). Each result
    has its licence, author and flags: free (public domain/CC0), attribution, share_alike."""
    return _run(api.commons_search, query=query, limit=limit)


@mcp.tool()
def commons_add(project: str, title: str, name_hint: str = "") -> str:
    """Download a Wikimedia Commons image (title from commons_search or its page URL) into the project
    with licence, author and source recorded in project.json and CREDITS.md. Prefer free results; tell
    the user about attribution or share-alike notes."""
    return _run(api.commons_add, project=project, title=title, name_hint=name_hint)


@mcp.tool()
def project_credit(project: str, file: str, source: str = "", license: str = "", author: str = "") -> str:
    """Record source, licence and author for any third-party file in a project (stock clip, music, map)."""
    return _run(api.project_credit, project=project, file=file, source=source, license=license, author=author)


@mcp.tool()
def project_intake(project: str) -> str:
    """Sort whatever the user dropped into projects/<project>/inbox/ (footage, photos, map images, voice,
    music, references, scripts) into typed folders and refresh project.json: every file with kind,
    duration and dimensions. Read project.json and brief.md instead of probing files again."""
    return _run(api.project_intake, project=project)


@mcp.tool()
def edit_prep(video: str, project: str, min_silence: float = 0.4, padding: float = 0.03, model: str = "base",
              language: str = "auto", render: bool = True) -> str:
    """Prepare a talking-head clip for editing (no Resolve needed): word-by-word transcript, silences
    removed with `padding` seconds kept on each side (0.03 = 30 ms), a tightened video, and the script
    split into short segments. Results go to projects/<project>/prep/. Follow with edit_plan."""
    return _run(api.edit_prep, video=video, project=project, min_silence=min_silence, padding=padding,
                model=model, language=language, render=render)


@mcp.tool()
def edit_plan(project: str, recommendations: Optional[dict] = None) -> str:
    """Create the planning page for the latest edit_prep of a project. recommendations maps a segment id
    to scene type ids, best first, e.g. {"2": ["graph", "line-text"]}. Rule of thumb: stay on the speaker
    ('aroll') when a new idea is announced, show a visual when it is described. The user picks scenes in
    the page and pastes the copied plan back; build only after that."""
    return _run(api.edit_plan, project=project, recommendations=recommendations)


@mcp.tool()
def project_kit(project: str, queries: list[str], per_query: int = 1) -> str:
    """Copy the best library match for each search phrase (e.g. 'whoosh', 'warm light leak 9:16',
    'uplift music') into projects/<project>/kit/. Use this instead of import_assets when the user edits
    in CapCut or any editor without the Resolve bridge: they import that one folder."""
    return _run(api.project_kit, project=project, queries=queries, per_query=per_query)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
