"""Expanded library (SFX, sequenced music, browser), editor choice and project kits."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path

from resolve_assist import workspace
from resolve_assist.analysis.beats import analyze_audio
from resolve_assist.audio import PRESETS, generate
from resolve_assist.library import sfx, sfx_cine, sfx_ui
from resolve_assist.library.browser import write_browser
from resolve_assist.library.build import scan_user_folders


class SfxTests(unittest.TestCase):
    def test_new_recipes_have_unique_names_and_render(self):
        names = [*sfx.RECIPES, *sfx_ui.RECIPES, *sfx_cine.RECIPES]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 80)
        with tempfile.TemporaryDirectory() as d:
            for mod, name in ((sfx_ui, "ui-success"), (sfx_ui, "fun-boing"), (sfx_cine, "whoosh-whip"),
                              (sfx_cine, "drum-clap"), (sfx_cine, "impact-thud")):
                fn, kw, tags, usage = mod.RECIPES[name]
                left, right = fn(**kw)
                self.assertEqual(len(left), len(right))
                self.assertGreater(max(map(abs, left)), 0.01, name)
                secs = sfx.write_wav(Path(d) / f"{name}.wav", (left, right), sfx_cine.PEAKS.get(name, 0.89))
                self.assertGreater(secs, 0.03)
                self.assertTrue(tags and usage)

    def test_quiet_beds_keep_their_peak(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hiss.wav"
            fn, kw, _t, _u = sfx_cine.RECIPES["ambience-tape-hiss"]
            sfx.write_wav(p, fn(seconds=0.5), sfx_cine.PEAKS["ambience-tape-hiss"])
            with wave.open(str(p)) as w:
                raw = w.readframes(w.getnframes())
            peak = max(abs(int.from_bytes(raw[i:i + 2], "little", signed=True)) for i in range(0, len(raw), 2))
            self.assertLess(peak / 32767, 0.13)


class SequencerTests(unittest.TestCase):
    def test_every_sequenced_preset_is_well_formed(self):
        for name, cfg in PRESETS.items():
            if "seq" not in cfg:
                continue
            steps = cfg.get("steps", 16)
            seq = cfg["seq"]
            patterns = [*seq.get("drums", {}).values()]
            if "bass" in seq:
                patterns.append(seq["bass"][0])
            if "arp" in seq:
                patterns.append(seq["arp"]["pattern"])
            if "lead" in seq:
                patterns.append(seq["lead"]["rhythm"])
            for pat in patterns:
                self.assertEqual(len(pat), steps, f"{name}: pattern '{pat}' must have {steps} steps")
            self.assertTrue(cfg["description"] and 40 <= cfg["bpm"] <= 200, name)

    def test_sequenced_track_renders_in_tempo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.wav"
            out = generate("chill-house", 12.0, p)
            self.assertEqual(out["seconds"], 12.0)
            with wave.open(str(p)) as w:
                self.assertEqual((w.getnchannels(), w.getframerate()), (2, 44100))
                self.assertAlmostEqual(w.getnframes() / 44100, 12.0, places=1)
            self.assertAlmostEqual(analyze_audio(p)["bpm"], PRESETS["chill-house"]["bpm"], delta=2.0)

    def test_known_tempo_wins_over_detection(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.wav"
            generate("ethio-tizita", 8.0, p)          # 6/8 feel: the detector may pick another pulse
            r = analyze_audio(p, bpm_hint=100)
            self.assertEqual(r["bpm"], 100.0)
            gaps = [b - a for a, b in zip(r["beats"], r["beats"][1:])]
            self.assertTrue(gaps and all(abs(g - 0.6) < 0.05 for g in gaps))


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {k: os.environ.get(k) for k in ("RESOLVE_ASSIST_OUTPUT", "STUDIO_EDITOR")}
        os.environ["RESOLVE_ASSIST_OUTPUT"] = self.tmp.name
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in self.old.items()])
        lib = Path(self.tmp.name) / "library"
        (lib / "sfx").mkdir(parents=True)
        (lib / "sfx" / "whoosh-whip.wav").write_bytes(b"RIFF")
        (lib / "fonts" / "Inter").mkdir(parents=True)
        (lib / "fonts" / "Inter" / "Inter-Bold.ttf").write_bytes(b"\0\1\0\0")
        (lib / "user-music").mkdir()
        (lib / "user-music" / "my-song.mp3").write_bytes(b"ID3")
        self.items = [{"id": "whoosh-whip", "category": "sfx", "file": "sfx/whoosh-whip.wav",
                       "tags": ["whoosh", "whip"], "usage": "Whip pans"}, *scan_user_folders(lib)]
        (lib / "manifest.json").write_text(json.dumps({"items": self.items}))
        self.lib = lib

    def test_user_folders_and_fonts_are_indexed(self):
        by_id = {i["id"]: i for i in self.items}
        self.assertEqual(by_id["Inter-Bold"]["file"], "fonts/Inter/Inter-Bold.ttf")
        self.assertIn("OFL", by_id["Inter-Bold"]["license"])
        self.assertEqual(by_id["my-song"]["category"], "music")

    def test_editor_choice(self):
        os.environ["STUDIO_EDITOR"] = "capcut"
        self.assertEqual(workspace.preferred_editor(), "capcut")
        os.environ["STUDIO_EDITOR"] = "something else"
        self.assertIn(workspace.preferred_editor(), workspace.EDITORS)
        os.environ["STUDIO_EDITOR"] = "capcut"
        res = workspace.doctor()
        self.assertEqual(res["editor"], "capcut")
        names = [c["check"] for c in res["checks"]]
        self.assertIn("CapCut", names)

    def test_kit_copies_matches_into_the_project(self):
        res = workspace.project_kit("Demo Video", ["whoosh", "no such thing", "song"])
        self.assertEqual(res["not_found"], ["no such thing"])
        files = sorted(c["file"] for c in res["copied"])
        self.assertEqual(files, ["kit/music/my-song.mp3", "kit/sfx/whoosh-whip.wav"])
        self.assertTrue((Path(self.tmp.name) / "projects" / "Demo Video" / "kit" / "sfx" / "whoosh-whip.wav").is_file())
        self.assertTrue((self.lib / "sfx" / "whoosh-whip.wav").is_file())       # copied, not moved
        with self.assertRaises(ValueError):
            workspace.project_kit("Demo Video", [])

    def test_intake_sorts_the_inbox_and_indexes_once(self):
        proj = Path(workspace.new_project("Trip")["project"])
        for name in ("clip one.mp4", "city-map.png", "logo.png", "voiceover take2.wav", "song.mp3", "script.txt",
                     "ref-style.jpg", "thing.xyz"):
            (proj / "inbox" / name).write_bytes(b"x")
        (proj / "stills").mkdir(exist_ok=True)
        (proj / "stills" / "logo.png").write_bytes(b"old")
        res = workspace.project_intake("Trip")
        self.assertEqual(sorted(res["moved"]), ["docs/script.txt", "footage/clip one.mp4", "maps/city-map.png",
                                                "music/song.mp3", "refs/ref-style.jpg", "stills/logo-1.png",
                                                "voice/voiceover take2.wav"])
        self.assertEqual(res["left_in_inbox"], ["thing.xyz"])
        self.assertEqual((proj / "stills" / "logo.png").read_bytes(), b"old")       # never overwritten
        self.assertEqual(res["counts"]["map"], 1)
        self.assertTrue((proj / "brief.md").is_file())
        self.assertEqual(workspace.project_index("Trip")["new"], [])                # nothing measured twice

    def test_browser_page_embeds_the_manifest_safely(self):
        items = [*self.items, {"id": "x</script><b>", "category": "sfx", "file": "sfx/x.wav", "tags": [], "usage": "u"}]
        page = write_browser(self.lib, items).read_text(encoding="utf-8")
        self.assertEqual(page.count("</script>"), 2)                 # only the page's own two script tags
        start = page.index('type="application/json">') + len('type="application/json">')
        data = json.loads(page[start:page.index("</script>", start)])
        self.assertEqual(len(data["items"]), len(items))
        self.assertIn("font-family:'lib-Inter-Bold'", page)


class EditPrepTests(unittest.TestCase):
    def test_silences_keep_ranges_and_remap(self):
        import math
        from resolve_assist.editprep import find_silences, keep_ranges, remap
        rate = 8000
        speech = lambda secs: [0.5 * math.sin(2 * math.pi * 220 * i / rate) for i in range(int(secs * rate))]
        quiet = lambda secs: [0.0005 * math.sin(i) for i in range(int(secs * rate))]
        samples = speech(1.0) + quiet(1.0) + speech(1.0) + quiet(0.2) + speech(0.5)
        sil = find_silences(samples, rate, min_silence=0.4)
        self.assertEqual(len(sil), 1)                                   # the 0.2 s pause stays
        self.assertAlmostEqual(sil[0][0], 1.0, delta=0.03)
        self.assertAlmostEqual(sil[0][1], 2.0, delta=0.03)
        keeps = keep_ranges(3.7, sil, padding=0.03)
        self.assertEqual(len(keeps), 2)
        self.assertAlmostEqual(keeps[0][1], 1.03, delta=0.03)           # 30 ms of the pause kept
        self.assertAlmostEqual(keeps[1][0], 1.97, delta=0.03)
        self.assertAlmostEqual(remap(2.5, keeps), 2.5 - (keeps[1][0] - keeps[0][1]), delta=0.001)
        self.assertEqual(remap(1.5, keeps), round(keeps[0][1] - keeps[0][0], 3))   # inside the cut

    def test_segments_and_plan_page(self):
        from resolve_assist.captions import Cue
        from resolve_assist.editprep import SCENE_TYPES, plan_page, segments_from_words
        words = [Cue(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("There are four patterns. Some go up </script> and up".split())]
        segs = segments_from_words(words)
        self.assertEqual([s["text"] for s in segs], ["There are four patterns.", "Some go up </script> and up"])
        with tempfile.TemporaryDirectory() as d:
            out = plan_page(Path(d) / "plan.html", Path(d) / "clip.mp4", segs, {"2": ["graph", "nope"]})
            page = out.read_text(encoding="utf-8")
            self.assertEqual(page.count("</script>"), 2)
            start = page.index('type="application/json">') + len('type="application/json">')
            data = json.loads(page[start:page.index("</script>", start)])
            self.assertEqual(data["recs"], {"2": ["graph"]})            # unknown scene types are dropped
            self.assertEqual(data["video"], "clip.mp4")
            self.assertEqual(set(data["types"]), set(SCENE_TYPES))


class NarrationAndCreditTests(unittest.TestCase):
    def test_script_markers_and_token_positions(self):
        from resolve_assist.narration import language_of, locate, split_script
        segs = split_script("In {y}1483, a boy\nwas born.\n\n{end}The end.")
        self.assertEqual(segs[0], ("In 1483, a boy was born.", [("y", 3)]))
        self.assertEqual(segs[1], ("The end.", [("end", 0)]))
        self.assertEqual(locate("In 1483, a boy was born.", [{"text": "In 1483,"}, {"text": "a"}, {"text": "boy"}]), [0, 9, 11])
        self.assertEqual((language_of("ሰላም world"), language_of("hello")), ("am", "en"))

    def test_commons_metadata_is_reduced_to_licence_facts(self):
        from resolve_assist.commons import _info
        page = {"title": "File:X.jpg", "imageinfo": [{"descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg", "mime": "image/jpeg",
                "thumburl": "https://upload.wikimedia.org/x.jpg", "width": 10, "height": 20,
                "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='x'>Some &amp; One</a>"}}}]}
        info = _info(page)
        self.assertEqual((info["license"], info["author"], info["free"], info["share_alike"], info["attribution"]),
                         ("CC BY-SA 4.0", "Some & One", False, True, True))
        page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = "Public domain"
        self.assertEqual((_info(page)["free"], _info(page)["share_alike"]), (True, False))
        self.assertIsNone(_info({"title": "File:gone"}))

    def test_credits_survive_reindexing_and_are_listed(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["RESOLVE_ASSIST_OUTPUT"] = d
            try:
                proj = Path(workspace.new_project("Doc")["project"])
                (proj / "music" / "song.mp3").write_bytes(b"ID3")
                res = workspace.project_credit("Doc", "song.mp3", "https://example.org/song", "CC BY-SA 4.0", "A. Writer")
                self.assertEqual(res["file"], "music/song.mp3")
                (proj / "music" / "song.mp3").write_bytes(b"ID3-changed-file")
                workspace.project_index("Doc")
                entry = json.loads((proj / "project.json").read_text())["files"][0]
                self.assertEqual((entry["license"], entry["author"]), ("CC BY-SA 4.0", "A. Writer"))
                credits = (proj / "CREDITS.md").read_text()
                self.assertIn("music/song.mp3", credits)
                self.assertIn("Share-alike", credits)
                with self.assertRaises(ValueError):
                    workspace.project_credit("Doc", "missing.png", license="x")
            finally:
                os.environ.pop("RESOLVE_ASSIST_OUTPUT", None)


if __name__ == "__main__":
    unittest.main()
