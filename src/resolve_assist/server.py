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
        "Report confidence and warnings honestly."
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
def undo_grade(target: str = "current") -> str:
    """Restore the clip's grade version from before resolve-assist changed it."""
    return _run(api.undo_grade, target=target)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
