"""Character-independent motion review gate. Coordinates are measured by a reviewer.

Pixel difference alone cannot distinguish meaningful acting from camera shake.
This gate binds observations to decoded APNG bytes and requires body-relative
landmarks, timing coverage, and explicit visual judgements. It does not claim
automatic anatomical or semantic understanding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image

POLICY = Path(__file__).with_name("MOTION_QUALITY.md")
SCORES = ("meaning", "amplitude", "timing", "readability", "continuity", "variety")
HARD_GATES = ("identity_preserved", "props_continuous", "no_ghosting", "loop_natural",
              "not_whole_body_only", "all_frames_seen", "played_at_native_and_half_size")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(folder):
    folder = Path(folder)
    paths = sorted(folder.glob("[0-9][0-9].png"))
    if len(paths) not in (8, 16, 24) or [p.name for p in paths] != [f"{i:02}.png" for i in range(1, len(paths) + 1)]:
        raise ValueError("Expected consecutive 8, 16, or 24 animation images")
    paths.append(folder / "main.png")
    return paths


def decoded(path):
    frames, durations = [], []
    with Image.open(path) as im:
        if getattr(im, "default_image", False):
            raise ValueError(f"{path.name}: separate default image is unsupported")
        for i in range(im.n_frames):
            im.seek(i)
            frames.append(im.convert("RGBA").copy())
            durations.append(float(im.info.get("duration", 0)))
    if len(frames) < 5 or any(d <= 0 for d in durations):
        raise ValueError(f"{path.name}: animated frames with positive delays required")
    return frames, durations


def template(folder):
    items = []
    for p in inventory(folder):
        frames, _ = decoded(p)
        items.append({"file": p.name, "sha256": digest(p), "body_height_px": None,
                      "primary_part": "", "action_read": "", "distinct_pose_frames": [],
                      "landmarks": [{"frame": i + 1, "body": None, "primary": None} for i in range(len(frames))],
                      "scores": {k: None for k in SCORES},
                      "gates": {k: None for k in HARD_GATES}, "evidence": ""})
    return {"version": "motion-v1", "required_read": "MOTION_QUALITY.md", "policy_sha256": digest(POLICY),
            "reviewer": "", "items": items}


def measure(item, size, durations):
    height = item["body_height_px"]
    if type(height) not in (float, int) or not math.isfinite(height) or not 0 < height <= size[1]:
        raise ValueError("body_height_px must be the visible character height in frame 1")
    rows = item["landmarks"]
    if [r["frame"] for r in rows] != list(range(1, len(durations) + 1)):
        raise ValueError("Measure body and primary landmark on EVERY decoded frame")
    relative = []
    for row in rows:
        for key in ("body", "primary"):
            xy = row[key]
            if not isinstance(xy, list) or len(xy) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in xy):
                raise ValueError("Landmarks must be finite [x,y] coordinates")
            if not (0 <= xy[0] < size[0] and 0 <= xy[1] < size[1]):
                raise ValueError("Landmark outside canvas")
        relative.append(tuple((a - b) / height for a, b in zip(row["primary"], row["body"])))
    excursion = max(math.dist(a, b) for a in relative for b in relative)
    # Attribute each interval to the outgoing frame; closing hold counts as hold.
    active_ms = sum(durations[i] for i in range(len(relative) - 1)
                    if math.dist(relative[i], relative[i + 1]) >= .015)
    return {"relative_excursion": excursion, "active_time_ratio": active_ms / sum(durations)}


def validate(folder, review):
    errors, metrics = [], {}
    if review.get("version") != "motion-v1" or review.get("policy_sha256") != digest(POLICY):
        errors.append("Read current MOTION_QUALITY.md and recreate review template")
    if not str(review.get("reviewer", "")).strip():
        errors.append("Missing reviewer")
    paths = inventory(folder)
    items = review.get("items", [])
    if len(items) != len(paths) or {it.get("file") for it in items} != {p.name for p in paths}:
        return errors + ["Review file set differs from complete submit set including Main"], metrics
    by_name = {it["file"]: it for it in items}
    for path in paths:
        item = by_name[path.name]
        try:
            if item.get("sha256") != digest(path):
                raise ValueError("Review SHA differs from final APNG")
            frames, durations = decoded(path)
            m = measure(item, frames[0].size, durations)
            metrics[path.name] = m
            if m["relative_excursion"] < .12:
                raise ValueError("Body-relative primary motion <12% character height; redraw key poses")
            if m["active_time_ratio"] < .40:
                raise ValueError("Active motion occupies <40% playback; revise holds/in-betweens")
            poses = item.get("distinct_pose_frames", [])
            if len(set(poses)) < 3 or any(type(n) is not int or not 1 <= n <= len(frames) for n in poses):
                raise ValueError("Specify at least 3 visually distinct articulated pose frames")
            values = [item.get("scores", {}).get(k) for k in SCORES]
            if any(type(v) is not int or not 1 <= v <= 2 for v in values) or sum(values) < 10:
                raise ValueError("Six visual scores must each be 1..2 and total >=10/12")
            if any(item.get("gates", {}).get(k) is not True for k in HARD_GATES):
                raise ValueError("Every hard visual gate must be true")
            if any(not str(item.get(k, "")).strip() for k in ("primary_part", "action_read", "evidence")):
                raise ValueError("Record actual primary part, observed action, and frame-specific evidence")
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    return errors, metrics


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("submit", type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--template", type=Path)
    g.add_argument("--review", type=Path)
    a = p.parse_args(argv)
    try:
        if a.template:
            if a.template.exists():
                raise ValueError("Refusing to overwrite existing review; choose a new path")
            a.template.write_text(json.dumps(template(a.submit), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Read {POLICY}; fill {a.template}. This is NOT a PASS.")
            return 0
        errors, metrics = validate(a.submit, json.loads(a.review.read_text(encoding="utf-8")))
        print(json.dumps({"status": "FAIL" if errors else "PASS", "errors": errors, "metrics": metrics}, ensure_ascii=False, indent=2))
        return int(bool(errors))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
