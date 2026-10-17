# -*- coding: utf-8 -*-
r"""validate.py — 出来上がった画像とメタデータを、申請前に機械で全数検査する。

**通ったものだけを ZIP に入れる**。1件でも落ちたら ZIP を作らない（黙って不備を通さない）。
検査は spec.py の値だけを見る——ここに数値を写さない。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import compose, spec


@dataclass
class Finding:
    target: str
    ok: bool
    detail: str

    def line(self) -> str:
        return "{} {}: {}".format("OK  " if self.ok else "NG  ", self.target, self.detail)


def _margin_for(slot: spec.Slot) -> int:
    if slot.key == "tab":
        return spec.TAB_MARGIN_PX
    if slot.key == "main":
        return spec.MAIN_MARGIN_PX
    return spec.MARGIN_PX


def check_image(path: str, slot: spec.Slot) -> list[Finding]:
    name = slot.filename
    out: list[Finding] = []
    if not os.path.exists(path):
        return [Finding(name, False, "ファイルが無い: " + path)]

    size = os.path.getsize(path)
    out.append(
        Finding(
            name,
            size <= spec.MAX_BYTES_PER_IMAGE,
            "{:,} バイト（上限 {:,}）".format(size, spec.MAX_BYTES_PER_IMAGE),
        )
    )
    # 画像を開く場所は compose.open_image に一本化する（画素数上限・EXIF補正）。
    # ここが読むのは自分で書いた build/ の成果物だが、利用者が差し替えた後に
    # validate を回す経路があるので、ガードの外に置かない。
    with compose.open_image(path) as im:
        fmt = im.format
        mode = im.mode
        w, h = im.size
        im = im.convert("RGBA")
        alpha = im.getchannel("A")
        lo, _hi = alpha.getextrema()
        bbox = alpha.point(lambda a: 255 if a > 8 else 0).getbbox()

    out.append(Finding(name, fmt == "PNG", "形式 {}（PNG 必須）".format(fmt)))
    out.append(
        Finding(name, mode in ("RGBA", "P", "RGB"), "カラーモード {}（RGB系必須）".format(mode))
    )
    out.append(Finding(name, lo == 0, "背景の透過: {}".format("あり" if lo == 0 else "**なし**")))
    if spec.EVEN_DIMENSIONS_REQUIRED:
        out.append(
            Finding(name, w % 2 == 0 and h % 2 == 0, "寸法 {}x{}（偶数必須）".format(w, h))
        )

    if slot.exact:
        out.append(
            Finding(name, (w, h) == (slot.width, slot.height),
                    "寸法 {}x{}（{}x{} ちょうど必須）".format(w, h, slot.width, slot.height))
        )
    else:
        out.append(
            Finding(name, w <= slot.width and h <= slot.height,
                    "寸法 {}x{}（{}x{} 以内）".format(w, h, slot.width, slot.height))
        )

    m = _margin_for(slot)
    if bbox is None:
        out.append(Finding(name, False, "中身が空（全面透過）"))
    else:
        gaps = (bbox[0], bbox[1], w - bbox[2], h - bbox[3])
        out.append(
            Finding(name, min(gaps) >= m,
                    "余白 左{} 上{} 右{} 下{}（{}px 以上必要）".format(*gaps, m))
        )
    return out


def check_meta(meta: dict) -> list[Finding]:
    out: list[Finding] = []
    for field in ("creator_name", "title", "description", "copyright"):
        ok, detail = spec.check_field(field, str(meta.get(field, "")))
        out.append(Finding(field, ok, detail))
    count = meta.get("count")
    out.append(
        Finding("count", count in spec.ALLOWED_COUNTS,
                "{}（{} のいずれか）".format(count, spec.ALLOWED_COUNTS))
    )
    return out


def check_all(build_dir: str, meta: dict) -> tuple[bool, list[Finding]]:
    findings = check_meta(meta)
    count = meta.get("count")
    if count in spec.ALLOWED_COUNTS:
        for slot in spec.slots(count):
            findings += check_image(os.path.join(build_dir, slot.filename), slot)
    return all(f.ok for f in findings), findings


def report(findings: list[Finding]) -> str:
    bad = [f for f in findings if not f.ok]
    head = "検査 {} 件 / 不合格 {} 件".format(len(findings), len(bad))
    body = "\n".join(f.line() for f in (bad if bad else findings))
    if bad:
        return head + "\n--- 不合格のみ表示 ---\n" + body
    return head + "\n" + body
