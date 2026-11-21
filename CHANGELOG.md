# Changelog

All notable changes are listed here. Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [Unreleased]

### Added (studio: bigger library, editor choice, launcher)
- Library grows from 79 to 350 assets. New generators: `library/sfx_ui.py` and `sfx_cine.py` (71 more
  SFX: interface, sparkle, comedy, transitions, impacts, drum one-shots, tension, quiet ambience beds),
  `sequencer.py` + 17 sequenced music presets (incl. three Ethiopian-scale ones) next to the 5 pad presets,
  `images_more.py` (mesh/grainy/spotlight backgrounds, paper/halftone/grid/stripe/sunburst textures,
  caption bar, scrims, safe-zone guide, frames, scan lines) and 9x16 versions of every overlay and
  transition clip. Shared helpers in `dsp.py` (biquad, reverb, plucked string).
- Library indexes `graphics/` and `fonts/` (from Motion Studio) and the `user-sfx`, `user-music`,
  `user-footage` folders. `library/index.html`: an offline browser page (search, listen, preview, copy path).
- The editor is optional: `~/.config/studio/config` (`editor=resolve|capcut|none`, or `STUDIO_EDITOR`).
  `doctor` skips Resolve/bridge checks for CapCut; the workspace guide covers both editors.
- `project_kit` (MCP) / `kit` (CLI): copy the best library match per phrase into `projects/<name>/kit/`
  for editors without a bridge. Projects get a `kit/` folder.
- `scripts/studio` + `scripts/install-launcher.sh`: one-word launcher (`studio`, `studio capcut`, `new`,
  `open`, `library`, `find`, `kit`, `motion`, `make`, `fonts`, `doctor`) and a clickable `Studio.app`.
- `edit_prep` / `edit_plan` (MCP), `prep` (CLI), `editprep.py`: talking-head preparation without Resolve:
  word-by-word transcript, silences cut with padding (default 30 ms), tightened clip, script segments,
  and `prep/plan.html` (clip + script, a scene type and notes per segment, "Copy plan").
- `project_intake` (MCP), `intake` (CLI), `studio add`: files dropped into `projects/<name>/inbox/` are
  sorted into footage, stills, maps, refs, voice, music, docs (never overwritten) and indexed in
  `project.json` (kind, duration, dimensions; unchanged files are not measured again). Each project
  gets a `brief.md` with a decisions log. The workspace guide tells the AI to read these first.
- `narrate` (MCP/CLI), `narration.py`: script -> voice audio + word timings + `{cue}` times in the project.
  Providers: `edge` (optional `edge-tts`, natural voices incl. Amharic, text goes to Microsoft) and `say`
  (local system voice, word times from local transcription).
- `commons_search` / `commons_add` (MCP), `commons` (CLI): Wikimedia Commons images with licence, author
  and source recorded; flags for free, attribution and share-alike. `project_credit` + generated `CREDITS.md`.
- `doctor --json` for the Tibeb app.
- 20 tactile SFX (`library/sfx_tactile.py`): soft/mechanical/switch clicks, wood and glass taps, stamp, paper
  slide, page turn, pen scribble, marker stroke, pencil tick, tape, typewriter keys, plucks, wood block,
  tiny bell, soft shutter. Library: 370 assets, 107 SFX.
- `handoff` (MCP/CLI), `handoff.py`: a project's `edit.json` exported as layers into `handoff/`: cut picture
  clips, each text as a transparent .mov (via Motion Studio), audio stems, `.cube` looks, `timeline.otio`,
  `timeline.fcpxml`, `manifest.json` and a README with every clip's start time. Overlapping clips get their
  own lanes. The timeline files have not been opened in an editor yet.
- `peaks` (waveform outline + beats, cached) and `look-curves` for the Tibeb editor.
- `analyze_music` uses the tempo stored for generated library tracks (syncopated presets can read as
  2/3 or half tempo otherwise). `make-music` accepts every preset.

### Added (OBS recording)
- `obs.py`: stdlib obs-websocket v5 client (RFC 6455 framing, SHA-256 challenge auth, clean close)
  with the password read from `~/.config/obs-websocket/password`, never from tool input or output.
- MCP `obs_status`, `obs_list_scenes`, `obs_switch_scene`, `obs_start_recording`, `obs_stop_recording`;
  CLI `obs-status`, `obs-scenes`, `obs-scene`, `obs-record`, `obs-stop`. Stop waits for the finished file
  (also the remuxed .mp4 of MKV recordings) and indexes it so `import_assets` can bring it into Resolve.
- Library indexes `library/footage/obs/` (category `footage`); `refresh_index()` re-scans only the user
  folders without regenerating assets. `doctor` reports OBS (informational).
- docs/OBS.md: profile, scenes, permissions, usage. Tests against a fake obs-websocket server.

### Added (pipeline)
- Library indexes `library/motion/` (Motion Studio renders, .mov = transparent) and
  `library/ai-generated/` (Higgsfield) so they can be searched and imported into Resolve.
- Workspace guide: full Higgsfield → Motion Studio → Resolve pipeline and credit rules.

### Fixed (first run on real footage, 2026-11-20)
- Beat plans no longer repeat one moment: shots are split into beat-length moments with their own
  fingerprints; nothing repeats until every moment was used; continuous footage is not called a cut.
- Hardware video decoding (`-hwaccel auto`): 4K HEVC phone clips sample 7x faster (26 s → 3.9 s);
  thumbnails were downscaled twice (56×100 instead of 112×200).
- Video probe reports the displayed size and orientation (phones store portrait video sideways + rotation).
- Captions: quiet phone audio is high-passed and level-normalized before transcription; a clear note
  when no speech is found. Library now builds transition clips (79 assets total).
- Test off-switch `RESOLVE_ASSIST_FFMPEG=none` for the fallback-decoder tests.

### Added (Phase 5: assembly + workspace)
- `build_edit` / `assemble_beat_edit`: build a NEW '(resolve-assist)' timeline from a plan: segments
  frame-accurate from the Media Pool (reused by file path), music on A1, a library SFX on every cut
  (A2, lead-in 0.4 s), a marker per cut. Only resolve-assist folders may be imported (protocol 9).
- `doctor`: checks Resolve, bridge version, ffmpeg, whisper, model, library, Claude connection, disk.
- Workspace guide (`~/Documents/resolve-assist/CLAUDE.md`) and `new_project` folder template.
- Bridge stores resolved folder paths (fixes /var vs /private/var mismatch found by tests).

### Added (social formats & captions)
- `make_format`: copy the timeline into 9x16 / 4x5 / 1x1 / 16x9 with clips scaled to fit (bridge protocol 8).
- `auto_captions`: local whisper.cpp transcription → short social-style SRT; for a file or the whole
  timeline (each clip's used source range, shifted to timeline time) and import onto a timeline copy.
- Clip info now includes the source file path and source offset.

### Added (asset library)
- `library_build`: royalty-free assets generated locally into ~/Documents/resolve-assist/library:
  16 SFX (whooshes, risers, impacts, hits, pops, glitch, shutter, ding, typing), 5 music beds
  (incl. house and cinematic), 20 LUTs (10 looks × 100/50%), 17 overlays (light leaks, bokeh,
  vignettes, grain, dust, letterbox, lower-third panel), 12 backgrounds (16:9 + 9:16), and with ffmpeg
  transition clips (flashes, light-leak sweeps, film burn, glitch) + animated grain.
- manifest.json with tags/usage/license, README with import steps and free sources.
- `library_search`, `import_assets` (into a Media Pool bin), `apply_powergrade` (.drx). Bridge protocol 7.
- 4 new looks: golden-hour, vintage-fade, moody-teal, pastel-dream. PNG encoder writes RGBA.

### Added (Phase 4: analysis engine)
- Visual fingerprints (layout grid, edge orientation, dominant colors, brightness centroid, sharpness).
- Shot detection with an adaptive per-shot threshold; best (sharpest) frame per shot; contact sheet PNG.
- Match-cut finder: ranks end→start shot pairs by composition, shape, position and color, with reasons.
- Beat tracking (stdlib): tempo 60–180 BPM with octave check, beat grid, downbeats. Verified on
  generated tracks: 84→83.65, 112→112.2, 60→60.09 BPM.
- Beat-synced edit plan: cuts every N beats from the first downbeat, segments centered on best frames,
  shots ordered for match cuts. MCP: `analyze_video`, `analyze_music`, `beat_edit_plan`; CLI: `video`,
  `beats`, `beat-plan`.

### Added (Phase 2: live Resolve)
- Lua bridge (`bridge.lua`) over a shared folder with `fu:OpenFile`: works in the sandboxed App Store build.
- Allowlisted ops: status, list_clips, clip_info, goto_clip, grab_frame, apply_cdl, apply_lut, undo, stop.
- `apply_grade` (dry run unless confirmed; separate `resolve-assist` grade version; re-measures the result),
  `undo_grade`, `analyze_clip`, `list_clips`, `bridge_status` as MCP tools and CLI commands.
- Session ids, request expiry, heartbeat, audit journal, Scripts-menu entry on first run.
- End-to-end tests running the real bridge in a Lua runtime against a fake Resolve.

- Bridge protocol 2: `stabilize` op; LUTs are copied by Lua into Resolve's own LUT folders when
  Resolve refuses to load them from Documents (live finding on Free 21.2 App Store).
- Bridge protocol 3: `duplicate_timeline`, `add_music`, `add_title`. Edits only happen on a copy
  named "<timeline> (resolve-assist)"; music only from ~/Documents/resolve-assist/media.
- Protocol 5: titles are composited inside the clip with Fusion (Text+ → Merge → MediaOut, timed fade),
  never an insert edit; `reset_copy` deletes only resolve-assist timeline copies.
- Royalty-free preset music generator (`make_music`: calm-lofi, bright-pop, ambient), stdlib only.
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
