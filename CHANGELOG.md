# Changelog

All notable changes are listed here. Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [Unreleased]

### Fixed
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
