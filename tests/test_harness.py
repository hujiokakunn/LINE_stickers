"""Clean export smoke tests. Synthetic source images only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run.py"
if not RUN.is_file():
    RUN = Path(__file__).with_name("run.py")
loader = importlib.util.spec_from_file_location("public_harness", RUN)
h = importlib.util.module_from_spec(loader)
loader.loader.exec_module(h)


class HarnessTests(unittest.TestCase):
    def test_init_generates_complete_frame_lists(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"project.json"
            self.assertEqual(h.main(["init",str(path),"--kind","animation","--count","8"]),0)
            plan=h.load(path)
            self.assertEqual(len(plan["stickers"]),8)
            self.assertEqual(len(plan["main"]["frames"]),20)
            self.assertEqual(sum(plan["main"]["durations_ms"]),3000)
            with self.assertRaises(ValueError):
                h.check_project(plan)  # blank metadata must be completed by the user

    def test_static_complete_flow_and_stale_review_block(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for n, size in (("art.png", (370, 320)), ("main.png", (240, 240)), ("tab.png", (96, 74))):
                im = Image.new("RGBA", size)
                ImageDraw.Draw(im).ellipse((20, 20, size[0]-20, size[1]-20), fill="blue")
                im.save(base/n, dpi=(72,72))
            project = {"kind": "static", "metadata": [{"language":"English", "creator_name":"Test", "title":"Test", "description":"Synthetic test", "copyright":"Test"}],
                       "stickers":[{"source":"art.png"} for _ in range(8)], "main":{"source":"main.png"}, "tab":{"source":"tab.png"}}
            h.check_project(project)
            h.assemble(base, project)
            h.review_template(base, project)
            with self.assertRaises(ValueError):
                h.package(base, project)
            review = h.load(base/"visual_review.json")
            review["reviewer"] = "synthetic fixture (not a real product review)"
            for r in review["items"]:
                r["gates"] = {g:True for g in h.GATES}
                r["evidence"] = "test-only synthetic approval"
            for pair in review["pairs"]:
                pair.update(pose_distinct=True, reason="test fixture")
            h.save(base/"visual_review.json", review)
            h.package(base, project)
            self.assertTrue((base/"stickers.zip").is_file())
            (base/"submit/main.png").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                h.package(base, project)
            self.assertFalse((base/"stickers.zip").exists())

    def test_animation_flow_requires_motion_and_rejects_tiny_movement(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            def sequence(prefix, size):
                paths = []
                for i, x in enumerate((60, 75, 90, 75, 60)):
                    im = Image.new("RGBA", size)
                    draw = ImageDraw.Draw(im)
                    draw.rectangle((100, 70, 160, 170), fill="blue")
                    draw.line((100, 100, x, 90), fill="black", width=6)
                    name = f"{prefix}_{i}.png"
                    im.save(base/name)
                    paths.append(name)
                return {"frames": paths, "durations_ms": [200]*5, "loops": 1}
            body = sequence("body", (320, 270))
            main = sequence("main", (240, 240))
            tab = Image.new("RGBA", (96,74))
            ImageDraw.Draw(tab).ellipse((20,10,75,65),fill="blue")
            tab.save(base/"tab.png")
            p = {"kind":"animation", "metadata":[{"language":"English", "creator_name":"Test", "title":"Test", "description":"Synthetic", "copyright":"Test"}],
                 "stickers":[body.copy() for _ in range(8)], "main":main, "tab":{"source":"tab.png"}}
            h.assemble(base,p)
            h.review_template(base,p)
            r = h.load(base/"visual_review.json")
            r["reviewer"]="synthetic test"
            for item in r["items"]:
                item["gates"]={g:True for g in h.GATES}
                item["evidence"]="synthetic protocol fixture"
            for pair in r["pairs"]:
                pair.update(pose_distinct=True,motion_distinct=True,reason="synthetic protocol fixture")
            h.save(base/"visual_review.json",r)
            with self.assertRaises(ValueError):
                h.package(base,p)
            m=h.load(base/"motion_review.json")
            m["reviewer"]="synthetic test"
            for item in m["items"]:
                item.update(body_height_px=100,primary_part="arm tip",action_read="arm waves",distinct_pose_frames=[1,2,3],evidence="drawn arm tip at x=60/75/90")
                item["scores"]={k:2 for k in h.motion_validate.SCORES}
                item["gates"]={k:True for k in h.motion_validate.HARD_GATES}
                item["landmarks"]=[{"frame":i+1,"body":[130,120],"primary":[x,90]} for i,x in enumerate((60,75,90,75,60))]
            h.save(base/"motion_review.json",m)
            h.package(base,p)
            self.assertTrue((base/"stickers.zip").exists())
            for row in m["items"][0]["landmarks"]:
                row["primary"]=[60,90]
            h.save(base/"motion_review.json",m)
            with self.assertRaises(ValueError):
                h.package(base,p)
            self.assertFalse((base/"stickers.zip").exists())


if __name__ == "__main__":
    unittest.main()
