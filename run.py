"""Portable LINE sticker harness: assemble approved frames, review, package.

No image generation API is invoked. Private references and captions are inputs.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import itertools
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts" / "tools"))
# In the source repository this file lives below harness/.
if not (ROOT / "scripts").is_dir():
    sys.path.insert(0, str(ROOT.parent.parent / "scripts" / "tools"))
from line_sticker import animation_validate, motion_validate, spec, validate
from PIL import Image

GATES = ("identity", "anatomy", "meaning", "caption", "transparency", "all_frames", "set_variety")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def check_project(p):
    if p.get("kind") not in ("static", "animation"):
        raise ValueError("kind: static or animation required")
    count = len(p["stickers"])
    allowed = spec.ALLOWED_COUNTS if p["kind"] == "static" else spec.ALLOWED_COUNTS_ANIMATION
    if count not in allowed:
        raise ValueError(f"Invalid count {count}, expected {allowed}")
    if not p.get("metadata"):
        raise ValueError("metadata required (one or more language rows)")
    for row in p["metadata"]:
        if not row.get("language"):
            raise ValueError("metadata language required")
        for field in spec.FIELD_LIMITS:
            ok, note = spec.check_field(field, row.get(field, ""))
            if not ok:
                raise ValueError(f"{row['language']} {field}: {note}")


def names(p):
    return [f"{i:02}.png" for i in range(1, len(p["stickers"]) + 1)] + ["main.png", "tab.png"]


def init(path, kind, count):
    if not kind or count not in (spec.ALLOWED_COUNTS if kind == "static" else spec.ALLOWED_COUNTS_ANIMATION):
        raise ValueError("init requires --kind static|animation and an allowed --count")
    if path.exists():
        raise ValueError("Project already exists")
    def row(key):
        if kind == "static" or key == "tab":
            return {"source": f"frames/{key}.png", "caption": ""}
        return {"frames": [f"frames/{key}_{i:02}.png" for i in range(1,21)],
                "durations_ms": [150]*20, "loops": 1, "caption": ""}
    p = {"kind":kind, "theme_evidence":"", "metadata":[{"language":"Japanese", **{f:"" for f in spec.FIELD_LIMITS}}],
         "stickers":[row(f"{i:02}") for i in range(1,count+1)], "main":row("main"), "tab":row("tab")}
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path,p)
    print("Created plan template. Fill metadata/captions, generate and approve all required frame files.")


def assemble(base, p):
    out = base / "submit"
    if out.exists():
        raise ValueError("submit already exists; preserve previous work and choose a new project directory")
    out.mkdir()
    rows = list(zip(names(p)[:-2], p["stickers"])) + [("main.png", p["main"]), ("tab.png", p["tab"])]
    for name, row in rows:
        if p["kind"] == "static" or name == "tab.png":
            source = base / row["source"]
            with Image.open(source) as im:
                if getattr(im, "n_frames", 1) != 1:
                    raise ValueError(f"{name}: static PNG required")
                im.convert("RGBA").save(out / name, dpi=(72, 72))
        else:
            frames = []
            for source in row["frames"]:
                with Image.open(base / source) as im:
                    frames.append(im.convert("RGBA").copy())
            durations = row["durations_ms"]
            if len(durations) != len(frames) or any(type(x) is not int or x <= 0 for x in durations):
                raise ValueError("One positive integer duration required per frame")
            if len({im.size for im in frames}) != 1:
                raise ValueError("All approved frames must have identical canvas size")
            from fractions import Fraction
            animation_validate.validate_total_playback([Fraction(x) for x in durations], row["loops"])
            frames[0].save(out / name, save_all=True, append_images=frames[1:], duration=durations,
                           loop=row["loops"], disposal=0, blend=0)
            actual, _ = motion_validate.decoded(out / name)
            if len(actual) != len(frames) or any(a.tobytes() != b.tobytes() for a, b in zip(actual, frames)):
                raise ValueError(f"{name}: decoded frames differ from approved inputs (possibly merged duplicates)")
    print("Assembled submit/. Next: inspect actual images, then review-template.")


def review_template(base, p):
    target = base / "visual_review.json"
    if target.exists():
        raise ValueError("visual_review.json exists; preserve it before re-review")
    save(target, {"reviewer": "", "pairs": [
        {"a": a, "b": b, "pose_distinct": None, "motion_distinct": None, "reason": ""}
        for a, b in itertools.combinations(names(p)[:-2], 2)], "items": [
        {"file": n, "sha256": sha(base / "submit" / n), "gates": {g: None for g in GATES}, "evidence": ""}
        for n in names(p)]})
    if p["kind"] == "animation":
        motion_path = base / "motion_review.json"
        if motion_path.exists():
            raise ValueError("motion_review.json exists; preserve it before re-review")
        save(motion_path, motion_validate.template(base / "submit"))
    print("Templates only. Read AGENTS.md and MOTION_QUALITY.md; inspect before filling.")


def package(base, p):
    # Invalidate earlier successful artifacts before attempting a fresh validation.
    final = base / "stickers.zip"
    table = base / "申請転記表.md"
    for previous in (final, table):
        if previous.exists():
            stale = base / "stale"
            stale.mkdir(exist_ok=True)
            shutil.move(str(previous), str(stale / (sha(previous)[:12] + "_" + previous.name)))
    check_project(p)
    out = base / "submit"
    if {x.name for x in out.iterdir()} != set(names(p)):
        raise ValueError("submit must contain exactly numbered stickers, main.png and tab.png")
    review = load(base / "visual_review.json")
    rows = review.get("items", [])
    if not review.get("reviewer") or len(rows) != len(names(p)) or {r.get("file") for r in rows} != set(names(p)):
        raise ValueError("Complete visual review required")
    for r in rows:
        if (out / r["file"]).stat().st_size > 1_000_000:
            raise ValueError(f"{r['file']}: conservative 1,000,000 byte limit exceeded")
        if r.get("sha256") != sha(out / r["file"]) or not str(r.get("evidence", "")).strip():
            raise ValueError(f"{r['file']}: stale review or missing observed evidence")
        if any(r.get("gates", {}).get(g) is not True for g in GATES):
            raise ValueError(f"{r['file']}: every visual gate must pass")
    pairs = review.get("pairs", [])
    expected = set(itertools.combinations(names(p)[:-2], 2))
    if len(pairs) != len(expected) or {(r.get("a"), r.get("b")) for r in pairs} != expected:
        raise ValueError("Review every pair of sticker poses (and animation motions)")
    for pair in pairs:
        if pair.get("pose_distinct") is not True or not str(pair.get("reason", "")).strip():
            raise ValueError("Every pair requires distinct pose and observed reason")
        if p["kind"] == "animation" and pair.get("motion_distinct") is not True:
            raise ValueError("Every animation pair requires distinct primary motion")
    if p["kind"] == "animation":
        errors, _ = motion_validate.validate(out, load(base / "motion_review.json"))
        if errors:
            raise ValueError("; ".join(errors))
    else:
        for slot in spec.slots(len(p["stickers"])):
            with Image.open(out / slot.filename) as im:
                if getattr(im, "n_frames", 1) != 1:
                    raise ValueError("Static sticker contains animation frames")
            findings = validate.check_image(str(out / slot.filename), slot)
            bad = [f.line() for f in findings if not f.ok]
            if bad:
                raise ValueError("; ".join(bad))
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names(p):
            z.write(out / n, n)
    pending = base / "stickers.pending.zip"
    pending.write_bytes(memory.getvalue())
    try:
        if p["kind"] == "animation":
            errors, _ = animation_validate.validate_zip(pending)
            if errors:
                raise ValueError("; ".join(errors))
        if pending.stat().st_size > spec.MAX_BYTES_ZIP:
            raise ValueError("ZIP exceeds size limit")
        pending.replace(final)
    finally:
        if pending.exists():
            pending.unlink()
    # Private data appears only in the user's work directory, never in distribution.
    text = "# 申請転記表\n\n## 商品情報\n\n" + json.dumps(p["metadata"], ensure_ascii=False, indent=2)
    text += "\n\n## スタンプ一覧\n\n" + "\n".join(f"- {i:02}.png: {r.get('caption', '')}" for i, r in enumerate(p["stickers"], 1))
    text += "\n\n## テーマ・根拠\n\n" + p.get("theme_evidence", "ユーザー指定。日付を使う場合は一次出典を記入")
    text += "\n\n## 提出画像\n\n" + " / ".join(names(p)) + "\n\nログイン・規約同意・審査送信は人が行う。\n"
    table.write_text(text, encoding="utf-8")
    print("PASS: stickers.zip + 申請転記表.md (keep review evidence)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "assemble", "review-template", "package"))
    parser.add_argument("project", type=Path)
    parser.add_argument("--kind", choices=("static", "animation"))
    parser.add_argument("--count", type=int, default=8)
    a = parser.parse_args(argv)
    try:
        if a.command == "init":
            init(a.project, a.kind, a.count)
            return 0
        p = load(a.project)
        if a.command != "package":
            check_project(p)
        {"assemble": assemble, "review-template": review_template, "package": package}[a.command](a.project.resolve().parent, p)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
