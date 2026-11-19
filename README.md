# 健康ショート動画 自動制作

イシューにテーマを書くと、Claude が台本を作り、GitHub Actions が音声・イラスト・動画まで自動で生成します。

## 流れ

1. **イシューを作る**：「動画制作（Claudeが自動作成）」テンプレートでテーマを書く
2. **Claude が台本を作成**：`episodes/` に台本と設定ファイルを作り、PR を出す
3. **人が確認してマージ**：内容・表現をチェックし、問題なければマージ
4. **動画を自動生成**：マージをきっかけに「動画を生成」ワークフローが動く
   - 音声：VOICEVOX（春日部つむぎ）
   - イラスト：Gemini API（Nano Banana 2）
   - 字幕と結合：ffmpeg
5. **ダウンロードして公開**：Actions の実行結果の「videos」から mp4 をダウンロードし、YouTube に限定公開でアップロード

## 初期設定（最初の1回だけ）

1. [Claude GitHub App](https://github.com/apps/claude) をこのリポジトリにインストール
2. Settings → Secrets and variables → Actions に、次のシークレットを登録
   - `CLAUDE_CODE_OAUTH_TOKEN`（Claude のサブスクリプション。`claude setup-token` で発行）または `ANTHROPIC_API_KEY`（Claude Console で発行）のどちらか
   - `GEMINI_API_KEY`（Google AI Studio で発行。画像生成は有料）

## 手動で動画を作り直す

Actions →「動画を生成」→ Run workflow で、エピソードのフォルダ（例：`episodes/001-sleep-hours`）を指定します。

## 手元で動作確認する

```
pip install pillow
python pipeline/render.py episodes/001-sleep-hours --mock
```

`--mock` を付けると、API を使わずにダミーの音声と画像で動画を作ります。

## 注意

- 公開前に必ず人が内容を確認してください（YouTube は、AIで量産された繰り返しの多いコンテンツや、AIの人物が健康について語る動画を収益化の対象外としています）
- 写実的なAI映像を使う場合は、アップロード時に「改変・合成コンテンツ」の申告が必要です
- 概要欄に「VOICEVOX:春日部つむぎ」のクレジットを入れてください
