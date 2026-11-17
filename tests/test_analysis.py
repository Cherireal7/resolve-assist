import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from resolve_assist.analysis.beats import analyze_audio
from resolve_assist.analysis.fingerprint import fingerprint, similarity
from resolve_assist.analysis.shots import detect_shots, frame_difference, match_cuts
from resolve_assist.audio import PRESETS, generate
from resolve_assist.imaging.png import Image

W, H = 64, 36


def draw(kind: str, color=(0.9, 0.8, 0.2), bg=(0.1, 0.1, 0.12), jitter: float = 0.0, seed: int = 0) -> Image:
    """Tiny synthetic scenes: a disc on the left, a bar on the right, or diagonal stripes."""
    rnd = random.Random(seed)
    px = []
    for y in range(H):
        for x in range(W):
            if kind == "disc":
                inside = (x - 16 - jitter) ** 2 + (y - 18) ** 2 < 64
            elif kind == "bar":
                inside = 44 <= x - jitter <= 52
            else:  # stripes
                inside = ((x + y + int(jitter)) // 6) % 2 == 0
            c = color if inside else bg
            n = rnd.uniform(-0.02, 0.02)
            px.append(tuple(min(1.0, max(0.0, v + n)) for v in c))
    return Image(W, H, px, W, H)


def scene_frames():
    frames = []
    t = 0.0
    for kind, color, bg in (("disc", (0.95, 0.85, 0.3), (0.08, 0.08, 0.1)),
                            ("stripes", (0.2, 0.6, 0.9), (0.9, 0.9, 0.85)),
                            ("disc", (0.3, 0.9, 0.5), (0.1, 0.05, 0.05))):
        for i in range(8):
            frames.append((t, draw(kind, color, bg, jitter=i * 0.3, seed=int(t * 10))))
            t += 0.25
    return frames


class FingerprintTests(unittest.TestCase):
    def test_same_shape_same_place_scores_high(self):
        a = fingerprint(draw("disc", (0.9, 0.8, 0.2)))
        b = fingerprint(draw("disc", (0.3, 0.9, 0.5)))       # same composition, other color
        c = fingerprint(draw("bar", (0.9, 0.8, 0.2)))        # same color, other composition
        self.assertGreater(similarity(a, b)["total"], similarity(a, c)["total"])
        self.assertGreater(similarity(a, b)["position"], 0.8)

    def test_edges_capture_orientation(self):
        stripes = fingerprint(draw("stripes"))
        bar = fingerprint(draw("bar"))
        self.assertGreater(max(stripes.edges), 0.3)          # one dominant diagonal direction
        self.assertNotEqual(stripes.edges.index(max(stripes.edges)), bar.edges.index(max(bar.edges)))


class ShotTests(unittest.TestCase):
    def test_detects_three_shots_and_match_cut(self):
        shots = detect_shots(scene_frames())
        self.assertEqual([round(s.start, 2) for s in shots], [0.0, 2.0, 4.0])
        best = match_cuts(shots, top=3, min_score=0.0)[0]
        self.assertEqual({best["from_shot"], best["to_shot"]}, {0, 2})  # disc ↔ disc rhyme
        self.assertTrue(best["why"])

    def test_small_motion_is_not_a_cut(self):
        a, b = draw("disc", jitter=0), draw("disc", jitter=1.5)
        self.assertLess(frame_difference(a, b), 0.2)


class BeatTests(unittest.TestCase):
    def test_tempo_and_grid_on_known_tracks(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("calm-lofi", "bright-pop", "ambient"):
                p = Path(d) / f"{name}.wav"
                generate(name, 16.0, p)
                r = analyze_audio(p)
                true_bpm = PRESETS[name]["bpm"]
                self.assertAlmostEqual(r["bpm"], true_bpm, delta=1.5, msg=name)
                period = 60.0 / true_bpm
                # every detected beat lies within 80 ms of the true grid
                for b in r["beats"]:
                    off = b % period
                    self.assertLess(min(off, period - off), 0.08, msg=f"{name} beat {b}")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class VideoTests(unittest.TestCase):
    def test_sample_frames_and_shots_from_a_real_video(self):
        from resolve_assist.analysis.video import probe, sample_frames
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "test.mp4"
            # 2 s red, 2 s blue (lavfi test sources): one cut at 2 s
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:d=2:r=25",
                            "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=2:r=25", "-filter_complex",
                            "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(out)],
                           check=True)
            info = probe(out)
            self.assertAlmostEqual(info["duration"], 4.0, delta=0.1)
            frames = sample_frames(out, fps=4)
            self.assertGreaterEqual(len(frames), 15)
            shots = detect_shots(frames)
            self.assertEqual(len(shots), 2)
            self.assertAlmostEqual(shots[1].start, 2.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()


class PlanTests(unittest.TestCase):
    def test_cuts_land_on_beats_and_match_order(self):
        from resolve_assist.analysis.plan import plan_cuts
        shots = detect_shots(scene_frames())            # disc, stripes, disc
        beats = [0.5 + i * 0.5 for i in range(20)]      # 120 BPM grid starting at 0.5 s
        plan = plan_cuts([("a.mp4", shots)], beats, beats[::4], duration=6.0, beats_per_cut=2)
        segs = plan["segments"]
        self.assertEqual(segs[0]["timeline_in"], 0.0)
        for s in segs[1:]:
            self.assertIn(s["timeline_in"], [round(b, 3) for b in beats])  # every cut on a beat
        # after the first disc shot, the matching disc shot (2) is chosen before the stripes (1)
        self.assertEqual([s["shot"] for s in segs[:2]], [0, 2])
        self.assertTrue(segs[1]["why"].startswith("match cut"))
        total = sum(s["duration"] for s in segs)
        self.assertAlmostEqual(total, 6.0, places=2)

    def test_rejects_bad_input(self):
        from resolve_assist.analysis.plan import plan_cuts
        shots = detect_shots(scene_frames())
        with self.assertRaises(ValueError):
            plan_cuts([("a", shots)], [1.0], [], 5.0)
        with self.assertRaises(ValueError):
            plan_cuts([("a", shots)], [0.5, 1.0], [], 5.0, beats_per_cut=0)


class LibraryTests(unittest.TestCase):
    def test_sfx_recipes_render_valid_wavs(self):
        import wave
        from resolve_assist.library import sfx
        with tempfile.TemporaryDirectory() as d:
            for name in ("swoosh-fast", "pop-bubble", "hit-punch"):
                fn, kw, _tags, _usage = sfx.RECIPES[name]
                p = Path(d) / f"{name}.wav"
                secs = sfx.write_wav(p, fn(**kw))
                with wave.open(str(p)) as w:
                    self.assertEqual((w.getnchannels(), w.getframerate()), (2, 48000))
                    self.assertAlmostEqual(w.getnframes() / 48000, secs, places=2)

    def test_search_ranks_by_words(self):
        import json, os
        from resolve_assist.library.build import search
        with tempfile.TemporaryDirectory() as d:
            os.environ["RESOLVE_ASSIST_OUTPUT"] = d
            try:
                (Path(d) / "library").mkdir()
                items = [{"id": "whoosh-medium", "category": "sfx", "file": "sfx/w.wav", "tags": ["whoosh", "transition"], "usage": "cut"},
                         {"id": "flash-white", "category": "transitions", "file": "t/f.mp4", "tags": ["flash", "transition"], "usage": "cut"},
                         {"id": "gradient-ocean-9x16", "category": "backgrounds", "file": "b/o.png", "tags": ["vertical"], "usage": "cards"}]
                (Path(d) / "library" / "manifest.json").write_text(json.dumps({"items": items}))
                self.assertEqual(search("whoosh transition")[0]["id"], "whoosh-medium")
                self.assertEqual([i["id"] for i in search("transition", category="transitions")], ["flash-white"])
                self.assertEqual(search("nothing-matches"), [])
            finally:
                os.environ.pop("RESOLVE_ASSIST_OUTPUT", None)

    def test_png_alpha_roundtrip(self):
        from resolve_assist.imaging.png import decode_png, encode_png
        data = encode_png(2, 1, [(1.0, 0.0, 0.0, 0.5), (0.0, 1.0, 0.0, 1.0)])
        img = decode_png(data)
        self.assertAlmostEqual(img.pixels[0][0], 1.0)


class CaptionTests(unittest.TestCase):
    SRT = """1
00:00:00,500 --> 00:00:01,800
Welcome to the

2
00:00:01,800 --> 00:00:03,100
nail art session

3
00:00:03,100 --> 00:00:04,000
[MUSIC]
"""

    def test_parse_drop_tags_and_roundtrip(self):
        from resolve_assist.captions import parse_srt, to_srt
        cues = parse_srt(self.SRT)
        self.assertEqual([c.text for c in cues], ["Welcome to the", "nail art session"])
        self.assertAlmostEqual(cues[1].start, 1.8)
        again = parse_srt(to_srt(cues))
        self.assertEqual([(c.start, c.end, c.text) for c in again], [(c.start, c.end, c.text) for c in cues])

    def test_shift_and_trim_to_clip(self):
        from resolve_assist.captions import parse_srt, shift
        cues = parse_srt(self.SRT)
        moved = shift(cues, offset=10.0, clip_from=0.0, clip_to=2.5)
        self.assertEqual([(round(c.start, 2), round(c.end, 2)) for c in moved], [(10.5, 11.8), (11.8, 12.5)])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_pipeline_with_fake_whisper(self):
        import os, stat
        from resolve_assist import captions
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake = d / "whisper-cli"
            fake.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ \"$1\" = -of ]; then OUT=$2; fi; shift; done\n"
                            "printf '1\\n00:00:00,000 --> 00:00:01,000\\nhello\\n' > \"$OUT.srt\"\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            os.environ["RESOLVE_ASSIST_OUTPUT"] = str(d / "out")
            old_path = os.environ["PATH"]
            os.environ["PATH"] = f"{d}:{old_path}"
            try:
                model = captions.models_dir() / "ggml-tiny.bin"
                model.parent.mkdir(parents=True)
                with model.open("wb") as fh:
                    fh.write(b"lmgg" + b"\0" * (76 * 1024 * 1024))
                audio = d / "a.wav"
                generate("ambient", 1.5, audio)
                cues = captions.transcribe(audio, model="tiny")
                self.assertEqual([c.text for c in cues], ["hello"])
            finally:
                os.environ["PATH"] = old_path
                os.environ.pop("RESOLVE_ASSIST_OUTPUT", None)
