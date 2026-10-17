# -*- coding: utf-8 -*-
"""LINEアニメーションスタンプ申請ZIPの事前検査。"""
from __future__ import annotations

import argparse
import binascii
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import io
import struct
import sys
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _console import use_utf8  # noqa: E402

use_utf8()

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ALLOWED_STICKER_COUNTS = (8, 16, 24)
MAX_IMAGE_BYTES = 1_000_000
MAX_ZIP_BYTES = 60 * 1024 * 1024
ALLOWED_TOTAL_MS = (1000, 2000, 3000, 4000)


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    frame_controls: tuple[tuple[int, int, int, int, int, int, int, int, int], ...]
    frame_delays_ms: tuple[Fraction, ...]
    plays: int | None
    sequence_numbers: tuple[int, ...]
    chunk_count: int

    @property
    def is_apng(self) -> bool:
        return self.plays is not None


def total_playback_ms(delays_ms: tuple[Fraction, ...] | list[Fraction], plays: int) -> Fraction:
    """Return one-loop frame delays multiplied by APNG's finite play count."""
    return sum(delays_ms, Fraction(0)) * plays


def validate_total_playback(delays_ms: tuple[Fraction, ...] | list[Fraction], plays: int) -> Fraction:
    """LINE requires total duration to be exactly 1, 2, 3, or 4 whole seconds."""
    if not 5 <= len(delays_ms) <= 20:
        raise ValueError(f"フレーム数 {len(delays_ms)}（5〜20が必要）")
    if not 1 <= plays <= 4:
        raise ValueError(f"ループ数 {plays}（1〜4が必要）")
    total = total_playback_ms(delays_ms, plays)
    if total.denominator != 1 or total.numerator not in ALLOWED_TOTAL_MS:
        raise ValueError(
            f"合計再生時間 {float(total / 1000):g} 秒（1・2・3・4秒の整数値が必要）"
        )
    return total


def inspect_png(data: bytes) -> PngInfo:
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("PNGシグネチャがありません")
    pos = len(PNG_SIGNATURE)
    width = height = None
    plays = None
    declared_frames = None
    controls = []
    delays = []
    sequences = []
    chunk_count = 0
    saw_iend = False
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("PNGチャンクが途中で切れています")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        stored_crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if (binascii.crc32(kind + body) & 0xFFFFFFFF) != stored_crc:
            raise ValueError(f"{kind.decode('ascii', 'replace')} CRC不一致")
        chunk_count += 1
        if kind == b"IHDR":
            if length != 13:
                raise ValueError("IHDRの長さが不正です")
            width, height = struct.unpack_from(">II", body)
        elif kind == b"acTL":
            if length != 8 or plays is not None:
                raise ValueError("acTLが不正または重複しています")
            declared_frames, plays = struct.unpack(">II", body)
            if declared_frames < 1:
                raise ValueError("acTLのフレーム数が0です")
        elif kind == b"fcTL":
            if length != 26:
                raise ValueError("fcTLの長さが不正です")
            fields = struct.unpack(">IIIIIHHBB", body)
            seq, fw, fh, x, y, delay_num, delay_den, _dispose, _blend = fields
            sequences.append(seq)
            controls.append(fields)
            delays.append(Fraction(delay_num * 1000, delay_den or 100))
            if width is not None and height is not None:
                if fw < 1 or fh < 1 or x + fw > width or y + fh > height:
                    raise ValueError("fcTLのフレーム領域がキャンバス外です")
        elif kind == b"fdAT":
            if length < 4:
                raise ValueError("fdATが短すぎます")
            sequences.append(struct.unpack_from(">I", body)[0])
        elif kind == b"IEND":
            saw_iend = True
            pos = end
            break
        pos = end
    if width is None or height is None or width < 1 or height < 1:
        raise ValueError("有効なIHDRがありません")
    if not saw_iend or pos != len(data):
        raise ValueError("IENDが無いか、IEND後に余分なデータがあります")
    if plays is None:
        if controls or sequences:
            raise ValueError("APNG制御チャンクがありますがacTLがありません")
    else:
        if len(controls) != declared_frames or len(delays) != declared_frames:
            raise ValueError(f"acTL宣言{declared_frames}フレーム、fcTL実数{len(controls)}フレーム")
        if sequences != list(range(len(sequences))):
            raise ValueError("APNGシーケンス番号が連続していません")
    return PngInfo(width, height, tuple(controls), tuple(delays), plays, tuple(sequences), chunk_count)


def _check_transparency_and_frames(name: str, data: bytes, expected_count: int) -> list[str]:
    errors = []
    try:
        im = Image.open(io.BytesIO(data))
        if im.format != "PNG":
            return [f"{name}: PNGとして読めません（{im.format}）"]
        if getattr(im, "n_frames", 1) != expected_count:
            errors.append(f"{name}: デコーダ実フレーム数が{getattr(im, 'n_frames', 1)}（期待{expected_count}）")
        hashes = set()
        for frame_index in range(getattr(im, "n_frames", 1)):
            im.seek(frame_index)
            frame = im.convert("RGBA")
            alpha_min, alpha_max = frame.getchannel("A").getextrema()
            if alpha_min != 0 or alpha_max == 0:
                errors.append(f"{name}: frame {frame_index + 1} の透明背景／内容を確認できません")
                break
            hashes.add(hashlib.sha256(frame.tobytes()).digest())
        if expected_count > 1 and len(hashes) < 2:
            errors.append(f"{name}: 全フレームの表示内容が同一です")
    except (OSError, UnidentifiedImageError, EOFError) as exc:
        errors.append(f"{name}: 画像をデコードできません（{exc}）")
    return errors


def validate_zip(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if path.stat().st_size > MAX_ZIP_BYTES:
        errors.append(f"ZIP容量が上限超過: {path.stat().st_size} bytes")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"ZIPを開けません: {exc}"], notes
    with archive:
        if archive.testzip() is not None:
            errors.append("ZIP内CRC検査に失敗しました")
        names = [i.filename for i in archive.infolist()]
        if len(names) != len(set(names)):
            errors.append("ZIP内に重複ファイル名があります")
        numbered = sorted(
            n for n in names
            if len(Path(n).name) == 6 and Path(n).name[:2].isdigit() and Path(n).name.endswith(".png")
        )
        if any(Path(n).name != n for n in names):
            errors.append("ZIPの画像はすべてルート直下に置いてください")
        count = len(numbered)
        if count not in ALLOWED_STICKER_COUNTS:
            errors.append(f"番号付きスタンプ画像数 {count}（8・16・24のいずれかが必要）")
        expected = {f"{i:02}.png" for i in range(1, count + 1)} | {"main.png", "tab.png"}
        if set(names) != expected:
            errors.append(f"ZIPのファイル名不一致: expected={sorted(expected)}, actual={sorted(names)}")
        for name in names:
            if name not in expected:
                continue
            data = archive.read(name)
            if len(data) > MAX_IMAGE_BYTES:
                errors.append(f"{name}: 1MB上限超過（{len(data)} bytes）")
            try:
                info = inspect_png(data)
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
                continue
            if name == "tab.png":
                if info.is_apng:
                    errors.append("tab.png: 静止PNGが必要です")
                if (info.width, info.height) != (96, 74):
                    errors.append(f"tab.png: 寸法{info.width}x{info.height}（96x74が必要）")
                errors.extend(_check_transparency_and_frames(name, data, 1))
                continue
            if not info.is_apng:
                errors.append(f"{name}: アニメーションスタンプ商品ではAPNGが必要です（Mainを含む）")
                continue
            if not 5 <= len(info.frame_controls) <= 20:
                errors.append(f"{name}: {len(info.frame_controls)}フレーム（5〜20が必要）")
            if name == "main.png":
                if (info.width, info.height) != (240, 240):
                    errors.append(f"main.png: 寸法{info.width}x{info.height}（240x240が必要）")
            elif info.width > 320 or info.height > 270 or max(info.width, info.height) < 270:
                errors.append(f"{name}: 寸法{info.width}x{info.height}がアニメーションスタンプ規格外")
            try:
                total = validate_total_playback(info.frame_delays_ms, info.plays or 0)
                notes.append(f"{name}: {len(info.frame_controls)} frames, {float(total / 1000):g}s total")
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
            errors.extend(_check_transparency_and_frames(name, data, len(info.frame_controls)))
    return errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LINEアニメーションスタンプのZIPをアップロード前に検査")
    parser.add_argument("zip", type=Path, help="main.png、tab.png、01.png…を格納したZIP")
    args = parser.parse_args(argv)
    errors, notes = validate_zip(args.zip)
    for note in notes:
        print("OK  " + note)
    for error in errors:
        print("NG  " + error)
    if errors:
        print(f"NG  {len(errors)} 件。ZIPを申請に使わないでください。")
        return 1
    print(f"PASS: {args.zip.name} — APNG、時間、画像数、寸法、透過、ZIP CRC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
