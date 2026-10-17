# -*- coding: utf-8 -*-
r"""compose.py — ベース画像とセリフから、規定どおりのスタンプ画像を組む。

入力は「人が渡した参考画像（キャラの絵）」と「セリフ1本」。出力は spec.py が定める
サイズ・余白・透過・容量をすべて満たす PNG。**絵そのものは作らない**——渡された絵を
規格に合わせて置き、文字を読める形で載せるところまでが守備範囲。

## やっていること

1. 背景を透過にする（`bg_remove`）。四隅から色距離で塗り広げる素朴な方式。
   **万能ではない**——背景とキャラが同色なら食い込む。効かなかったときは
   透過済み PNG を渡してもらうのが正しい（検証が「余白なし」で落として気付ける）。
2. 中身の外接矩形で切り詰める（余白の計算を安定させるため）。
3. キャンバスに置く。文字を置く帯を先に取り、残りにキャラを最大化して収める。
4. セリフを描く。**縁取り必須**（LINEの却下理由に「視認性が低い」が明記されている）。
5. 容量が上限を超えたら減色して収める。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import spec

# スタンプ用途に対しては桁違いに大きい値。Pillow の既定（約8950万px）より低く倒しておく——
# 既定は「2倍を超えたら例外・1〜2倍は警告のみ」なので、4MBのバイト上限を守ったままでも
# 高解像度を騙るPNGが警告域を素通りしてメモリを食える（2026-09-05 の審査で指摘）。
MAX_IMAGE_PIXELS = 40_000_000
# **プロセス全体の既定も下げる**。open_image を通さない Image.open が将来どこかに増えても、
# その経路が Pillow 既定（約8950万px）へ戻らないようにするため（審査 F6 の指摘）。
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

DEFAULT_FONT = r"C:\Windows\Fonts\meiryob.ttc"
FALLBACK_FONTS = [
    r"C:\Windows\Fonts\BIZ-UDGothicB.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]

# 行頭に置いてはいけない文字 / 行末に置いてはいけない文字（素朴な禁則処理）
_NO_LINE_START = "、。，．！？」』）】〉》”’ゃゅょっァィゥェォヵヶーぁぃぅぇぉ…・"
_NO_LINE_END = "「『（【〈《“‘"


@dataclass
class TextStyle:
    font_path: str = DEFAULT_FONT
    fill: str = "#2E2A26"
    stroke: str = "#FFFFFF"
    stroke_ratio: float = 0.16      # 文字サイズに対する縁取りの太さ
    position: str = "bottom"        # "bottom" | "top" | "none"
    band_ratio: float = 0.34        # 文字帯が内側領域に占める高さの割合
    max_lines: int = 2
    min_size: int = 18
    max_size: int | None = None


@dataclass
class ComposeOptions:
    bg_remove: bool = True
    bg_tolerance: int = 32
    text: TextStyle = field(default_factory=TextStyle)


# -------------------------------------------------------------- 画像を開く
def open_image(path: str) -> Image.Image:
    """画素数の上限を確かめ、EXIF の回転を適用してから開く。

    `Image.open` はヘッダしか読まない遅延読込なので、`.size` の検査は `.load()` より
    先に効く＝**デコードする前に**大きすぎる画像を弾ける。
    EXIF を当てるのは、スマホ写真をそのまま渡されたときに**検査は通るのに絵が横倒し**の
    スタンプが出来上がるのを防ぐため（`validate` は寸法と余白しか見ないので気付けない）。
    """
    raw = Image.open(path)
    try:
        w, h = raw.size
        if w * h > MAX_IMAGE_PIXELS:
            raise ValueError(
                "{} は {}x{} = {:,} 画素で上限 {:,} を超える。先に縮小してから渡すこと".format(
                    path, w, h, w * h, MAX_IMAGE_PIXELS
                )
            )
        fmt = raw.format
        fixed = ImageOps.exif_transpose(raw)
    except BaseException:
        raw.close()
        raise
    if fixed is not raw:
        # **format を引き継ぐ**。exif_transpose は新しい画像を返し、その .format は None に
        # なる（2026-09-05 実測）。引き継がないと validate の「PNG必須」検査が
        # 黙って落ちる側へ倒れる——ガードを一本化した修正が、そのガードを壊す。
        fixed.format = fmt
        raw.close()
    return fixed


# ---------------------------------------------------------------- 背景の透過
def remove_background(im: Image.Image, tolerance: int = 32) -> Image.Image:
    """四隅を種にして、近い色を透過にする。

    既に透過が使われている画像には**触らない**（せっかくの切り抜きを壊さないため）。
    """
    im = im.convert("RGBA")
    alpha = im.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return im  # 透過済みとみなす

    w, h = im.size
    px = im.load()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    ref = [px[x, y][:3] for x, y in seeds]
    tol2 = tolerance * tolerance

    def near(c):
        for r in ref:
            d0 = c[0] - r[0]
            d1 = c[1] - r[1]
            d2 = c[2] - r[2]
            if d0 * d0 + d1 * d1 + d2 * d2 <= tol2:
                return True
        return False

    # **push する時点で seen を立てる**。pop 時にしか立てないと、同じ座標が
    # 上下左右それぞれから最大4回積まれてから捨てられる＝ベタ塗り背景の大きい画像で
    # スタックが数千万要素まで膨らむ（2026-09-05 のレビューで指摘）。
    # push 時に立てれば各画素は高々1回しか積まれず、スタックは w*h に収まる。
    seen = bytearray(w * h)
    stack: list[tuple[int, int]] = []

    def push(x: int, y: int) -> None:
        i = y * w + x
        if not seen[i]:
            seen[i] = 1
            stack.append((x, y))

    for sx, sy in seeds:
        push(sx, sy)
    while stack:
        x, y = stack.pop()
        c = px[x, y]
        if not near(c):
            continue
        px[x, y] = (c[0], c[1], c[2], 0)
        if x > 0:
            push(x - 1, y)
        if x < w - 1:
            push(x + 1, y)
        if y > 0:
            push(x, y - 1)
        if y < h - 1:
            push(x, y + 1)
    return im


def trim(im: Image.Image, alpha_threshold: int = 8) -> Image.Image:
    """不透明な中身の外接矩形で切り詰める。"""
    im = im.convert("RGBA")
    mask = im.getchannel("A").point(lambda a: 255 if a > alpha_threshold else 0)
    box = mask.getbbox()
    if box is None:
        raise ValueError("画像の中身が空（すべて透過）。背景除去が効きすぎた可能性がある")
    return im.crop(box)


# ------------------------------------------------------------------ 文字組み
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """日本語フォントを読む。既定が無い環境では代替を順に試す（market もこれを使う）。"""
    for candidate in [path] + FALLBACK_FONTS:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    raise FileNotFoundError(
        "日本語フォントが1つも読めなかった。探した場所: " + str([path] + FALLBACK_FONTS)
    )


def wrap_japanese(text: str, max_chars: int) -> list[str]:
    """日本語を文字数で折り返す（空白が無いので単語区切りに頼れない）。"""
    if max_chars < 1:
        max_chars = 1
    lines: list[str] = []
    buf = ""
    for ch in text:
        if len(buf) >= max_chars:
            # 行頭禁則: 次が禁則文字なら、この行に引き込む
            if ch in _NO_LINE_START:
                buf += ch
                lines.append(buf)
                buf = ""
                continue
            # 行末禁則: 行末が禁則文字なら、1文字送る
            if buf[-1] in _NO_LINE_END:
                lines.append(buf[:-1])
                buf = buf[-1] + ch
                continue
            lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        lines.append(buf)
    return lines


def _fit_text(
    text: str, box_w: int, box_h: int, style: TextStyle
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """帯に収まる最大の文字サイズを二分探索で求める。"""
    lo, hi = style.min_size, min(box_h, style.max_size) if style.max_size else box_h
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(style.font_path, mid)
        # 1文字あたりの幅から折り返し幅を見積もり、実測で詰める
        adv = font.getlength("あ") or mid
        per = max(1, int(box_w // adv))
        lines = text.split("\n") if "\n" in text else wrap_japanese(text, per)
        if len(lines) > style.max_lines:
            hi = mid - 1
            continue
        stroke = max(1, int(mid * style.stroke_ratio))
        widest = max(font.getlength(ln) for ln in lines) + stroke * 2
        line_h = int(mid * 1.18)
        total_h = line_h * len(lines) + stroke * 2
        if widest <= box_w and total_h <= box_h:
            best = (font, lines, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        # 黙って min_size で描くと文字が帯からはみ出し、検査では「余白不足」としてしか
        # 出てこない＝原因が読めない。ここで理由を名指しして落とす。
        raise ValueError(
            "セリフ「{}」は {}x{}px の帯に {} 行以内で収まらない"
            "（最小 {}px でも不可）。短いセリフにするか、text_style の"
            " band_ratio を上げるか max_lines を増やすこと".format(
                text, box_w, box_h, style.max_lines, style.min_size
            )
        )
    return best


def draw_text(canvas: Image.Image, text: str, band: tuple[int, int, int, int],
              style: TextStyle) -> None:
    """帯 band=(x0,y0,x1,y1) の中央にセリフを描く（縁取りつき）。"""
    x0, y0, x1, y1 = band
    font, lines, size = _fit_text(text, x1 - x0, y1 - y0, style)
    stroke = max(1, int(size * style.stroke_ratio))
    line_h = int(size * 1.18)
    total_h = line_h * len(lines)
    cy = y0 + ((y1 - y0) - total_h) // 2
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        w = font.getlength(line)
        cx = x0 + ((x1 - x0) - w) / 2
        draw.text(
            (cx, cy + i * line_h),
            line,
            font=font,
            fill=style.fill,
            stroke_width=stroke,
            stroke_fill=style.stroke,
        )


# ------------------------------------------------------------------ 組み立て
def _place(canvas: Image.Image, art: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    scale = min(bw / art.width, bh / art.height)
    new = art.resize(
        (max(1, round(art.width * scale)), max(1, round(art.height * scale))),
        Image.LANCZOS,
    )
    canvas.alpha_composite(new, (x0 + (bw - new.width) // 2, y0 + (bh - new.height) // 2))


def compose_sticker(
    art: Image.Image,
    text: str | None,
    width: int = spec.STICKER_MAX_W,
    height: int = spec.STICKER_MAX_H,
    margin: int = spec.MARGIN_PX,
    style: TextStyle | None = None,
) -> Image.Image:
    """1枚のスタンプ画像を組む。art は既に透過・トリム済みであること。"""
    style = style or TextStyle()
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    inner = (margin, margin, width - margin, height - margin)
    if not text or style.position == "none":
        _place(canvas, art, inner)
        return canvas

    ih = inner[3] - inner[1]
    band_h = max(style.min_size + 8, int(ih * style.band_ratio))
    if style.position == "top":
        band = (inner[0], inner[1], inner[2], inner[1] + band_h)
        art_box = (inner[0], inner[1] + band_h, inner[2], inner[3])
    else:
        band = (inner[0], inner[3] - band_h, inner[2], inner[3])
        art_box = (inner[0], inner[1], inner[2], inner[3] - band_h)
    _place(canvas, art, art_box)
    draw_text(canvas, text, band, style)
    return canvas


def save_png(im: Image.Image, path: str, max_bytes: int = spec.MAX_BYTES_PER_IMAGE) -> int:
    """容量上限に収めて PNG を書く。収まらなければ減色していく。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.save(path, "PNG", optimize=True)
    size = os.path.getsize(path)
    if size <= max_bytes:
        return size
    for colors in (256, 128, 64):
        q = im.convert("RGBA").quantize(
            colors=colors, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG
        )
        q.save(path, "PNG", optimize=True)
        size = os.path.getsize(path)
        if size <= max_bytes:
            return size
    raise ValueError(
        "{} は減色しても上限 {} バイトに収まらなかった（{} バイト）".format(
            path, max_bytes, size
        )
    )


def load_art(path: str, options: ComposeOptions) -> Image.Image:
    """参考画像を読み、透過とトリムまで済ませる。"""
    if not os.path.exists(path):
        raise FileNotFoundError("参考画像が見つからない: " + path)
    with open_image(path) as raw:
        im = raw.convert("RGBA")
    if options.bg_remove:
        im = remove_background(im, options.bg_tolerance)
    return trim(im)
