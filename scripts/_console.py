# -*- coding: utf-8 -*-
"""_console.py — 標準出力・標準エラーを UTF-8 に固定する唯一の場所。

## なぜ1箇所に集めるのか（2026-08-16 の監査で確定した実害）

このPCの既定コードページは cp932 である。Python は起動元の環境に従うため、
同じスクリプトが **Git Bash では cp932、PYTHONIOENCODING=utf-8 の下では utf-8** で
出力する。コードは1行も変わらないのに、次の3つが環境ごとに変わる。

1. **下流の判定が変わる。** 上流の日本語文言に一致するかで判定する検査は、
   cp932 バイト列を utf-8 として読んだ瞬間に永久に一致しなくなる。
   実害: `structure_audit` の索引鮮度検査が **常に「索引は最新」を返していた**
   （`kb_index_refresh --check` の出力が cp932 で、「再構築が必要」が現れないため。
   空でもないのでフォールバックも発動しない＝**壊れていることが観測できない**）。
2. **異常系だけが落ちる。** 正常系は ASCII で通り、Fail Loud のために足した
   日本語の警告行だけが `UnicodeEncodeError` でクラッシュする。
   実害: `check_agent_originality.py` が判定行を印字する前に落ち、
   **クラッシュの rc=1 と「重複疑い」の rc=1 が区別できない**状態だった。
3. **テストの合否が変わる。** 同じテストが Git Bash で失敗し、
   `PYTHONIOENCODING=utf-8` で全通する。二人が同じ手順を踏んで違う結論に達し、
   **どちらも「再現した」と報告できてしまう**。

2026-08-13 に3本（install_gate / cost_gate / secret_scan）だけ個別に直したが、
残り12本以上へ横展開されなかった。**同じ3行を各ファイルへ書き写す方式が、
取り残しを生む原因そのものだった**ため、ここへ集約する。

## 使い方

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _console import use_utf8

    def main() -> int:
        use_utf8()          # ← 引数を解釈する前に呼ぶ（--help の日本語も化けさせない）
        ...

`import` した時点でも自動的に適用される。明示呼び出しは、読む人に
「このスクリプトは出力エンコーディングを固定している」と伝えるためのもので、
二重に呼んでも害はない（べき等）。

## この対処が**しないこと**（誇張しない）

- ファイル I/O のエンコーディングは変えない（`open()` の `encoding=` は各所の指定に従う）。
- 子プロセスの出力は変えない。`subprocess` で他の Python を呼ぶ側は、
  **受け取った側で** `encoding="utf-8"` を明示するか、この関数を子側でも通すこと。
- 端末が cp932 のまま表示する文字（フォント未収録など）は救えない。
"""
from __future__ import annotations

import sys
from typing import IO, Any


def use_utf8(*streams: IO[Any]) -> None:
    """`sys.stdout` / `sys.stderr`（または指定のストリーム）を UTF-8 へ切り替える。

    - **べき等**: 何度呼んでも同じ結果になる。
    - **失敗しても止めない**: 切り替えられない環境（リダイレクト済み・差し替え済み・
      `reconfigure` を持たないラッパ）でも、本来の処理は続ける。
      ここで例外を投げると「出力の都合で判定が止まる」という本末転倒になる。
      ただし**黙って諦めない**——切り替えに失敗したことは呼び出し側から
      `is_utf8()` で確認できる。
    """
    for stream in (streams or (sys.stdout, sys.stderr)):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError, AttributeError):
            # 差し替え済みストリーム（テストの StringIO 等）では起きうる。判定は続ける。
            continue


def is_utf8(stream: IO[Any] | None = None) -> bool:
    """そのストリームが実際に UTF-8 で書き出す状態かを返す。

    `use_utf8()` が効いたかを**呼び出し側が確認できる**ようにするための関数。
    「呼んだ」ことと「効いた」ことは別物であり、後者を測れないと
    この対処自体が『判定を表示だけに使う』欠陥になる。
    """
    target = stream if stream is not None else sys.stdout
    encoding = getattr(target, "encoding", None)
    return isinstance(encoding, str) and encoding.lower().replace("-", "") in {"utf8", "utf8sig"}


# import した時点で適用する。個別スクリプトが呼び忘れても最低限は効く
# （呼び忘れが12本出た実績があるため、明示呼び出しだけに頼らない）。
use_utf8()
