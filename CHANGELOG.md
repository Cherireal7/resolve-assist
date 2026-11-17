# Changelog

All notable changes are listed here. Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [Unreleased]

### Added (Phase 2: live Resolve)
- Lua bridge (`bridge.lua`) over a shared folder with `fu:OpenFile`: works in the sandboxed App Store build.
- Allowlisted ops: status, list_clips, clip_info, goto_clip, grab_frame, apply_cdl, apply_lut, undo, stop.
- `apply_grade` (dry run unless confirmed; separate `resolve-assist` grade version; re-measures the result),
  `undo_grade`, `analyze_clip`, `list_clips`, `bridge_status` as MCP tools and CLI commands.
- Session ids, request expiry, heartbeat, audit journal, Scripts-menu entry on first run.
- End-to-end tests running the real bridge in a Lua runtime against a fake Resolve.

- Bridge protocol 2: `stabilize` op; LUTs are copied by Lua into Resolve's own LUT folders when
  Resolve refuses to load them from Documents (live finding on Free 21.2 App Store).
- Fallback: if no LUT folder works, the look is approximated as CDL and folded into the correction.

### Fixed
- Client retries reading the heartbeat file while Lua is rewriting it (found by the end-to-end test).

### Fixed
- Analysis ignores letterbox/pillarbox black bars (found on real footage: vertical phone video in a 16:9 timeline had 68% bars and skewed every measurement).
- A single number passed as text (e.g. `--offset -0.01`) now applies to all channels.
- Probe now works with the sandboxed Mac App Store build of Resolve: reports to ~/Movies or ~/Pictures, records `sandboxed`, Scripts/LUT paths.
- `sips` no longer upscales small stills; original size is reported.

### Added
- Test that runs probe.lua in a Lua runtime (lupa) against a fake Resolve, including the sandboxed and no-`io` cases.

## [0.1.0] - 2026-11-16

### Added
- Phase 0: read-only Lua probe for Resolve (`install-probe`, `probe-report`) with io → bmd.writefile → console fallbacks.
- Phase 1: frame analysis (exposure, contrast, cast, clipping, saturation, warnings, confidence).
- Auto balance and shot matching as ASC-CDL, verified by re-measuring.
- Six starter looks with strength control; before/after preview PNGs.
- `.cube` LUT writer/reader (17/33/65) and `.cc` CDL export; optional install to Resolve's LUT folder.
- Decoder chain: ffmpeg → macOS sips → built-in PNG decoder.
- MCP server (8 tools) and CLI.
- Tests (color math, LUT I/O, PNG decoder, path security, end-to-end) and CI.
