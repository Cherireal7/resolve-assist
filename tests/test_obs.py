"""OBS control: the real client <-> a fake obs-websocket v5 server over real sockets and real
RFC 6455 frames (handshake, masking, fragmentation, ping, close codes). No OBS needed."""

import asyncio
import base64
import hashlib
import io
import json
import os
import socket
import struct
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from resolve_assist import api, cli, obs
from resolve_assist.library.build import load_manifest, refresh_index, search

from helpers import TempEnv

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PASSWORD = "test-password-123"
SALT, CHALLENGE = "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=", "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="


def spec_auth(password: str, salt: str, challenge: str) -> str:
    """obs-websocket protocol.md: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """Server → client frame (servers never mask)."""
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack("!H", n)
    else:
        head += bytes([127]) + struct.pack("!Q", n)
    return head + payload


class _Conn:
    def __init__(self, sock: socket.socket) -> None:
        self.sock, self.buf = sock, b""

    def read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def read_frame(self) -> tuple[int, bytes]:
        b0, b1 = self.read(2)
        if not b1 & 0x80:
            raise AssertionError("client frames must be masked")
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self.read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self.read(8))[0]
        key = self.read(4)
        return b0 & 0x0F, bytes(b ^ key[i % 4] for i, b in enumerate(self.read(n)))


class FakeOBS:
    """Speaks just enough obs-websocket v5 for the client: Hello/Identify/requests, plus noise."""

    def __init__(self) -> None:
        self.password: str | None = PASSWORD
        self.scenes = ["App screen", "Talking head", "Voiceover"]  # dock order, top first
        self.extra_scenes = 0
        self.current = "App screen"
        self.recording = False
        self.fail_start = False
        self.record_dir = str(obs.footage_dir())
        self.ext = ".mp4"
        self.output: Path | None = None
        self.requests: list[str] = []
        self.client_close_codes: list[int] = []
        self.errors: list[str] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.srv.settimeout(0.1)
        self.port = self.srv.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self._stop = True
        self.thread.join(2)
        self.srv.close()

    def _serve(self) -> None:
        while not self._stop:
            try:
                sock, _ = self.srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            threading.Thread(target=self._session, args=(sock,), daemon=True).start()

    def _session(self, sock: socket.socket) -> None:
        sock.settimeout(5)
        with sock:
            try:
                self._handle(sock)
            except EOFError:
                pass
            except Exception as exc:  # surfaced by tearDown
                self.errors.append(f"{type(exc).__name__}: {exc}")

    def _handle(self, sock: socket.socket) -> None:
        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += sock.recv(4096)
        lines = raw.decode().split("\r\n")
        headers = {k.lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:] if ln)}
        assert lines[0].startswith("GET / HTTP/1.1"), lines[0]
        assert headers.get("sec-websocket-protocol") == "obswebsocket.json"
        accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()).decode()
        hello = {"op": 0, "d": {"obsStudioVersion": "33.0.1", "obsWebSocketVersion": "5.7.6", "rpcVersion": 1}}
        if self.password:
            hello["d"]["authentication"] = {"challenge": CHALLENGE, "salt": SALT}
        # 101 reply and Hello in one write: the client must keep the bytes after the headers
        sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode()
                     + frame(1, json.dumps(hello).encode()))
        conn = _Conn(sock)
        op, data = conn.read_frame()
        if op == 8:  # client gave up before identifying (e.g. no password file)
            self.client_close_codes.append(struct.unpack("!H", data[:2])[0])
            sock.sendall(frame(8, data[:2]))
            return
        ident = json.loads(data)
        assert ident["op"] == 1 and ident["d"]["rpcVersion"] == 1
        if self.password and ident["d"].get("authentication") != spec_auth(self.password, SALT, CHALLENGE):
            sock.sendall(frame(8, struct.pack("!H", 4009) + b"Authentication failed."))
            conn.read_frame()  # the client's close reply
            return
        sock.sendall(frame(1, json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}).encode()))
        while True:
            op, data = conn.read_frame()
            if op == 8:
                self.client_close_codes.append(struct.unpack("!H", data[:2])[0])
                sock.sendall(frame(8, data[:2]))
                return
            if op == 0xA:  # pong to our ping
                continue
            d = json.loads(data)["d"]
            self.requests.append(d["requestType"])
            ok, payload = self._respond(d["requestType"], d.get("requestData") or {})
            status = {"result": ok, "code": 100}
            if not ok:
                status = {"result": False, "code": payload.pop("code"), "comment": payload.pop("comment")}
            reply = {"op": 7, "d": {"requestType": d["requestType"], "requestId": d["requestId"],
                                    "requestStatus": status, **({"responseData": payload} if ok else {})}}
            body = json.dumps(reply).encode()
            half = len(body) // 2
            # noise first (a ping and an unrelated event), then the reply split into two fragments
            sock.sendall(frame(9, b"ping") + frame(1, json.dumps({"op": 5, "d": {"eventType": "Noise"}}).encode())
                         + frame(1, body[:half], fin=False) + frame(0, body[half:]))

    def _respond(self, rt: str, data: dict) -> tuple[bool, dict]:
        if rt == "GetCurrentProgramScene":
            return True, {"sceneName": self.current, "sceneUuid": "u1", "currentProgramSceneName": self.current}
        if rt == "GetSceneList":
            names = self.scenes + [f"Extra scene {i:05d} {'x' * 60}" for i in range(self.extra_scenes)]
            listed = [{"sceneIndex": i, "sceneName": n, "sceneUuid": str(i)} for i, n in enumerate(reversed(names))]
            return True, {"currentProgramSceneName": self.current, "scenes": listed}  # bottom-up, like OBS
        if rt == "SetCurrentProgramScene":
            if data.get("sceneName") not in self.scenes:
                return False, {"code": 600, "comment": "No source was found."}
            self.current = data["sceneName"]
            return True, {}
        if rt == "GetRecordStatus":
            return True, {"outputActive": self.recording, "outputPaused": False, "outputBytes": 0,
                          "outputTimecode": "00:00:03.000", "outputDuration": 3000 if self.recording else 0}
        if rt == "GetRecordDirectory":
            return True, {"recordDirectory": self.record_dir}
        if rt == "GetProfileList":
            return True, {"currentProfileName": "Vertical 1080x1920", "profiles": ["Vertical 1080x1920"]}
        if rt == "GetSceneCollectionList":
            return True, {"currentSceneCollectionName": "Content Studio", "sceneCollections": ["Content Studio"]}
        if rt == "StartRecord":
            if self.recording:
                return False, {"code": 500, "comment": "The output is running."}
            if self.fail_start:
                return True, {}  # accepted, but the output never becomes active
            Path(self.record_dir).mkdir(parents=True, exist_ok=True)
            self.output = Path(self.record_dir) / f"obs-2026-11-20_10-00-00{self.ext}"
            self.output.write_bytes(b"\0" * 1000)
            self.recording = True
            return True, {}
        if rt == "StopRecord":
            if not self.recording or self.output is None:
                return False, {"code": 501, "comment": "The output is not running."}
            with open(self.output, "ab") as f:
                f.write(b"\1" * 1000)
            self.recording = False
            if self.ext == ".mkv":  # OBS auto-remux writes the .mp4 a moment later
                mp4 = self.output.with_suffix(".mp4")
                threading.Timer(0.3, lambda: mp4.write_bytes(b"\2" * 3000)).start()
            return True, {"outputPath": str(self.output)}
        return False, {"code": 204, "comment": f"unknown request {rt}"}


class OBSClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempEnv().__enter__()
        self.pw_file = Path(os.environ["RESOLVE_ASSIST_OBS_PASSWORD_FILE"])
        self.pw_file.write_text(PASSWORD + "\n", encoding="utf-8")
        os.chmod(self.pw_file, 0o600)
        self.fake = FakeOBS()
        os.environ["RESOLVE_ASSIST_OBS_PORT"] = str(self.fake.port)

    def tearDown(self) -> None:
        self.fake.close()
        self.env.__exit__(None, None, None)
        self.assertEqual(self.fake.errors, [])

    def test_auth_response_follows_the_spec(self):
        self.assertEqual(obs.auth_response(PASSWORD, SALT, CHALLENGE), spec_auth(PASSWORD, SALT, CHALLENGE))
        self.assertNotEqual(obs.auth_response("other", SALT, CHALLENGE), spec_auth(PASSWORD, SALT, CHALLENGE))

    def test_status_connected_and_never_leaks_the_password(self):
        st = api.obs_status()
        self.assertTrue(st["connected"], st)
        self.assertTrue(st["authenticated"])
        self.assertEqual((st["obs_version"], st["websocket_version"]), ("33.0.1", "5.7.6"))
        self.assertEqual(st["current_scene"], "App screen")
        self.assertEqual((st["profile"], st["scene_collection"]), ("Vertical 1080x1920", "Content Studio"))
        self.assertFalse(st["recording"])
        self.assertTrue(st["records_into_library"])
        self.assertEqual(st["warnings"], [])
        self.assertNotIn(PASSWORD, json.dumps(st))
        deadline = time.monotonic() + 2
        while not self.fake.client_close_codes and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.fake.client_close_codes, [1000])  # clean close handshake

    def test_scenes_in_dock_order_and_switching(self):
        self.assertEqual(api.obs_scenes(), {"current_scene": "App screen",
                                            "scenes": ["App screen", "Talking head", "Voiceover"]})
        self.assertEqual(api.obs_switch_scene("Voiceover"), {"current_scene": "Voiceover"})
        with self.assertRaises(obs.OBSError) as cm:
            api.obs_switch_scene("Gaming")
        self.assertIn("Talking head", str(cm.exception))  # lists the real scenes
        sent = len(self.fake.requests)
        with self.assertRaises(ValueError):
            api.obs_switch_scene("bad\nname")
        self.assertEqual(len(self.fake.requests), sent)  # rejected before anything reaches OBS

    def test_large_messages_use_64_bit_lengths_and_fragments(self):
        self.fake.extra_scenes = 3000  # ~250 KB reply in two fragments
        scenes = api.obs_scenes()["scenes"]
        self.assertEqual(len(scenes), 3003)
        self.assertEqual(scenes[:3], ["App screen", "Talking head", "Voiceover"])

    def test_record_start_stop_indexes_the_clip_for_import(self):
        res = api.obs_start_recording("Talking head")
        self.assertEqual((res["recording"], res["scene"], res["records_into_library"]), (True, "Talking head", True))
        with self.assertRaises(obs.OBSError) as cm:
            api.obs_start_recording()
        self.assertIn("already recording", str(cm.exception))
        out = api.obs_stop_recording()
        rel = "footage/obs/obs-2026-11-20_10-00-00.mp4"
        self.assertEqual(out["file"], str(obs.footage_dir() / "obs-2026-11-20_10-00-00.mp4"))
        self.assertEqual((out["library_file"], out["seconds"]), (rel, 3.0))
        self.assertTrue(out["library"]["indexed"])
        self.assertNotIn("notes", out)
        hit = search("obs recording", category="footage")[0]
        self.assertEqual((hit["file"], hit["id"]), (rel, "obs-2026-11-20_10-00-00"))
        self.assertIn("vertical", hit["tags"])
        self.assertEqual(api._library_rel(rel), rel)  # what import_assets sends to the bridge
        with self.assertRaises(obs.OBSError) as cm:
            api.obs_stop_recording()
        self.assertIn("not recording", str(cm.exception))

    def test_mkv_recording_waits_for_the_remuxed_mp4(self):
        self.fake.ext = ".mkv"
        api.obs_start_recording()
        out = api.obs_stop_recording(refresh_library=False)
        self.assertTrue(out["file"].endswith("obs-2026-11-20_10-00-00.mp4"), out)
        self.assertEqual(out["size_mb"], 0.0)
        self.assertNotIn("library", out)
        self.assertIn("library_build", out["next"])

    def test_recording_outside_the_library_is_reported(self):
        self.fake.record_dir = str(self.env.root / "Movies")
        st = api.obs_status()
        self.assertFalse(st["records_into_library"])
        self.assertTrue(any("Recording Path" in w for w in st["warnings"]))
        api.obs_start_recording()
        out = api.obs_stop_recording()
        self.assertNotIn("library_file", out)
        self.assertTrue(any("outside the library" in n for n in out["notes"]))

    def test_start_that_never_becomes_active_fails_clearly(self):
        self.fake.fail_start = True
        with self.assertRaises(obs.OBSError) as cm:
            obs.start_recording(confirm_seconds=0.5)
        self.assertIn("permission prompt", str(cm.exception))
        self.assertIn("check obs_status", str(cm.exception))  # it may still start: don't double-start

    def test_wrong_password(self):
        self.pw_file.write_text("not-the-password", encoding="utf-8")
        with self.assertRaises(obs.OBSError) as cm:
            api.obs_scenes()
        self.assertIn("rejected the password", str(cm.exception))
        self.assertNotIn("not-the-password", str(cm.exception))
        st = api.obs_status()
        self.assertFalse(st["connected"])
        self.assertIn("rejected the password", st["message"])

    def test_missing_password_file(self):
        self.pw_file.unlink()
        with self.assertRaises(obs.OBSError) as cm:
            api.obs_scenes()
        self.assertIn("missing or empty", str(cm.exception))

    def test_server_without_auth(self):
        self.fake.password = None
        self.pw_file.unlink()
        st = api.obs_status()
        self.assertTrue(st["connected"])
        self.assertFalse(st["authenticated"])

    def test_readable_password_file_is_warned(self):
        os.chmod(self.pw_file, 0o644)
        self.assertTrue(any("chmod 600" in w for w in api.obs_status()["warnings"]))

    def test_cli_commands(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["obs-scene", "Voiceover"]), 0)
            self.assertEqual(cli.main(["obs-record"]), 0)
            self.assertEqual(cli.main(["obs-stop", "--no-index"]), 0)
            self.assertEqual(cli.main(["obs-status"]), 0)
        self.assertIn('"current_scene": "Voiceover"', out.getvalue())
        self.assertIn("obs-2026-11-20_10-00-00.mp4", out.getvalue())


class OBSOfflineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TempEnv().__enter__()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        os.environ["RESOLVE_ASSIST_OBS_PORT"] = str(s.getsockname()[1])
        s.close()  # nothing listens there now

    def tearDown(self) -> None:
        self.env.__exit__(None, None, None)

    def test_offline_is_graceful(self):
        st = api.obs_status()
        self.assertFalse(st["connected"])
        self.assertIn("WebSocket Server Settings", st["message"])
        with self.assertRaises(obs.OBSOffline):
            api.obs_start_recording()
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            self.assertEqual(cli.main(["obs-scenes"]), 1)
            self.assertEqual(cli.main(["obs-status"]), 1)
        self.assertIn("error: OBS is not reachable", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertFalse(json.loads(out.getvalue())["connected"])

    def test_something_else_on_the_port(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        os.environ["RESOLVE_ASSIST_OBS_PORT"] = str(srv.getsockname()[1])

        def answer():
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            conn.close()

        t = threading.Thread(target=answer, daemon=True)
        t.start()
        with self.assertRaises(obs.OBSOffline) as cm:
            api.obs_scenes()
        self.assertIn("not as obs-websocket", str(cm.exception))
        t.join(2)
        srv.close()

    def test_bad_port_setting(self):
        os.environ["RESOLVE_ASSIST_OBS_PORT"] = "not-a-port"
        with self.assertRaises(obs.OBSError):
            obs.port()

    def test_mcp_tools_registered_and_offline_safe(self):
        try:
            from resolve_assist import server
        except ImportError:
            self.skipTest("mcp SDK not installed")
        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        self.assertTrue({"obs_status", "obs_list_scenes", "obs_switch_scene", "obs_start_recording",
                         "obs_stop_recording"} <= names)
        self.assertFalse(json.loads(server.obs_status())["connected"])
        self.assertEqual(json.loads(server.obs_list_scenes())["error"], "OBSOffline")


class LibraryIndexTest(unittest.TestCase):
    def test_refresh_rescans_user_folders_and_keeps_generated_assets(self):
        with TempEnv():
            lib = obs.footage_dir().parents[1]
            obs.footage_dir().mkdir(parents=True)
            (lib / "manifest.json").write_text(json.dumps({"items": [
                {"id": "whoosh", "category": "sfx", "file": "sfx/whoosh.wav", "tags": [], "usage": ""},
                {"id": "gone", "category": "footage", "file": "footage/obs/gone.mp4", "tags": [], "usage": ""},
            ]}), encoding="utf-8")
            (obs.footage_dir() / "obs-2026-11-21_09-00-00.mp4").write_bytes(b"x")
            (obs.footage_dir() / "obs-2026-11-21_09-00-00.mkv").write_bytes(b"x")  # remux source: not indexed
            res = refresh_index()
            files = [it["file"] for it in load_manifest()["items"]]
            self.assertEqual(files, ["sfx/whoosh.wav", "footage/obs/obs-2026-11-21_09-00-00.mp4"])
            self.assertEqual((res["total"], res["user_items"]), (2, 1))
            self.assertIn("footage/obs/", (lib / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
