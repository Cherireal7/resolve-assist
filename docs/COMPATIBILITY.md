# Compatibility

| Component | Tested | Notes |
|---|---|---|
| Python | 3.10 (CI), 3.15.2 (dev) | Core is stdlib-only |
| macOS | dev machine | sips fallback available |
| Linux | CI | ffmpeg or built-in PNG decoder |
| Resolve Free 21.2.0 (macOS) | **pending probe** | Fill in from `probe-report` |

## Known platform facts (as of 2026-11)

- Resolve 21.1+ Free: external scripting and the built-in MCP server are Studio-only;
  Python scripts are not offered in the Free Workspace → Scripts menu; Lua scripts run.
- Resolve Free loads `.cube` LUTs on any node.

## Probe results

_Add one section per Resolve version: date, product/version, Lua libraries available,
whether `io` works, which color methods exist (`SetCDL`, `SetLUT`, `GetNodeGraph` ...),
and the method-existence control result._
