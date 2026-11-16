# Notes for AI agents working on this repo

- Read PROJECT.md first: goals, phases, security model, fallbacks, performance budgets.
- Core (`color/`, `imaging/`, `analyze.py`, `paths.py`, `api.py`) must stay **stdlib-only**. `mcp` is used only in `server.py`.
- Every file read/write goes through `paths.py` (`check_input_media`, `output_path`). Never add a tool that reads arbitrary files or writes outside the output dir.
- Never execute strings received from tools (no `eval`, no Lua `loadstring` of request data in the future bridge).
- Phase 2 bridge ops must be allowlisted, support dry-run, and record previous state for undo.
- Run `.venv/bin/python -m unittest discover -s tests -t tests` before committing. Update CHANGELOG.md and docs/COMPATIBILITY.md when behavior or Resolve support changes.
- Conventional Commits.
