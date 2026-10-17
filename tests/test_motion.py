"""Synthetic APNG motion-gate regressions; contains no character assets."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw

# Works both in the Vault and in a clean exported distribution.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "tools"))
from line_sticker import motion_validate as motion


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        frames = []
        for x in (60, 75, 90, 75, 60):
            im = Image.new("RGBA", (320, 270))
            d = ImageDraw.Draw(im)
            d.rectangle((90, 70, 160, 170), fill="blue")
            d.ellipse((x, 90, x + 10, 100), fill="red")
            frames.append(im)
        frames[0].save(self.folder / "01.png", save_all=True, append_images=frames[1:],
                       duration=200, loop=1, disposal=0, blend=0)
        for n in [f"{i:02}.png" for i in range(2, 9)] + ["main.png"]:
            (self.folder / n).write_bytes((self.folder / "01.png").read_bytes())
        self.review = motion.template(self.folder)
        self.review["reviewer"] = "synthetic test observer"
        for item in self.review["items"]:
            item.update(body_height_px=100, primary_part="test arm", action_read="arm moves horizontally",
                        distinct_pose_frames=[1, 2, 3], evidence="frames 1,2,3: arm changes position relative to body")
            item["scores"] = {k: 2 for k in motion.SCORES}
            item["gates"] = {k: True for k in motion.HARD_GATES}
            item["landmarks"] = [{"frame": i + 1, "body": [125, 120], "primary": [x + 5, 95]}
                                 for i, x in enumerate((60, 75, 90, 75, 60))]

    def test_clear_articulation_passes(self):
        errors, metrics = motion.validate(self.folder, self.review)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(metrics["main.png"]["relative_excursion"], .3)
        self.assertAlmostEqual(metrics["main.png"]["active_time_ratio"], .8)

    def test_unfilled_template_is_rejected(self):
        self.assertTrue(motion.validate(self.folder, motion.template(self.folder))[0])

    def test_whole_body_translation_has_zero_relative_motion(self):
        row = self.review["items"][0]
        row["landmarks"] = [{"frame": i + 1, "body": [100 + i * 10, 120], "primary": [80 + i * 10, 95]} for i in range(5)]
        errors, metrics = motion.validate(self.folder, self.review)
        self.assertEqual(metrics["01.png"]["relative_excursion"], 0)
        self.assertTrue(any("<12%" in e for e in errors))

    def test_tiny_motion_fails_even_with_twenty_frames_claim(self):
        item = self.review["items"][0]
        for i, row in enumerate(item["landmarks"]):
            row["primary"] = [80 + i, 95]
        self.assertTrue(any("<12%" in e for e in motion.validate(self.folder, self.review)[0]))

    def test_hold_heavy_animation_fails_duration_ratio(self):
        item = copy.deepcopy(self.review["items"][0])
        m = motion.measure(item, (320, 270), [10, 10, 10, 10, 960])
        self.assertAlmostEqual(m["active_time_ratio"], .04)

    def test_missing_frames_nan_and_stale_sha_rejected(self):
        for mutation in ("missing", "nan", "sha", "policy", "main", "zero_score", "hard_gate"):
            with self.subTest(mutation=mutation):
                r = copy.deepcopy(self.review)
                item = r["items"][0]
                if mutation == "missing": item["landmarks"].pop()
                if mutation == "nan": item["landmarks"][0]["primary"][0] = float("nan")
                if mutation == "sha": item["sha256"] = "stale"
                if mutation == "policy": r["policy_sha256"] = "stale"
                if mutation == "main": r["items"].pop()
                if mutation == "zero_score": item["scores"]["meaning"] = 0
                if mutation == "hard_gate": item["gates"]["no_ghosting"] = False
                self.assertTrue(motion.validate(self.folder, r)[0])


if __name__ == "__main__":
    unittest.main()
