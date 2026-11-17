import unittest

from resolve_assist.analyze import analyze_pixels
from resolve_assist.color.cdl import CDL, luma
from resolve_assist.color.correct import auto_balance, match_shot, verify
from resolve_assist.color.looks import LOOKS, _s_curve, look_transform
from resolve_assist.color.lut import LUT3D
from resolve_assist.analyze import analyze_image
from resolve_assist.imaging.png import Image

from helpers import scene


def stats_for(pixels, w=96, h=64):
    return analyze_image(Image(w, h, pixels, w, h))


class CDLTests(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(CDL().apply((0.2, 0.5, 0.9)), (0.2, 0.5, 0.9))

    def test_sop_math(self):
        cdl = CDL.make(slope=2.0, offset=0.1, power=2.0)
        r, g, b = cdl.apply((0.2, 0.2, 0.2))
        self.assertAlmostEqual(r, (0.2 * 2 + 0.1) ** 2)

    def test_clamp_before_power(self):
        self.assertEqual(CDL.make(offset=-0.5).apply((0.1, 0.1, 0.1)), (0.0, 0.0, 0.0))

    def test_saturation_zero_is_luma(self):
        r, g, b = CDL.make(saturation=0.0).apply((0.8, 0.2, 0.1))
        y = luma(0.8, 0.2, 0.1)
        for v in (r, g, b):
            self.assertAlmostEqual(v, y)

    def test_parsing_and_validation(self):
        self.assertEqual(CDL.make(slope="1.1, 1.0 0.9").slope, (1.1, 1.0, 0.9))
        self.assertEqual(CDL.make(offset="-0.01").offset, (-0.01, -0.01, -0.01))
        with self.assertRaises(ValueError):
            CDL.make(slope=[1, 2])
        with self.assertRaises(ValueError):
            CDL.make(power=0.0)
        with self.assertRaises(ValueError):
            CDL.make(slope=float("nan"))

    def test_blend(self):
        half = CDL.make(slope=2.0, saturation=0.0).blend(0.5)
        self.assertAlmostEqual(half.slope[0], 1.5)
        self.assertAlmostEqual(half.saturation, 0.5)
        self.assertTrue(CDL.make(slope=3.0).blend(0.0).is_identity())

    def test_resolve_strings_and_cc(self):
        cdl = CDL.make(slope=(1.1, 1, 0.9))
        self.assertEqual(cdl.resolve_strings()["Slope"], "1.1000 1.0000 0.9000")
        self.assertIn("<Slope>1.1000 1.0000 0.9000</Slope>", cdl.to_cc_xml())


class LUTTests(unittest.TestCase):
    def test_identity_lookup(self):
        lut = LUT3D.identity(17)
        for rgb in ((0.0, 0.0, 0.0), (0.33, 0.66, 0.12), (1.0, 1.0, 1.0)):
            for a, b in zip(lut.lookup(rgb), rgb):
                self.assertAlmostEqual(a, b, places=6)

    def test_roundtrip_and_order(self):
        lut = LUT3D.from_transform(lambda c: (c[0], 0.0, 0.0), 17, title='x"y')
        text = lut.to_cube()
        self.assertIn("LUT_3D_SIZE 17", text)
        back = LUT3D.parse(text)
        self.assertEqual(back.size, 17)
        # red varies fastest: second data row has r = 1/16
        self.assertAlmostEqual(back.table[1][0], 1 / 16, places=5)
        self.assertNotIn('x"y', text)

    def test_lut_matches_transform(self):
        cdl = CDL.make(slope=(1.2, 1.0, 0.8), power=1.1, saturation=0.8)
        lut = LUT3D.from_transform(cdl.apply, 33)
        for rgb in ((0.25, 0.5, 0.75), (0.9, 0.1, 0.4)):
            for a, b in zip(lut.lookup(rgb), cdl.apply(rgb)):
                self.assertAlmostEqual(a, b, delta=0.01)

    def test_parse_rejects_bad(self):
        for bad in ("LUT_3D_SIZE 2\n0 0 0\n", "0 0 0\n", "LUT_1D_SIZE 4\n", "LUT_3D_SIZE 2\n" + "nan 0 0\n" * 8):
            with self.assertRaises(ValueError):
                LUT3D.parse(bad)

    def test_size_allowlist(self):
        with self.assertRaises(ValueError):
            LUT3D.from_transform(lambda c: c, 9)


class CorrectionTests(unittest.TestCase):
    def test_balance_removes_cast(self):  # success criterion S3
        w, h, px = scene(cast=(1.15, 1.0, 0.82))
        stats = stats_for(px)
        self.assertGreater(max(abs(v) for v in stats.cast.values()), 0.05)
        cdl = auto_balance(stats, fix_exposure=False, fix_blacks=False)
        after = verify(cdl, px)
        self.assertLess(max(abs(v) for v in after["cast_after"].values()), 0.02)

    def test_balance_brightens_underexposed_without_clipping(self):
        w, h, px = scene(gain=0.45)
        stats = stats_for(px)
        cdl = auto_balance(stats)
        after = verify(cdl, px)
        self.assertGreater(after["median_luma_after"], stats.luma.p50 * 1.3)
        self.assertLess(after["clip_white_pct_after"], 1.0)

    def test_match(self):  # success criterion S4
        _, _, ref = scene(cast=(1.1, 1.0, 0.9), seed=1)
        _, _, src = scene(cast=(0.9, 1.0, 1.15), gain=0.7, seed=2)
        cdl = match_shot(stats_for(src), stats_for(ref))
        matched = analyze_pixels([cdl.apply(p) for p in src])
        target = analyze_pixels(ref)
        for ch in ("red", "green", "blue"):
            self.assertAlmostEqual(matched[ch].mean, target[ch].mean, delta=0.03)


class LookTests(unittest.TestCase):
    def test_s_curve_fixed_points_and_monotonic(self):
        for amount in (0.2, 0.6):
            self.assertAlmostEqual(_s_curve(0.0, amount, 0.435), 0.0)
            self.assertAlmostEqual(_s_curve(1.0, amount, 0.435), 1.0)
            self.assertAlmostEqual(_s_curve(0.435, amount, 0.435), 0.435)
            vals = [_s_curve(i / 100, amount, 0.435) for i in range(101)]
            self.assertEqual(vals, sorted(vals))

    def test_looks_stay_in_range_and_zero_strength_is_identity(self):
        for look in LOOKS.values():
            fn = look_transform(look, 1.0)
            for rgb in ((0, 0, 0), (1, 1, 1), (0.9, 0.1, 0.5)):
                self.assertTrue(all(0.0 <= v <= 1.0 for v in fn(rgb)))
            ident = look_transform(look, 0.0)
            for a, b in zip(ident((0.3, 0.5, 0.7)), (0.3, 0.5, 0.7)):
                self.assertAlmostEqual(a, b, places=6)

    def test_bw_is_gray(self):
        r, g, b = look_transform(LOOKS["bw-contrast"])((0.8, 0.3, 0.1))
        self.assertAlmostEqual(r, g, places=6)
        self.assertAlmostEqual(g, b, places=6)


if __name__ == "__main__":
    unittest.main()


class BorderTests(unittest.TestCase):
    def test_pillarbox_is_cropped(self):
        from resolve_assist.analyze import crop_borders
        w, h, px = scene(40, 60)
        W = 120  # 40-px picture centered in a 120-px wide black frame
        framed = []
        for y in range(h):
            framed += [(0.0, 0.0, 0.0)] * 40 + px[y * w:(y + 1) * w] + [(0.0, 0.0, 0.0)] * 40
        img, info = crop_borders(Image(W, h, framed, 1920, 960))
        self.assertEqual((img.width, img.height), (40, 60))
        self.assertEqual(info["kind"], "pillarbox")
        self.assertEqual(info["picture_size_estimate"], [640, 960])
        stats = analyze_image(Image(W, h, framed, W, h))
        self.assertLess(stats.clip_black_pct, 5)
        self.assertTrue(stats.warnings[0].startswith("ignored black bars"))

    def test_dark_scene_is_not_cropped(self):
        from resolve_assist.analyze import crop_borders
        dark = [(0.005, 0.005, 0.005)] * (50 * 50)
        img, info = crop_borders(Image(50, 50, dark, 50, 50))
        self.assertIsNone(info)
        self.assertEqual(img.width, 50)


class LookCDLTests(unittest.TestCase):
    def test_look_as_cdl_tracks_the_look(self):
        from resolve_assist.color.looks import look_as_cdl
        look = LOOKS["warm-film"]
        cdl = look_as_cdl(look, 1.0)
        fn = look_transform(look, 1.0)
        for v in (0.25, 0.5, 0.75):
            for a, b in zip(cdl.apply((v, v, v)), fn((v, v, v))):
                self.assertAlmostEqual(a, b, delta=0.05)
        self.assertGreater(cdl.slope[0], cdl.slope[2])  # warm: more red than blue

    def test_compose_is_sequential_application(self):
        from resolve_assist.color.looks import compose
        a = CDL.make(slope=(1.1, 1.0, 0.9), offset=0.02)
        b = CDL.make(slope=1.05, offset=-0.01, saturation=1.2)
        c = compose(a, b)
        x = (0.3, 0.5, 0.6)
        for u, v in zip(c.apply(x), b.apply(a.apply(x))):
            self.assertAlmostEqual(u, v, places=6)
        with self.assertRaises(ValueError):
            compose(CDL.make(power=1.2), b)


class AudioTests(unittest.TestCase):
    def test_preset_wav(self):
        import tempfile, wave
        from pathlib import Path
        from resolve_assist.audio import generate
        with tempfile.TemporaryDirectory() as tmp:
            out = generate("calm-lofi", 2.0, Path(tmp) / "m.wav")
            with wave.open(out["path"]) as w:
                self.assertEqual((w.getnchannels(), w.getframerate()), (2, 44100))
                self.assertAlmostEqual(w.getnframes() / 44100, 2.0, places=2)
        with self.assertRaises(ValueError):
            generate("nope", 2.0, Path("/tmp/x.wav"))
