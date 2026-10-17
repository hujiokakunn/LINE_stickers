# -*- coding: utf-8 -*-
r"""spec.py — LINE Creators Market のスタンプ規定を一箇所に固定する。

**この規定の正典はここ1ファイル**。他のモジュールは数値を写さず、ここを import する
（「正典は種類ごとに1つ」。数値を写した瞬間に片方だけ古くなる）。

## 出典と取得日

- 制作ガイドライン https://creator.line.me/ja/guideline/sticker/ （2026-09-05 取得）
- 審査ガイドライン https://creator.line.me/ja/guideline/ （2026-09-05 取得）

## 未確認の項目（Fail Loud）

**ZIP内のファイル名規則は公式ページで明示を確認できなかった**。
`creator.line.me/ja/guideline/sticker/detail/` は 404、`howto` にも記載なし。
このため `ZIP_NAMES_VERIFIED = False` とし、既定の命名（main.png / tab.png / 01.png…）は
**慣行にもとづく推定**として扱う。パイプラインは ZIP と同時に**個別ファイルのフォルダも出す**ので、
命名が違っていた場合は1枚ずつアップロードすれば必ず通る。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

GUIDELINE_URL = "https://creator.line.me/ja/guideline/sticker/"
REVIEW_GUIDELINE_URL = "https://creator.line.me/ja/guideline/"
SPEC_FETCHED_ON = "2026-09-05"

# ---- 画像規定 -------------------------------------------------------------
STICKER_MAX_W = 370
STICKER_MAX_H = 320
MAIN_W = MAIN_H = 240
TAB_W, TAB_H = 96, 74

MARGIN_PX = 10               # スタンプ画像でコンテンツと外枠の間に必要な余白の目安
MAIN_MARGIN_PX = 10          # メイン画像も同じ扱いでよい（240px なので十分取れる）
TAB_MARGIN_PX = 4            # タブは 96x74 と小さく、10px だと絵が潰れる。ここだけ緩める
MAX_BYTES_PER_IMAGE = 1024 * 1024        # 1MB
MAX_BYTES_ZIP = 60 * 1024 * 1024         # 60MB
MIN_DPI = 72
# 「画像サイズは偶数に設定」（制作ガイドライン。自動縮小への配慮として明記されている）
EVEN_DIMENSIONS_REQUIRED = True
ALLOWED_COUNTS = (8, 16, 24, 32, 40)     # 静止画スタンプ
ALLOWED_COUNTS_ANIMATION = (8, 16, 24)

# ---- テキスト項目の上限（全角は2文字としてカウントされる）----------------
FIELD_LIMITS = {
    "creator_name": 50,
    "title": 40,
    "description": 160,
    "copyright": 50,
}
# コピーライトは英数字のみ（公式明記）
COPYRIGHT_ASCII_ONLY = True

# ---- ZIP 命名（未確認・設定で変えられる）---------------------------------
ZIP_NAMES_VERIFIED = False
ZIP_MAIN_NAME = "main.png"
ZIP_TAB_NAME = "tab.png"
ZIP_STICKER_FMT = "{n:02d}.png"


@dataclass(frozen=True)
class Slot:
    """出力する1枚の画像の枠。"""
    key: str          # "main" / "tab" / "01".."40"
    width: int        # 上限（sticker）または固定値（main/tab）
    height: int
    exact: bool       # True=そのサイズちょうど / False=上限以内

    @property
    def filename(self) -> str:
        if self.key == "main":
            return ZIP_MAIN_NAME
        if self.key == "tab":
            return ZIP_TAB_NAME
        return ZIP_STICKER_FMT.format(n=int(self.key))


def slots(count: int) -> list[Slot]:
    """スタンプ個数から、出力すべき全スロットを返す。"""
    if count not in ALLOWED_COUNTS:
        raise ValueError(
            f"スタンプ個数は {ALLOWED_COUNTS} のいずれか。受け取った値: {count}"
        )
    out = [
        Slot("main", MAIN_W, MAIN_H, exact=True),
        Slot("tab", TAB_W, TAB_H, exact=True),
    ]
    out += [
        Slot(f"{i:02d}", STICKER_MAX_W, STICKER_MAX_H, exact=False)
        for i in range(1, count + 1)
    ]
    return out


def count_line_chars(text: str) -> int:
    """LINEの数え方で文字数を数える（全角=2、半角=1）。

    公式は「全角文字は2文字でカウントされます」とだけ述べており、どこまでを全角と
    見なすかは書かれていない。ここでは Unicode East Asian Width の W / F / A を
    全角として数える（A=Ambiguous を全角側に倒すのは、少なく見積もって上限超過を
    見逃すより安全側だから）。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1 for c in text)


def check_field(name: str, value: str) -> tuple[bool, str]:
    """申請フォームの1項目を検査する。戻り値 (ok, 理由)。"""
    if name not in FIELD_LIMITS:
        raise KeyError(f"未知の項目: {name}")
    if not value or not value.strip():
        return False, "空欄（必須項目）"
    limit = FIELD_LIMITS[name]
    n = count_line_chars(value)
    if n > limit:
        return False, f"{n}/{limit} 文字（全角=2換算）で上限超過"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return False, "制御文字が含まれている"
    if _has_emoji(value):
        return False, "絵文字は使えない（公式明記）"
    if name == "copyright" and COPYRIGHT_ASCII_ONLY:
        if not all(c.isascii() for c in value):
            return False, "コピーライトは英数字のみ（非ASCII文字が含まれている）"
    return True, f"{n}/{limit} 文字"


def _has_emoji(text: str) -> bool:
    for c in text:
        cp = ord(c)
        if (
            0x1F300 <= cp <= 0x1FAFF
            or 0x2600 <= cp <= 0x27BF
            or 0xFE0F == cp
            or 0x1F000 <= cp <= 0x1F2FF
        ):
            return True
    return False
