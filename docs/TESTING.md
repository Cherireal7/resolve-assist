# Testing

## Automated

```bash
.venv/bin/python -m unittest discover -s tests -t tests
```

Covers: CDL/look math, LUT round-trip and accuracy, PNG decoder (all filters, 8/16-bit,
bomb limits), path security (traversal, symlinks, URLs, overwrite), end-to-end
analyze → balance → LUT → preview, sips decode (macOS), MCP tool errors.

## Performance (measured 2026-11-16, Apple Silicon, Python 3.15.2)

| Operation | Result | Budget |
|---|---|---|
| 33³ LUT with a look | 0.10 s | < 0.5 s |
| `analyze` 4K PNG via sips (incl. startup) | 0.44 s | < 1.5 s |
| `analyze` 4K TIFF via sips | 0.35 s | < 1.5 s |
| Built-in PNG decoder, real 4K 8-bit PNG | 2.9 s | fallback only |

## Manual checklist (Resolve)

Log each run in the table below.

1. `resolve-assist install-probe`, then open Resolve with a project and a clip under the playhead.
2. Workspace → Scripts → **resolve-assist Probe**. Check the console output.
3. `resolve-assist probe-report`: report found, version correct.
4. Grab a still → export PNG → `resolve-assist balance still.png`.
5. `resolve-assist lut test-balance --slope "<values>"` → load the LUT on a node → visual check.
6. Compare with `resolve-assist preview`: the preview and Resolve should look the same.

| Date | Resolve | OS | Steps passed | Notes |
|---|---|---|---|---|
| | Free 21.2.0 | macOS | | pending first run |
