"""OBS Studio remote control over obs-websocket v5 (built into OBS 28+). Stdlib only.

A minimal RFC 6455 client (text frames, client masking, fragmentation, ping/pong, close codes) and
the obs-websocket flow: Hello → Identify (SHA-256 challenge) → Identified → Request/RequestResponse.

Security: the password is read from a local file (never from tool input) and is never returned.
Host and port come from the environment, not from tool calls; the default is this Mac only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import stat
import struct
import time
import uuid
from pathlib import Path
from typing import Any

from .paths import output_dir

DEFAULT_PORT = 4455
SUBPROTOCOL = "obswebsocket.json"
RPC_VERSION = 1
MAX_MESSAGE = 16 * 1024 * 1024
FOOTAGE_SUBDIR = "footage/obs"  # inside the library: indexed by library_build, importable with import_assets
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_REMUXABLE = {".mkv", ".flv", ".ts", ".m3u8"}  # OBS "auto remux" turns these into .mp4 after stopping


class OBSError(RuntimeError):
    pass


class OBSOffline(OBSError):
    """OBS is not running, or its WebSocket server is off/unreachable."""


class _Closed(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"{code} {reason}".strip())
        self.code, self.reason = code, reason


# --------------------------------------------------------------------------- configuration

def host() -> str:
    return os.environ.get("RESOLVE_ASSIST_OBS_HOST", "127.0.0.1")


def port() -> int:
    raw = os.environ.get("RESOLVE_ASSIST_OBS_PORT", str(DEFAULT_PORT))
    try:
        value = int(raw)
    except ValueError as exc:
        raise OBSError(f"RESOLVE_ASSIST_OBS_PORT must be a number, not {raw!r}") from exc
    if not 1 <= value <= 65535:
        raise OBSError("RESOLVE_ASSIST_OBS_PORT must be 1..65535")
    return value


def password_file() -> Path:
    return Path(os.environ.get("RESOLVE_ASSIST_OBS_PASSWORD_FILE", "~/.config/obs-websocket/password")).expanduser()


def read_password() -> str | None:
    """The WebSocket password, or None when the file doesn't exist (OBS may run without auth)."""
    p = password_file()
    if not p.is_file():
        return None
    if p.stat().st_size > 4096:
        raise OBSError(f"{p} is unexpectedly large; it should hold only the OBS WebSocket password")
    return p.read_text(encoding="utf-8").strip() or None


def _password_warnings() -> list[str]:
    p = password_file()
    if p.is_file() and p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return [f"{p} is readable by other users; run: chmod 600 '{p}'"]
    return []


def footage_dir() -> Path:
    """Where OBS should record so clips land in the resolve-assist library."""
    return output_dir() / "library" / FOOTAGE_SUBDIR


def _offline_message() -> str:
    return (f"OBS is not reachable at {host()}:{port()}. Start OBS, then check Tools → WebSocket Server "
            f"Settings: 'Enable WebSocket server' on, port {port()}, authentication on.")


def auth_response(password: str, salt: str, challenge: str) -> str:
    """obs-websocket v5: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode("utf-8")).digest()).decode("ascii")


# --------------------------------------------------------------------------- WebSocket (RFC 6455, client)

def _mask(data: bytes, key: bytes) -> bytes:
    if not data:
        return b""
    n = len(data)
    pad = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(pad, "big")).to_bytes(n, "big")


class _WebSocket:
    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self.sock = sock
        self._buf = bytearray(leftover)
        self._close_sent = False

    @classmethod
    def connect(cls, h: str, p: int, timeout: float) -> "_WebSocket":
        sock = socket.create_connection((h, p), timeout=timeout)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            sock.sendall((f"GET / HTTP/1.1\r\nHost: {h}:{p}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                          f"Sec-WebSocket-Protocol: {SUBPROTOCOL}\r\n\r\n").encode("ascii"))
            raw = bytearray()
            while b"\r\n\r\n" not in raw:
                chunk = sock.recv(4096)
                if not chunk:
                    raise OBSOffline("the WebSocket handshake was cut off (is something else using the port?)")
                raw += chunk
                if len(raw) > 16384:
                    raise OBSError("WebSocket handshake response too large")
            head, _, rest = bytes(raw).partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
                raise OBSOffline(f"port {p} answered, but not as obs-websocket ({lines[0][:80]})")
            headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
            expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
            if headers.get("sec-websocket-accept") != expected:
                raise OBSError("WebSocket handshake failed (bad Sec-WebSocket-Accept)")
            proto = headers.get("sec-websocket-protocol")
            if proto and proto != SUBPROTOCOL:
                raise OBSError(f"OBS chose the unsupported subprotocol {proto!r}")
            return cls(sock, rest)
        except BaseException:
            sock.close()
            raise

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise _Closed(1006, "connection lost")
            self._buf += chunk
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        n = len(payload)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", n)
        key = os.urandom(4)  # clients must mask every frame
        self.sock.sendall(bytes(header) + key + _mask(payload, key))

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        parts: list[bytes] = []
        total = 0
        while True:
            b0, b1 = self._read(2)
            fin, opcode, n = bool(b0 & 0x80), b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            if n > MAX_MESSAGE:
                raise OBSError("message from OBS exceeds the size limit")
            key = self._read(4) if b1 & 0x80 else b""
            data = self._read(n)
            if key:
                data = _mask(data, key)
            if opcode == 0x9:  # ping
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1005
                if not self._close_sent:
                    try:
                        self._send_frame(0x8, data[:2])
                        self._close_sent = True
                    except OSError:
                        pass
                raise _Closed(code, data[2:].decode("utf-8", "replace"))
            if opcode in (0x1, 0x2):
                parts, total = [], 0
            elif opcode != 0x0:
                raise OBSError(f"unexpected WebSocket opcode {opcode}")
            parts.append(data)
            total += len(data)
            if total > MAX_MESSAGE:
                raise OBSError("message from OBS exceeds the size limit")
            if fin:
                return b"".join(parts).decode("utf-8")

    def close(self) -> None:
        """Clean close handshake: send close, wait briefly for the server's close reply."""
        try:
            if not self._close_sent:
                self._send_frame(0x8, struct.pack("!H", 1000))
                self._close_sent = True
                self.sock.settimeout(1.0)
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    self.recv_text()  # discard late events until the close reply arrives
        except (_Closed, OSError, OBSError, ValueError):
            pass
        finally:
            try:
                self.sock.close()
            except OSError:
                pass


# --------------------------------------------------------------------------- obs-websocket client

def _close_message(code: int, reason: str) -> str:
    if code == 4009:
        return (f"OBS rejected the password. Put the password from OBS (Tools → WebSocket Server Settings → "
                f"Show Connect Info) into {password_file()} (chmod 600).")
    if code == 4010:
        return "this OBS speaks an unsupported obs-websocket RPC version (needs OBS 28 or newer)"
    if code == 1006:
        return "OBS closed the connection (did OBS quit?)"
    return f"OBS closed the connection (code {code}{': ' + reason if reason else ''})"


class OBSClient:
    """One identified session. Use as a context manager: `with OBSClient().connect() as obs: ...`."""

    def __init__(self, host_: str | None = None, port_: int | None = None, password: str | None = None,
                 timeout: float = 5.0) -> None:
        self.host = host_ or host()
        self.port = port_ or port()
        self._password = password
        self.timeout = timeout
        self.ws: _WebSocket | None = None
        self.info: dict[str, Any] = {}

    def __enter__(self) -> "OBSClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.ws:
            self.ws.close()
            self.ws = None

    def _send(self, op: int, d: dict) -> None:
        assert self.ws is not None
        self.ws.send_text(json.dumps({"op": op, "d": d}))

    def _recv(self) -> dict:
        assert self.ws is not None
        try:
            msg = json.loads(self.ws.recv_text())
        except socket.timeout as exc:
            raise OBSError("OBS did not answer in time") from exc
        except _Closed as exc:
            self.close()
            raise OBSError(_close_message(exc.code, exc.reason)) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OBSError(f"OBS sent an unreadable message: {exc}") from exc
        if not isinstance(msg, dict) or not isinstance(msg.get("d"), dict):
            raise OBSError("OBS sent a message in an unknown format")
        return msg

    def connect(self) -> "OBSClient":
        try:
            self.ws = _WebSocket.connect(self.host, self.port, self.timeout)
        except (ConnectionRefusedError, socket.timeout) as exc:
            raise OBSOffline(_offline_message()) from exc
        except OSError as exc:
            raise OBSOffline(f"{_offline_message()} ({exc})") from exc
        try:
            hello = self._recv()
            if hello.get("op") != 0:
                raise OBSError("OBS did not send Hello; is this really obs-websocket v5?")
            d = hello["d"]
            identify: dict[str, Any] = {"rpcVersion": RPC_VERSION, "eventSubscriptions": 0}
            auth = d.get("authentication")
            if auth:
                pw = self._password if self._password is not None else read_password()
                if not pw:
                    raise OBSError(f"OBS asks for a password, but {password_file()} is missing or empty. "
                                   "Copy it from OBS: Tools → WebSocket Server Settings → Show Connect Info.")
                identify["authentication"] = auth_response(pw, str(auth.get("salt", "")), str(auth.get("challenge", "")))
            self._send(1, identify)
            identified = self._recv()
            if identified.get("op") != 2:
                raise OBSError("OBS did not confirm the session (Identified)")
            self.info = {"obs_version": d.get("obsStudioVersion"),
                         "websocket_version": d.get("obsWebSocketVersion"),
                         "rpc_version": identified["d"].get("negotiatedRpcVersion"),
                         "authenticated": bool(auth)}
            return self
        except BaseException:
            self.close()
            raise

    def request(self, request_type: str, data: dict | None = None) -> dict:
        if self.ws is None:
            raise OBSError("not connected to OBS")
        rid = uuid.uuid4().hex
        d: dict[str, Any] = {"requestType": request_type, "requestId": rid}
        if data:
            d["requestData"] = data
        self._send(6, d)
        while True:
            msg = self._recv()
            if msg.get("op") != 7 or msg["d"].get("requestId") != rid:
                continue  # events or unrelated messages
            status = msg["d"].get("requestStatus") or {}
            if not status.get("result"):
                comment = status.get("comment") or "no details"
                raise OBSError(f"OBS refused {request_type} (code {status.get('code')}): {comment}")
            return msg["d"].get("responseData") or {}


def connect(timeout: float = 5.0) -> OBSClient:
    return OBSClient(timeout=timeout).connect()


# --------------------------------------------------------------------------- features

def _scene_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > 256 or any(ord(c) < 32 for c in name):
        raise ValueError("give a scene name (as listed by obs_list_scenes)")
    return name


def _current_scene(c: OBSClient) -> str | None:
    d = c.request("GetCurrentProgramScene")
    return d.get("sceneName") or d.get("currentProgramSceneName")


def _scene_names(c: OBSClient) -> list[str]:
    scenes = c.request("GetSceneList").get("scenes") or []
    # obs-websocket lists scenes bottom-up (index 0 = last in the OBS Scenes dock): show the dock's order
    scenes = sorted(scenes, key=lambda s: -int(s.get("sceneIndex", 0)))
    return [s.get("sceneName") for s in scenes if s.get("sceneName")]


def _switch(c: OBSClient, name: str) -> str:
    names = _scene_names(c)
    if name not in names:
        raise OBSError(f"no scene named {name!r} in OBS. Scenes: {', '.join(names) or 'none'}")
    c.request("SetCurrentProgramScene", {"sceneName": name})
    return _current_scene(c) or name


def _in_library(path: Path) -> bool:
    try:
        return path.resolve() == footage_dir().resolve()
    except OSError:
        return False


def status() -> dict:
    """Connected? Current scene, recording state, where recordings go. Never raises for 'OBS is off'."""
    base = {"host": f"{host()}:{port()}", "password_file": str(password_file()),
            "password_file_exists": password_file().is_file()}
    try:
        with connect() as c:
            scene = _current_scene(c)
            rec = c.request("GetRecordStatus")
            rec_dir = c.request("GetRecordDirectory").get("recordDirectory") or ""
            profile = c.request("GetProfileList").get("currentProfileName")
            collection = c.request("GetSceneCollectionList").get("currentSceneCollectionName")
            info = dict(c.info)
    except OBSError as exc:
        return {"connected": False, "message": str(exc), **base}
    warnings = _password_warnings()
    in_lib = bool(rec_dir) and _in_library(Path(rec_dir))
    if not in_lib:
        warnings.append(f"OBS records to {rec_dir or '?'}, not {footage_dir()}: clips won't be indexed in the "
                        "library (OBS → Settings → Output → Recording Path)")
    return {"connected": True, **info, "profile": profile, "scene_collection": collection,
            "current_scene": scene, "recording": bool(rec.get("outputActive")),
            "recording_paused": bool(rec.get("outputPaused")), "recording_timecode": rec.get("outputTimecode"),
            "record_directory": rec_dir, "records_into_library": in_lib, "warnings": warnings, **base}


def list_scenes() -> dict:
    with connect() as c:
        return {"current_scene": _current_scene(c), "scenes": _scene_names(c)}


def switch_scene(name: str) -> dict:
    name = _scene_name(name)
    with connect() as c:
        return {"current_scene": _switch(c, name)}


def start_recording(scene: str | None = None, confirm_seconds: float = 5.0) -> dict:
    """Start recording (optionally switching scene first) and confirm OBS really started."""
    if scene is not None:
        scene = _scene_name(scene)
    with connect() as c:
        if c.request("GetRecordStatus").get("outputActive"):
            raise OBSError("OBS is already recording; stop it first (obs_stop_recording)")
        current = _switch(c, scene) if scene else _current_scene(c)
        c.request("StartRecord")
        deadline = time.monotonic() + confirm_seconds
        active = False
        while not active and time.monotonic() < deadline:
            active = bool(c.request("GetRecordStatus").get("outputActive"))
            if not active:
                time.sleep(0.2)
        if not active:
            raise OBSError(
                f"OBS accepted the start but is not recording after {confirm_seconds:g} s. Usually macOS is "
                "showing a permission prompt (Documents folder, Screen Recording, Camera or Microphone): once it "
                "is answered the recording may start by itself, so check obs_status before starting again. "
                "Otherwise look at the OBS window for the error (e.g. a full disk).")
        rec_dir = c.request("GetRecordDirectory").get("recordDirectory") or ""
    return {"recording": True, "scene": current, "record_directory": rec_dir,
            "records_into_library": bool(rec_dir) and _in_library(Path(rec_dir)),
            "next": "Stop with obs_stop_recording (CLI: resolve-assist obs-stop)."}


def _stable_file(path: Path, deadline: float) -> bool:
    """True once the file exists and its size stopped changing (OBS finished writing / remuxing)."""
    last = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(0.5)
    return False


def _final_file(output: str, wait_seconds: float) -> tuple[Path, list[str]]:
    """The finished recording. MKV/FLV/TS recordings are remuxed to .mp4 by OBS (if enabled): prefer that."""
    p = Path(output)
    deadline = time.monotonic() + wait_seconds
    notes: list[str] = []
    if p.suffix.lower() in _REMUXABLE:
        mp4 = p.with_suffix(".mp4")
        while time.monotonic() < deadline and not mp4.exists():
            time.sleep(0.25)
        if mp4.exists() and _stable_file(mp4, deadline):
            return mp4, notes
        notes.append(f"no remuxed .mp4 appeared; Resolve may not read {p.suffix} well. Turn on OBS → Settings → "
                     "Advanced → 'Automatically remux to mp4', or record as Hybrid MP4.")
    if not _stable_file(p, deadline):
        notes.append("the file was still changing or missing when the wait ended; check it before importing")
    return p, notes


def stop_recording(refresh_library: bool = True, wait_seconds: float = 30.0) -> dict:
    """Stop recording, wait until the file is finished, and (optionally) index it in the library."""
    with connect() as c:
        before = c.request("GetRecordStatus")
        if not before.get("outputActive"):
            raise OBSError("OBS is not recording")
        output = c.request("StopRecord").get("outputPath") or ""
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and c.request("GetRecordStatus").get("outputActive"):
            time.sleep(0.2)
    if not output:
        raise OBSError("OBS stopped but did not report the file path; look in the recording folder")
    path, notes = _final_file(output, wait_seconds)
    res: dict[str, Any] = {"stopped": True, "file": str(path),
                           "seconds": round(float(before.get("outputDuration") or 0) / 1000, 1)}
    if path.is_file():
        res["size_mb"] = round(path.stat().st_size / 1e6, 1)
    lib = (output_dir() / "library").resolve()
    try:
        rel = str(path.resolve().relative_to(lib))
    except (ValueError, OSError):
        rel = None
    if rel is None:
        notes.append(f"recorded outside the library ({footage_dir()}), so it is not indexed. Set OBS → Settings "
                     "→ Output → Recording Path to that folder.")
    else:
        res["library_file"] = rel
        if refresh_library:
            from .library.build import load_manifest, refresh_index
            summary = refresh_index()
            indexed = any(it.get("file") == rel for it in load_manifest().get("items", []))
            res["library"] = {"indexed": indexed, "total": summary["total"]}
            res["next"] = f"import_assets(['{rel}']) puts it into Resolve's Media Pool (bridge running)."
        else:
            res["next"] = f"Run library_build, then import_assets(['{rel}'])."
    if notes:
        res["notes"] = notes
    return res
