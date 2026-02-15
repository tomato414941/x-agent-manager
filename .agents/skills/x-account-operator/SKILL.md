---
name: x-account-operator
description: 複数アカウントで使えるX運用スキル（下書き生成、重複回避、学習ループ、人間との非同期やりとり）
---

# X Account Operator

## 目的
- このアカウントの人気を高める（フォロワー増、意味のあるエンゲージメント増）
- そのために下書きを生成し、学習ループを回す（投稿は人間が行う前提）

## 呼び出し
- Codex: `$x-account-operator`

## スコープ
- 作業対象は「現在のアカウントディレクトリ」配下のみ
- リポジトリのコードや他アカウントのファイルは変更しない
- 投稿実行は原則しない（下書き生成まで）
  - 例外: 人間が `workspace/human/messages.md` で明示的に承認した場合のみ、X API で投稿してよい
  - 投稿実行は `scripts/publish_draft.py`（共通スクリプト）を利用してアカウント配下 `workspace` を対象に行う

## 入力
- `workspace/human/messages.md`（人間からの返答）
- `workspace/memory/*.md`
- `workspace/state/*.jsonl`（過去投稿・メトリクスがある場合）
- `workspace/drafts/*`（既存下書き）

## 出力
- `workspace/drafts/` に下書きを作成する
- `workspace/memory/latest_summary.md` を更新する（作業ログ + 次アクション）
- 必要なら `workspace/human/requests.md` に依頼を書く（意思決定/不足データ/メトリクス共有など）

## Human Communication（ファイル経由）
- `workspace/human/requests.md`: エージェント -> 人間（依頼）。先頭に追記し、日時（ISO）と要件を簡潔に書く。
- `workspace/human/messages.md`: 人間 -> エージェント（返答）。読んだら削除（または空にする）。

requests.md 例:
```md
## 2026-02-15T04:12:00Z
- [ ] 確認: 次回から投稿トーンを「丁寧語」か「フランク」にする？
```

messages.md 例:
```md
## 2026-02-15T04:20:00Z
- 回答: トーンは丁寧語で固定。技術寄り、煽りなし。
```

## 下書きフォーマット（Markdown）
ファイル名例: `workspace/drafts/20260215_033000.md`

```md
---
created_at: 2026-02-15T03:30:00Z
scheduled_at: 2026-02-15T09:00:00Z  # optional
topics: ["topic1", "topic2"]
sources:
  - title: "..."
    url: "https://..."
    retrieved_at: "2026-02-15T03:29:00Z"
---
本文（X投稿テキスト。280文字以内）
```

## 最低限の品質ルール
- 日本語（指示がない限り）
- 280文字以内
- 事実ベースで簡潔に
- 既存下書き/過去投稿と重複しない
- 時事性がある主張は Web 検索で裏取りし、`sources` を最低1件付ける
