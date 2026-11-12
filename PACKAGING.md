# 同梱の梱包・検査ツール

`run.py` は手元の完成画像から提出ファイルと検品テンプレートを組み立てる任意のツールです。画像生成・修正は [制作手順](WORKFLOW.md) に沿って、利用環境の画像ツールで行います。

Python 3.10以上を使用します。

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

## 使い方

```sh
python run.py init work/example/project.json --kind static --count 16
python run.py assemble work/example/project.json
python run.py review-template work/example/project.json
python run.py package work/example/project.json
```

1. `init` 後に `project.json` の商品情報、文言と入力ファイルを設定し、`assemble` の前に画像を指定パスへ置く。パスは `project.json` のフォルダ基準。
2. `assemble` 後に `review-template` を実行する。実物を見て `visual_review.json` の各画像とポーズの組み合わせに根拠を記録し、アニメーションでは `motion_review.json` も記入する。
3. `package` が成功すると `stickers.zip` と `申請転記表.md` ができる。レビューが画像と一致しない場合は修正版を見直し、新しいテンプレートを使う。

アニメーションの雛形は `--kind animation --count 8`。静止画は8・16・24・32・40個、アニメーションは8・16・24個を指定できます。

## project.json

- `kind` は `static` または `animation`。`theme_evidence` はテーマと根拠を記す欄。
- `metadata` は必要な言語ごとの配列。各行に `language`、`creator_name`、`title`、`description`、`copyright` を指定。
- `stickers` はスタンプの配列。`main` と `tab` も提出用に指定する。
- 静止画の `stickers`・`main` は `{"source":"art/01.png","caption":"セリフ"}` の形式。Tabは種別共通で `{"source":"art/tab.png"}`。
- アニメーションの `stickers`・`main` は `frames`、同数の `durations_ms`、`loops` を指定。詳しい制約は [提出仕様](SPEC.md) と [同梱ツールの動きの検査基準](scripts/tools/line_sticker/MOTION_QUALITY.md) を参照。

文字合成を自動化する場合は [compose.py](scripts/tools/line_sticker/compose.py) の `TextStyle` と `ComposeOptions` を利用できます。フォントは利用者が用意してください。
