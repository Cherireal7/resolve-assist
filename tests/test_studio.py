"""Expanded library (SFX, sequenced music, browser), editor choice and project kits."""

from __future__ import annotations

import json
import os
import shutil
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
        from resolve_assist.library import sfx_tactile
        names = [*sfx.RECIPES, *sfx_ui.RECIPES, *sfx_cine.RECIPES, *sfx_tactile.RECIPES]
        for name, (fn, kw, tags, usage) in sfx_tactile.RECIPES.items():
            left, right = fn(**kw)
            self.assertGreater(max(map(abs, left)), 0.01, name)
            self.assertEqual(len(left), len(right))
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

    def test_commons_download_takes_a_standard_thumbnail_below_the_original(self):
        import tempfile, urllib.parse
        from resolve_assist import commons
        asked = []
        def fake(url, binary=False, tries=4):
            if binary:
                return b"\xff\xd8data", "image/jpeg"
            step = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["iiurlwidth"][0])
            asked.append(step)
            return {"query": {"pages": {"1": {"title": "File:X.jpg", "imageinfo": [{"descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
                "mime": "image/jpeg", "width": 1920, "height": 1080, "thumburl": f"https://upload.wikimedia.org/x/{step}px-X.jpg",
                "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]}}}}
        real = commons._get
        commons._get = fake
        try:
            with tempfile.TemporaryDirectory() as d:
                res = commons.fetch("File:X.jpg", Path(d))
                self.assertTrue(Path(res["path"]).is_file())
        finally:
            commons._get = real
        self.assertEqual(asked, [1920, 1280])          # 1920 would be the original itself, so the next step down is used

    def test_cutout_checks_its_input_and_carries_the_credit_over(self):
        from resolve_assist import workspace
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("RESOLVE_ASSIST_OUTPUT")
            os.environ["RESOLVE_ASSIST_OUTPUT"] = d
            try:
                proj = Path(workspace.new_project("Cut Test")["project"])
                self.assertTrue(str(proj.resolve()).startswith(str(Path(d).resolve())))   # never the real workspace
                (proj / "stills" / "cat.png").write_bytes(b"\x89PNG fake")
                (proj / "docs" / "notes.txt").write_text("x")
                workspace.project_index("Cut Test")
                workspace.project_credit("Cut Test", "stills/cat.png", "https://example.org/cat", "CC0", "A. Author")
                with self.assertRaises(ValueError):
                    workspace.project_cutout("Cut Test", "missing.png")
                with self.assertRaises(ValueError):
                    workspace.project_cutout("Cut Test", "notes.txt")
                with self.assertRaises(ValueError):
                    workspace.project_cutout("Cut Test", "cat.png", roi="0.9,0,0.1,1")
                with self.assertRaises(ValueError):
                    workspace.project_cutout("Cut Test", "cat.png", pick="1;rm")
                seen = {}
                def fake(picture, out_dir, stem, options):
                    seen["options"] = options
                    for part in ("fg", "bg", "mask"):
                        (out_dir / f"{stem}-{part}.png").write_bytes(b"\x89PNG fake")
                    return "instance 1: 40.0% of the frame, box x 0.10-0.90 y 0.20-1.00\nwrote\n"
                real = workspace._run_subject
                workspace._run_subject = fake
                try:
                    res = workspace.project_cutout("Cut Test", "cat.png", roi="0.5,0.3,1,0.95", fill_black=True)
                finally:
                    workspace._run_subject = real
                self.assertEqual(res["subject"], "stills/layers/cat-fg.png")
                self.assertEqual(len(res["found"]), 1)
                self.assertIn("--fill-black", seen["options"])
                self.assertEqual(seen["options"][:2], ["--roi", "0.5000,0.3000,1.0000,0.9500"])
                data = json.loads((proj / "project.json").read_text())
                layer = next(e for e in data["files"] if e["file"] == "stills/layers/cat-fg.png")
                self.assertEqual((layer["license"], layer["author"]), ("CC0", "A. Author"))
            finally:
                if old is None:
                    os.environ.pop("RESOLVE_ASSIST_OUTPUT", None)
                else:
                    os.environ["RESOLVE_ASSIST_OUTPUT"] = old

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


class EditorSupportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_peaks_follow_the_sound_and_are_cached(self):
        from resolve_assist import api
        with tempfile.TemporaryDirectory() as d:
            os.environ["RESOLVE_ASSIST_OUTPUT"] = d
            try:
                p = Path(d) / "tone.wav"
                generate("ambient", 3.0, p)
                first = api.media_peaks(str(p), 20)
                self.assertAlmostEqual(first["duration"], 3.0, delta=0.05)
                self.assertAlmostEqual(len(first["peaks"]) / first["per_second"], 3.0, delta=0.1)
                self.assertEqual(max(first["peaks"]), 1.0)
                self.assertLess(first["peaks"][0], first["peaks"][len(first["peaks"]) // 2])   # the track fades in
                self.assertEqual(len(list((Path(d) / "cache" / "peaks").glob("*.json"))), 1)
                self.assertEqual(api.media_peaks(str(p), 20), first)
            finally:
                os.environ.pop("RESOLVE_ASSIST_OUTPUT", None)

    def test_look_curves_describe_each_look(self):
        from resolve_assist import api
        looks = api.look_curves()["looks"]
        self.assertIn("golden-hour", looks)
        bw, warm = looks["bw-contrast"], looks["golden-hour"]
        self.assertEqual(bw["saturation"], 0.0)
        self.assertEqual(len(warm["r"]), 17)
        self.assertGreater(warm["r"][12], warm["b"][12])          # warm look: more red than blue in the highlights
        self.assertTrue(all(b >= a for a, b in zip(warm["g"], warm["g"][1:])))   # monotonic tone curve


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class HandoffTests(unittest.TestCase):
    def test_layers_timeline_and_readme_are_written(self):
        import subprocess
        import xml.dom.minidom
        from resolve_assist import handoff
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "My Video"
            for sub in ("footage", "stills", "music"):
                (proj / sub).mkdir(parents=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=180x320:r=30:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                            "-pix_fmt", "yuv420p", "-shortest", str(proj / "footage" / "a.mp4")], check=True)
            (proj / "stills" / "p.png").write_bytes(encode_png_1x1())
            generate("ambient", 4.0, proj / "music" / "m.wav")
            pre = "projects/my-video/"
            media = lambda i, kind, src, start, length, **kw: {"id": i, "kind": kind, "src": pre + src, "start": start, "length": length, "in": 0, "volume": 1,
                                                              "fit": "cover", "scale": 1, "x": 0, "y": 0, "opacity": 1, "zoom": 0, **kw}
            doc = {"version": 1, "duration": 4, "background": "#000000", "credit": "Edit by Cheri", "tracks": [
                {"id": "text", "name": "Text", "kind": "text", "clips": [{"id": "t1", "kind": "text", "text": "Hello", "start": 0.5, "length": 2, "style": "headline", "motion": "rise", "size": 8, "color": "#fff", "accent": "#f80", "x": 50, "y": 30, "align": "center"}]},
                {"id": "video", "name": "Video", "kind": "video", "clips": [media("v1", "video", "footage/a.mp4", 0, 2, **{"in": 0.5}), media("v2", "image", "stills/p.png", 2, 2, look="golden-hour", lookStrength=0.6),
                                                                              media("v3", "image", "stills/p.png", 1, 2)]},
                {"id": "music", "name": "Music", "kind": "audio", "clips": [{"id": "m1", "kind": "audio", "src": pre + "music/m.wav", "start": 0, "length": 9, "in": 0, "volume": 0.4, "fadeIn": 0.2, "fadeOut": 1}]}]}
            (proj / "edit.json").write_text(json.dumps(doc))
            res = handoff.build(proj, "9x16", None)
            out = proj / "handoff"
            self.assertEqual(res["counts"], {"audio": 1, "video": 1, "image": 2})
            self.assertEqual(len(list((out / "video").iterdir())), 3)
            self.assertEqual(len(list((out / "looks").glob("*.cube"))), 1)
            self.assertTrue(any("not rendered" in n for n in res["notes"]) and any("credit" in n for n in res["notes"]))
            otio = json.loads((out / "timeline.otio").read_text())
            names = [t["name"] for t in otio["tracks"]["children"]]
            self.assertEqual(names, ["Video", "Video 2", "Music"])                 # the overlapping still gets its own lane
            first = otio["tracks"]["children"][0]["children"]
            self.assertEqual([k["OTIO_SCHEMA"] for k in first], ["Clip.2", "Clip.2"])
            self.assertEqual(first[0]["source_range"]["duration"]["value"], 60.0)
            music = otio["tracks"]["children"][2]["children"][0]
            self.assertEqual(music["source_range"]["duration"]["value"], 120.0)    # cut at the video's end
            xml.dom.minidom.parse(str(out / "timeline.fcpxml"))                    # well-formed
            readme = (out / "README.md").read_text()
            self.assertIn("looks/", readme)
            self.assertIn("fade out 1s", readme)
            self.assertEqual(json.loads((out / "text" / "titles.json").read_text())[0]["text"], "Hello")
            doc["tracks"][1]["clips"][0]["src"] = "projects/other/x.mp4"
            (proj / "edit.json").write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                handoff.build(proj, "9x16", None)


class CapCutDraftTests(unittest.TestCase):
    def test_writes_only_a_new_marked_draft_from_a_template(self):
        from unittest import mock
        from resolve_assist import capcut
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            root = home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
            tpl = root / "mine"
            tpl.mkdir(parents=True)
            template = {"canvas_config": {"width": 1920, "height": 1080, "ratio": "original"}, "duration": 0, "fps": 30.0, "id": "X", "name": "", "version": 360000,
                        "new_version": "191.0.0", "platform": {"app_version": "9.7.1"}, "tracks": [],
                        "materials": {"videos": [], "audios": [], "speeds": [], "canvases": [], "sound_channel_mappings": [], "audio_fades": [], "texts": []}}
            (tpl / "draft_info.json").write_text(json.dumps(template))
            (tpl / "draft_meta_info.json").write_text(json.dumps({"draft_name": "mine", "draft_id": "A"}))
            hand = home / "handoff"
            for sub in ("video", "audio"):
                (hand / sub).mkdir(parents=True)
            (hand / "video" / "01-p.png").write_bytes(encode_png_1x1())
            generate("ambient", 2.0, hand / "audio" / "02-m.wav")
            (hand / "manifest.json").write_text(json.dumps({"project": "P", "format": "9x16", "size": [1080, 1920], "fps": 30, "duration": 2, "notes": [], "items": [
                {"file": "video/01-p.png", "kind": "image", "track": "Video", "start": 0, "length": 2, "fit": "cover", "scale": 1, "opacity": 1},
                {"file": "audio/02-m.wav", "kind": "audio", "track": "Music", "start": 0, "length": 2, "volume": 0.4, "fadeOut": 1}]}))
            with mock.patch.object(Path, "home", return_value=home), mock.patch.object(capcut, "capcut_running", return_value=False):
                res = capcut.build_draft(hand, "Tibeb P")
                draft = Path(res["draft"])
                info = json.loads((draft / "draft_info.json").read_text())
                self.assertEqual((info["version"], info["platform"]["app_version"]), (360000, "9.7.1"))     # format fields come from the template
                self.assertEqual(info["canvas_config"]["ratio"], "9:16")
                self.assertEqual([(t["type"], len(t["segments"])) for t in info["tracks"]], [("video", 1), ("audio", 1)])
                seg = info["tracks"][0]["segments"][0]
                self.assertEqual(seg["target_timerange"], {"duration": 2000000, "start": 0})
                self.assertGreater(seg["clip"]["scale"]["x"], 1.0)                                          # square still must fill a 9:16 frame
                self.assertEqual(info["tracks"][1]["segments"][0]["volume"], 0.4)
                self.assertEqual(info["materials"]["audio_fades"][0]["fade_out_duration"], 1000000)
                self.assertTrue(Path(info["materials"]["videos"][0]["path"]).is_file())                     # media copied into the draft
                self.assertTrue((draft / capcut.MARKER).is_file())
                self.assertEqual(json.loads((tpl / "draft_info.json").read_text()), template)               # the template is untouched
                second = capcut.build_draft(hand, "Tibeb P")
                self.assertNotEqual(second["draft"], res["draft"])                                          # never overwrites
                self.assertEqual(capcut.find_template().name, "mine")                                       # our drafts are never used as template
                self.assertEqual(sorted(capcut.remove()["removed"]), ["Tibeb P", "Tibeb P 2"])
                self.assertTrue(tpl.is_dir())
            (hand / "text").mkdir()
            (hand / "text" / "titles.json").write_text(json.dumps([{"id": "t1", "text": "ሰላም Hi", "start": 0.5, "length": 1, "size": 8, "color": "#F5C451", "x": 50, "y": 25, "align": "center"}]))
            with mock.patch.object(Path, "home", return_value=home), mock.patch.object(capcut, "capcut_running", return_value=True):
                res = capcut.build_draft(hand, "Tibeb P")                      # allowed while CapCut runs: it is only a new folder
                self.assertIn("Restart CapCut", res["next"])
                info = json.loads((Path(res["draft"]) / "draft_info.json").read_text())
                text_track = info["tracks"][-1]
                self.assertEqual((text_track["type"], len(text_track["segments"])), ("text", 1))
                content = json.loads(info["materials"]["texts"][0]["content"])
                self.assertEqual((content["text"], content["styles"][0]["range"]), ("ሰላም Hi", [0, 6]))
                self.assertEqual(text_track["segments"][0]["clip"]["transform"], {"x": 0.0, "y": 0.5})
                with self.assertRaises(RuntimeError):
                    capcut.remove()                                            # deleting needs CapCut closed
                # the user edits in CapCut: moves the picture, lowers the music, retypes the title
                (home / "edit.json").write_text(json.dumps({"version": 1, "duration": 2, "background": "#000", "tracks": [
                    {"id": "text", "name": "Text", "kind": "text", "clips": [{"id": "t1", "kind": "text", "text": "ሰላም Hi", "start": 0.5, "length": 1}]},
                    {"id": "video", "name": "Video", "kind": "video", "clips": [{"id": "v1", "kind": "image", "src": "x", "start": 0, "length": 2}]},
                    {"id": "music", "name": "Music", "kind": "audio", "clips": [{"id": "m1", "kind": "audio", "src": "y", "start": 0, "length": 2, "in": 0, "volume": 0.4}]}]}))
                manifest = json.loads((hand / "manifest.json").read_text())
                manifest["items"][0]["id"], manifest["items"][1]["id"] = "v1", "m1"
                (hand / "manifest.json").write_text(json.dumps(manifest))
                d2 = Path(capcut.build_draft(hand, "Tibeb Edited")["draft"])
                info = json.loads((d2 / "draft_info.json").read_text())
                info["tracks"][0]["segments"][0]["target_timerange"]["start"] = 500000
                info["tracks"][1]["segments"][0]["volume"] = 0.2
                info["tracks"][2]["segments"][0].pop("tibeb_id")                # CapCut drops fields it does not know
                info["materials"]["texts"][0]["content"] = json.dumps({"text": "New title", "styles": []})
                (d2 / "draft_info.json").write_text(json.dumps(info))
                got = capcut.pull("Tibeb Edited")
                self.assertEqual(sorted((c["clip"], c["field"], c["to"]) for c in got["changes"]), [("m1", "volume", 0.2), ("t1", "text", "New title"), ("v1", "start", 0.5)])
                self.assertEqual((got["deleted"], got["added_in_capcut"]), ([], []))
                self.assertNotIn("applied", got)
                done = capcut.pull("Tibeb Edited", apply=True)
                self.assertTrue(Path(done["backup"]).is_file())
                after = json.loads((home / "edit.json").read_text())
                self.assertEqual((after["tracks"][1]["clips"][0]["start"], after["tracks"][2]["clips"][0]["volume"], after["tracks"][0]["clips"][0]["text"]), (0.5, 0.2, "New title"))
                with self.assertRaises(ValueError):
                    capcut.pull("mine")                                        # never reads back the user's own projects


def encode_png_1x1() -> bytes:
    from resolve_assist.imaging.png import encode_png
    return encode_png(2, 2, [(1.0, 0.5, 0.2)] * 4)


if __name__ == "__main__":
    unittest.main()


class BeatGridTests(unittest.TestCase):
    def test_tempos_have_whole_frame_sixteenths(self):
        from resolve_assist import beatgrid as bg
        got = {t["bpm"]: t["sixteenth_frames"] for t in bg.tempos(60)}
        self.assertEqual({90.0: 10, 100.0: 9, 112.5: 8, 150.0: 6}, {k: got[k] for k in (90.0, 100.0, 112.5, 150.0)})
        with self.assertRaises(bg.GridError):
            bg.step_frames(60, 120.5)

    def test_plan_is_frame_exact_and_adds_silence_before_the_drop(self):
        from resolve_assist import beatgrid as bg
        p = bg.plan(60, 112.5, bg.parse_sections("intro:4,groove:3,build=spin:3,drop:2,outro:2"))
        self.assertEqual((p["sixteenth_frames"], p["bar_frames"], p["frames"]), (8, 128, 14 * 128))
        self.assertEqual([s["duration_ms"] for s in p["sections"]], [8533, 6400, 6400, 4267, 4267])
        self.assertEqual(sum(s["duration_ms"] for s in p["sections"]), round(p["frames"] / 60 * 1000))
        spin, drop = p["sections"][2], p["sections"][3]
        self.assertEqual((spin["name"], spin["kind"], spin["silence_steps"]), ("build", "spin", 4))
        silent = bg.silent_steps(p)
        self.assertEqual(silent, set(range(drop["start_step"] - 4, drop["start_step"])))
        self.assertFalse(silent & set(p["hits"]["steps"]))
        self.assertTrue(set(range(drop["start_step"], drop["start_step"] + 32)) <= set(p["hits"]["steps"]))
        self.assertEqual(len(p["music_plan"]["sections"]), 5)
        self.assertIn("GRID.t", bg.grid_js(p))

    def test_check_names_each_broken_rule(self):
        from resolve_assist import beatgrid as bg
        p = bg.plan()
        self.assertTrue(bg.check(p, bg.starter_cues(p))["ok"])
        cues = bg.starter_cues(p) + [
            {"pos": "2.1.2", "kind": "text", "text": "one two three four five"},      # empty sixteenth, too many words
            {"frame": 101, "kind": "effect"},                                          # between sixteenths
            {"section": "spin", "step": 46, "kind": "effect"},                         # in the silence
            {"pos": "3.2.1", "kind": "music-cut"},                                     # mid-bar music cut
            {"section": "intro", "step": 0, "kind": "text", "text": "hi"},             # shares the first cut's hit
        ]
        rules = [x["rule"] for x in bg.check(p, cues)["problems"]]
        for rule in ("on a hit", "few words", "on the grid", "silence", "cut on the one", "one at a time"):
            self.assertIn(rule, rules)
        gaps = bg.check(p, [c for c in bg.starter_cues(p) if c["kind"] != "slide"])["problems"]
        self.assertEqual([x["rule"] for x in gaps], ["the drop never holds"])

    def test_track_sits_on_the_grid_and_is_silent_before_the_drop(self):
        from resolve_assist import beatgrid as bg
        from resolve_assist.analysis.beats import read_wav_mono
        p = bg.plan(60, 150, bg.parse_sections("intro:1,spin:1,drop:1,outro:1"))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "t.wav"
            info = bg.render(p, out)
            self.assertEqual(info["samples"], p["frames"] * bg.RATE // 60)
            mono, rate = read_wav_mono(out)
        drop = p["sections"][2]["start_step"]
        a, b = bg.step_sample(p, drop - 4) + int(0.01 * rate), bg.step_sample(p, drop)
        self.assertLess(max(abs(x) for x in mono[a:b]), 1e-4)
        m = bg.measure(p, mono, rate)
        self.assertEqual(m["offset_ms"], 0)
        self.assertGreaterEqual(len(set(m["hits"]) & set(p["hits"]["steps"])), 0.9 * len(p["hits"]["steps"]))
        late = bg.measure(p, [0.0] * int(0.03 * rate) + mono, rate)
        self.assertEqual(late["offset_ms"], 30)
