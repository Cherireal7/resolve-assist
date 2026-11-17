"""Client for the in-Resolve Lua bridge (Phase 2).

Transport: files in a shared folder (default ~/Documents/resolve-assist/bridge),
because the sandboxed App Store Resolve has no sockets/io, only fu:OpenFile.

  request.txt   written by us (atomic rename), "key<TAB>value" lines
  response.txt  written by Lua, one JSON line, matched by seq
  status.txt    Lua heartbeat (session id, time), refreshed every second
  journal.jsonl audit trail of every call
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path
from typing import Any

from .paths import output_dir

PROTOCOL = 2
HEARTBEAT_STALE_S = 10.0
ALLOWED_OPS = {"status", "list_clips", "clip_info", "goto_clip", "grab_frame",
               "apply_cdl", "apply_lut", "stabilize", "undo", "stop"}
ALLOWED_PARAMS = {"target", "node", "slope", "offset", "power", "saturation", "lut", "version"}
_VALUE_RE = re.compile(r"^[^\t\r\n\x00]{0,512}$")
_TARGET_RE = re.compile(r"^(current|\d{1,3}:\d{1,4})$")


class BridgeError(RuntimeError):
    pass


class BridgeOffline(BridgeError):
    pass


def bridge_dir() -> Path:
    return output_dir() / "bridge"


def lut_dir() -> Path:
    return output_dir() / "LUTs"


def _lua_string(value: str) -> str:
    if any(c in value for c in "\r\n\x00"):
        raise ValueError("path contains a control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def loader_code(bridge_file: Path) -> str:
    """The snippet the user pastes into the Console (and the Scripts-menu entry)."""
    return (
        "-- resolve-assist: start the bridge\n"
        f"local p = {_lua_string(str(bridge_file))}\n"
        "local f = (fusion or fu):OpenFile(p, 1)\n"
        "assert(f, 'resolve-assist: bridge not installed. Run: resolve-assist bridge-install')\n"
        "local t = {}\n"
        "while true do local l = f:ReadLine(); if l == nil then break end; t[#t + 1] = l end\n"
        "f:Close()\n"
        "assert(loadstring(table.concat(t, '\\n'), 'resolve-assist bridge'))()\n"
    )


def install(copy_to_clipboard: bool = True) -> dict:
    root = bridge_dir()
    (root / "frames").mkdir(parents=True, exist_ok=True)
    lut_dir().mkdir(parents=True, exist_ok=True)
    source = resources.files("resolve_assist").joinpath("lua/bridge.lua").read_text(encoding="utf-8")
    rendered = (source.replace("{{BRIDGE_DIR}}", _lua_string(str(root)))
                      .replace("{{LUT_DIR}}", _lua_string(str(lut_dir()))))
    bridge_file = root / "bridge.lua"
    bridge_file.write_text(rendered, encoding="utf-8")
    loader = loader_code(bridge_file)
    (root / "loader.lua").write_text(loader, encoding="utf-8")
    copied = False
    if copy_to_clipboard and sys.platform == "darwin" and shutil.which("pbcopy"):
        copied = subprocess.run(["pbcopy"], input=loader.encode(), check=False).returncode == 0
    return {
        "bridge": str(bridge_file),
        "loader_copied_to_clipboard": copied,
        "loader": loader,
        "next": "Resolve: Workspace → Console → click the input line → paste (⌘V) → Enter. "
                "After the first run it is also in Workspace → Scripts.",
    }


def _first_line(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.readline(1024 * 1024).strip() or None
    except OSError:
        return None


class Bridge:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or bridge_dir()
        self._last_seq = 0

    # -------------------------------------------------------------- status
    def status(self) -> dict:
        # Lua rewrites status.txt every second (truncate + write), so a read can land
        # in the middle and see an empty/partial file. Retry briefly before concluding.
        st = None
        for _ in range(10):
            line = _first_line(self.root / "status.txt")
            if line:
                try:
                    st = json.loads(line)
                    if st:
                        break
                except json.JSONDecodeError:
                    pass
            if not (self.root / "status.txt").exists():
                break
            time.sleep(0.03)
        if not st:
            return {"running": False, "hint": "Start the bridge in Resolve (resolve-assist bridge-install)."}
        age = time.time() - float(st.get("time") or 0)
        st["age_seconds"] = round(age, 1)
        st["running"] = st.get("state") == "running" and age < HEARTBEAT_STALE_S
        if not st["running"]:
            st["hint"] = "Bridge not running. In Resolve: Workspace → Scripts → resolve-assist Bridge, " \
                         "or paste the loader into the Console."
        return st

    # -------------------------------------------------------------- calls
    def send(self, op: str, **params: Any) -> str:
        if op not in ALLOWED_OPS:
            raise BridgeError(f"operation not allowed: {op}")
        lines: list[tuple[str, str]] = []
        for key, value in params.items():
            if value is None:
                continue
            if key not in ALLOWED_PARAMS:
                raise BridgeError(f"parameter not allowed: {key}")
            text = str(value)
            if not _VALUE_RE.match(text):
                raise BridgeError(f"invalid value for {key}")
            if key == "target" and not _TARGET_RE.match(text):
                raise BridgeError("target must be 'current' or 'track:index' like '1:2'")
            lines.append((key, text))
        st = self.status()
        if not st["running"]:
            raise BridgeOffline(st.get("hint", "bridge not running"))
        seq = max(int(time.time() * 1000), self._last_seq + 1)
        self._last_seq = seq
        header = [("seq", str(seq)), ("session", str(st["session"])), ("ts", str(int(time.time()))), ("op", op)]
        body = "".join(f"{k}\t{v}\n" for k, v in header + lines)
        tmp = self.root / f".request-{seq}.tmp"
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.root / "request.txt")
        return str(seq)

    def wait(self, seq: str, timeout: float = 20.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = _first_line(self.root / "response.txt")
            if line:
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    resp = None  # Lua is mid-write
                if resp and str(resp.get("seq")) == seq:
                    return resp
            time.sleep(0.05)
        raise BridgeError(f"no answer from Resolve within {timeout:.0f}s. Is a dialog open in Resolve? "
                          "Close it and retry.")

    def call(self, op: str, timeout: float = 20.0, **params: Any) -> Any:
        seq = self.send(op, **params)
        resp = self.wait(seq, timeout)
        self._journal(op, params, resp)
        if not resp.get("ok"):
            raise BridgeError(str(resp.get("error") or "unknown error"))
        return resp.get("result")

    def _journal(self, op: str, params: dict, resp: dict) -> None:
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "op": op, "params": params,
                 "ok": resp.get("ok"), "error": resp.get("error")}
        try:
            with (self.root / "journal.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------- undo memory
    def remember_previous(self, clip: dict, previous_version: str | None) -> None:
        if not clip or not previous_version or previous_version == "resolve-assist":
            return
        data = self._undo_data()
        data[_clip_key(clip)] = previous_version
        (self.root / "undo.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def previous_version(self, clip: dict) -> str | None:
        return self._undo_data().get(_clip_key(clip))

    def _undo_data(self) -> dict:
        try:
            return json.loads((self.root / "undo.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}


def _clip_key(clip: dict) -> str:
    return f"{clip.get('name')}@{clip.get('start')}"
