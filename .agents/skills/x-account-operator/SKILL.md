---
name: x-account-operator
description: X account growth strategy and autonomous operation. Covers draft creation, human communication, memory management, and self-improvement workflow.
---

# X Account Operator

## Purpose
Grow this X account toward monetization (Creator Revenue Sharing). Act as a growth strategist, not just a draft writer.

## Workspace Layout
- `workspace/drafts/` — post drafts (YAML frontmatter + text)
- `workspace/memory/` — strategy notes, session summaries
- `workspace/state/` — posts.jsonl, metrics.jsonl, queue.jsonl, runs.jsonl
- `workspace/human/requests.md` — Agent → Human (proposals, questions)
- `workspace/human/messages.md` — Human → Agent (approvals, answers)

## Draft Format
File: `workspace/drafts/YYYYMMDD_HHMMSS_<slug>.md`
```md
---
created_at: "<ISO UTC>"
scheduled_at: "<ISO UTC>"   # when auto_publish: true
auto_publish: true|false
topics: ["..."]
sources:
  - title: "..."
    url: "https://..."
    retrieved_at: "<ISO UTC>"
---
<post text>
```

## Human Communication
- Write proposals to `workspace/human/requests.md` (prepend with ISO timestamp)
- Read responses from `workspace/human/messages.md`
- Be specific and actionable: "Follow @user1, @user2 — they post about X and engage with similar content" is better than "consider engaging with accounts in your niche"

## Quality Rules
- Write like a real person. No template patterns ("結論:", "ポイント:", "解説します")
- 280 chars default. First 280 chars must carry value even in longer posts
- Back claims with sources (web search + record in frontmatter)
- No duplicates against existing drafts and past posts

## State File Formats

### posts.jsonl
`{published_at, draft_path, tweet_id, text_sha256, text, response}`

### metrics.jsonl
`{fetched_at, tweet_id, created_at, public_metrics, non_public_metrics, organic_metrics}`

### eligibility.jsonl
`{computed_at, window_days, observed_organic_impressions_90d, observed_progress_pct, ...}`

## Metrics Operations

### Fetch Post Metrics
- posts.jsonl から最近の tweet_id を取得（最大50件）
- metrics.jsonl で各 tweet の最終取得時刻を確認、15分以上経過分を対象
- X API `GET /2/tweets?ids=...&tweet.fields=created_at,public_metrics,non_public_metrics,organic_metrics`
  - バッチ上限: 100 IDs/リクエスト
  - 401/403 → public_metrics のみでリトライ
  - non_public_metrics / organic_metrics は投稿後30日以内のみ取得可能
- 結果を metrics.jsonl に追記

### Summarize Performance
- posts.jsonl + metrics.jsonl を結合
- 各 tweet の最良スナップショット（最大 impression_count）を選択
- ドラフトの frontmatter から topics を取得
- Top 10 by impressions / Top 10 by replies のテーブル生成
- workspace/memory/performance.md に出力

### Track Eligibility
- Creator Revenue Sharing 条件: 90日間で 500万オーガニックインプレッション
- metrics.jsonl から tweet ごとの最大 impression_count を抽出
- 90日ウィンドウでフィルタ → 合計 → 進捗率計算
- manual.jsonl の verified_followers も参照
- workspace/state/eligibility.jsonl に追記 + workspace/memory/eligibility.md に出力
