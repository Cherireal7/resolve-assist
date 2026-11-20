import json
import os
import shutil
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

from resolve_assist import api
from resolve_assist.imaging.png import PNG_SIGNATURE, PNGError, decode_png, encode_png
from resolve_assist.paths import PathError, check_input_media, output_path, safe_name

from helpers import TempEnv, scene, write_png


def chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


class PNGTests(unittest.TestCase):
    def test_roundtrip_8_and_16_bit(self):
        w, h, px = scene(20, 10)
        for depth, tol in ((8, 1 / 255), (16, 1 / 65535)):
            img = decode_png(encode_png(w, h, px, depth))
            self.assertEqual((img.width, img.height), (20, 10))
            for a, b in zip(img.pixels[5], px[5]):
                self.assertAlmostEqual(a, b, delta=tol)

    def test_all_filters(self):
        # 3x2 RGB image, row 0 filter 1 (sub), row 1 filter 4 (paeth) -> hand-built
        w, h = 3, 2
        row0 = [10, 20, 30, 40, 50, 60, 70, 80, 90]
        row1 = [15, 25, 35, 45, 55, 65, 75, 85, 95]

        def sub(row):
            return [row[i] - (row[i - 3] if i >= 3 else 0) & 0xFF for i in range(len(row))]

        def paeth_enc(row, prev):
            out = []
            for i in range(len(row)):
                a = row[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                out.append((row[i] - pred) & 0xFF)
            return out

        for f1, enc in ((2, lambda r, p: [(x - y) & 0xFF for x, y in zip(r, p)]),
                        (3, lambda r, p: [(r[i] - (((r[i - 3] if i >= 3 else 0) + p[i]) >> 1)) & 0xFF for i in range(9)]),
                        (4, paeth_enc)):
            raw = bytes([1] + sub(row0) + [f1] + enc(row1, row0))
            data = PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
            img = decode_png(data)
            self.assertAlmostEqual(img.pixels[0][0], 10 / 255)
            self.assertAlmostEqual(img.pixels[5][2], 95 / 255, msg=f"filter {f1}")

    def test_downsample(self):
        w, h, px = scene(200, 100)
        img = decode_png(encode_png(w, h, px), max_side=50)
        self.assertLessEqual(max(img.width, img.height), 50)
        self.assertEqual(img.source_width, 200)

    def test_rejects_bombs_and_garbage(self):
        with self.assertRaises(PNGError):
            decode_png(b"not a png")
        huge = PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 50000, 50000, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
        with self.assertRaises(PNGError):
            decode_png(huge)
        interlaced = PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 1)) + chunk(b"IEND", b"")
        with self.assertRaises(PNGError):
            decode_png(interlaced)


class PathSecurityTests(unittest.TestCase):
    def test_input_rules(self):
        with TempEnv() as env:
            secret = env.root / "id_rsa"
            secret.write_text("x")
            for bad in (str(secret), "", "http://example.com/a.png", str(env.root / "missing.png"), str(env.root)):
                with self.assertRaises(PathError):
                    check_input_media(bad)
            ok = write_png(env.root, "a.PNG", 2, 2, [(0, 0, 0)] * 4)
            self.assertEqual(check_input_media(str(ok)), ok.resolve())

    def test_symlink_to_non_media_is_rejected(self):
        with TempEnv() as env:
            target = env.root / "notes.txt"
            target.write_text("secret")
            link = env.root / "fake.png"
            os.symlink(target, link)
            with self.assertRaises(PathError):
                check_input_media(str(link))

    def test_output_names_cannot_escape(self):
        with TempEnv() as env:
            for name in ("../../evil", "/etc/passwd", "..", "a/b\\c"):
                p = output_path(name, ".cube")
                self.assertEqual(p.parent, (env.root / "out" / "LUTs").resolve())
            self.assertEqual(safe_name("../x;rm -rf"), "xrm -rf")
            self.assertEqual(safe_name(".."), "grade")
            self.assertLessEqual(len(safe_name("a" * 500)), 64)

    def test_no_overwrite_by_default(self):
        with TempEnv():
            p = output_path("dup", ".cube")
            p.write_text("x")
            with self.assertRaises(PathError):
                output_path("dup", ".cube")
            self.assertEqual(output_path("dup", ".cube", overwrite=True), p)


class APITests(unittest.TestCase):
    def test_end_to_end_png_workflow(self):
        with TempEnv() as env:
            os.environ["PATH"] = ""  # force built-in decoder
            os.environ["RESOLVE_ASSIST_FFMPEG"] = "none"
            w, h, px = scene(cast=(1.12, 1.0, 0.85))
            still = write_png(env.root, "shot.png", w, h, px, depth=16)
            stats = api.analyze(str(still))
            self.assertEqual(stats["decoder"], "builtin-png")
            bal = api.balance(str(still))
            self.assertLess(max(abs(v) for v in bal["after"]["cast_after"].values()), 0.03)
            c = bal["cdl"]
            out = api.make_lut("Shot 1 balance", look="warm-film", strength=0.5,
                               slope=c["slope"], offset=c["offset"], power=c["power"], size=17,
                               install_to_resolve=True)
            self.assertTrue(Path(out["lut_path"]).is_file())
            self.assertTrue(Path(out["cc_path"]).is_file())
            self.assertTrue(Path(out["installed_path"]).is_file())
            prev = api.preview(str(still), "shot1", look="teal-orange")
            self.assertTrue(Path(prev["preview_path"]).read_bytes().startswith(PNG_SIGNATURE))
            m = api.match(str(still), str(still))
            for v in m["cdl"]["slope"]:
                self.assertAlmostEqual(v, 1.0, delta=0.01)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("sips"), "macOS sips only")
    def test_sips_decodes_tiff(self):
        with TempEnv() as env:
            w, h, px = scene(64, 32)
            png = write_png(env.root, "s.png", w, h, px)
            tiff = env.root / "s.tiff"
            subprocess.run(["sips", "-s", "format", "tiff", str(png), "--out", str(tiff)],
                           capture_output=True, check=True)
            os.environ["PATH"] = "/usr/bin"  # sips yes
            os.environ["RESOLVE_ASSIST_FFMPEG"] = "none"  # ffmpeg off
            stats = api.analyze(str(tiff))
            self.assertEqual(stats["decoder"], "sips")
            self.assertEqual(stats["source_width"], 64)

    def test_unknown_look_and_bad_size(self):
        with TempEnv():
            with self.assertRaises(ValueError):
                api.make_lut("x", look="nope")
            with self.assertRaises(ValueError):
                api.make_lut("x", size=8)

    def test_probe_install_and_reports(self):
        with TempEnv() as env:
            report_dir = env.root / "state"
            self.assertFalse(api.probe_report()["found"])
            report_dir.mkdir()
            payload = {"checks": {"product": "DaVinci Resolve", "note": 'say "hi"\n'}}
            # bmd.writefile-style Lua fallback
            lua_str = json.dumps(payload).replace("\\", "\\\\").replace('"', '\\"')
            (report_dir / "probe-report.lua").write_text('{\n\tjson = "' + lua_str + '"\n}\n')
            self.assertEqual(api.probe_report()["report"], payload)
            (report_dir / "probe-report.json").write_text(json.dumps(payload))
            self.assertTrue(api.probe_report()["path"].endswith(".json"))


if __name__ == "__main__":
    unittest.main()
