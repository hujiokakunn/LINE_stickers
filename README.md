# LINE stickers production harness

静止画とアニメーションスタンプの制作・検査・梱包の共通手順。Luna等の制御エージェントは最初に[AGENTS.md](AGENTS.md)を読む。
公開先: https://github.com/hujiokakunn/LINE_stickers 。この配布物にはキャラクター仕様・参照画像・セリフ集・ポーズ集を含めない。

## セットアップ

Python 3.10以上。`python -m pip install -r requirements.txt`。
実制作には参照画像を渡せる画像生成ツールと、使用言語のフォントが必要。画像生成のAPIキーはハーネスに保存しない。
チェックは `python -m unittest discover -s tests`。ネットワーク・生成API不要。

## 制作

[SPEC.md](SPEC.md)と、アニメの場合は[scripts/tools/line_sticker/MOTION_QUALITY.md](scripts/tools/line_sticker/MOTION_QUALITY.md)を読む。
キャラ正典はユーザーが `private/` に置き、文言・ポーズも利用者の資料から選ぶ。公開版はそれらを供給しない。

1. AGENTSの手順で素材を生成し1枚ずつ承認する。全フレームは同寸法・共通アンカーとし、文字は後合成。たとえば `scripts/tools/line_sticker/compose.py` の `TextStyle` と `ComposeOptions` はフォント指定と静止画合成に再利用できる。画像生成自体をrun.pyが自動実行するわけではない。
2. `python run.py init work/<商品名>/project.json --kind animation --count 8` で全件分の雛形を作る。静止画なら `--kind static --count 16`。相対パスはproject.jsonのフォルダ基準。空欄の商品情報と文言を埋め、全素材を指定パスへ保存する。雛形だけでは完成でも検査PASSでもない。
3. `python run.py assemble work/<商品名>/project.json`
4. `python run.py review-template work/<商品名>/project.json`
5. 実物を見て `visual_review.json`、アニメは `motion_review.json` も記入。Mainを含め全数・全フレーム、原寸と半分表示で通常速度再生する。商品内の全組合せの差も evidence に対象番号付きで記録する。テンプレート作成は合格ではない。
6. `python run.py package work/<商品名>/project.json` → `stickers.zip`・`申請転記表.md`。失敗時は完成扱いしない。

### project.json の項目

```json
{
  "kind": "animation",
  "theme_evidence": "利用者のテーマと根拠URL",
  "metadata": [{"language": "Japanese", "creator_name": "Creator", "title": "利用者のタイトル", "description": "利用者の説明", "copyright": "Creator"}],
  "stickers": [{"caption": "利用者の文言", "frames": ["frames/01_01.png", "frames/01_02.png"], "durations_ms": [150, 150], "loops": 1}],
  "main": {"frames": ["frames/main_01.png", "frames/main_02.png"], "durations_ms": [150, 150], "loops": 1},
  "tab": {"source": "frames/tab.png"}
}
```

これはフィールド説明用の不完全な例。2フレーム・1スタンプのままでは検査に落ちる。アニメはstickersを8/16/24件、各framesを5〜20件、各durations_msを同じ件数にする。既定20×150ms。Mainも同じフレーム規則。
静止画は `kind: "static"` とし、各stickersとmainを `{"source":"art/01.png","caption":"利用者の文言"}` の形式にする。Tabは共通。静止画は8/16/24/32/40件。画像は提出寸法に整えてからassembleへ渡す。metadataは必要な言語数だけ行を追加する。

再制作は以前の素材・証跡を保存し、新しい作業ディレクトリで組み立てる。生成途中の失敗を完了と報告しない。実生成できるか、販売されるか、審査に通るかはこのテストだけでは保証しない。

## 公開範囲と更新

`private/`, `work/`, `submit/`, ZIP、画像、参照仕様・文言・ポーズ資料は公開対象外。export_public.pyが固定allowlistから公開物を作る。出力のPUBLIC_MANIFEST.jsonでファイルとSHAを確認する。既存GitHubリポジトリへ反映する場合はその履歴・規約も確認し、配布物だけを差分追加する。元Vault全体をpushしない。

ライセンスは既存の[MIT License](LICENSE)に従う。フォント・利用者のキャラクター画像・文言資料は同梱しない。
