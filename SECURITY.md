# Security policy

resolve-assist runs locally and is driven by an AI client. Text reaching that client
(file names, metadata, web pages) may contain prompt injection, so **every tool input
is treated as untrusted**. The full threat model is in [PROJECT.md §6](PROJECT.md#6-security-model).

## Guarantees (v0.1)

- **Reads** only regular files with a media extension (symlinks are resolved first),
  under a size cap, and returns statistics only, never file contents.
- **Writes** only inside `~/Documents/resolve-assist/` (override with `RESOLVE_ASSIST_OUTPUT`)
  and, when asked, Resolve's LUT folder. Names are sanitized; no overwrite unless requested.
- **Resolve changes only on request:** the probe is read-only. The bridge (Phase 2) changes a clip
  only when `apply_grade` is called with `confirm=true`, and then only inside a separate grade
  version named `resolve-assist`, so your own grade stays untouched and `undo_grade` restores it.
- **Bridge allowlist:** the Lua bridge runs a fixed set of operations. Requests are parsed as plain
  `key<TAB>value` text, validated on both sides, tied to the running session and expire after 60 s.
  No request content is ever executed. LUTs load only from `~/Documents/resolve-assist/LUTs`.
- **Audit trail:** every bridge call is appended to `~/Documents/resolve-assist/bridge/journal.jsonl`.
- No shell commands: ffmpeg/sips are run with argument lists, timeouts and `file:`-only input.
- No network access at runtime. No telemetry.
- The PNG decoder enforces dimension and decompressed-size limits.

## Reporting

This is a personal project. Open a private security advisory on GitHub
(Security → Advisories → Report a vulnerability) rather than a public issue.
