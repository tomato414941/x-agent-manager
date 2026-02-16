---
name: x-account-operator
description: X account autonomous operation. Covers growth strategy, draft creation, workspace management, metrics analysis, X API v2 reference, authentication, and troubleshooting.
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

## Authentication & Secrets

### Auth types

| Method | Variable | Use case | Header |
|---|---|---|---|
| OAuth 2.0 User Token | `$X_ACCESS_TOKEN` | User actions (post, like, follow, DM) | `Authorization: Bearer $X_ACCESS_TOKEN` |
| App-Only Bearer Token | `$X_APP_BEARER_TOKEN` | Read-only, platform-level | `Authorization: Bearer $X_APP_BEARER_TOKEN` |

**Important**: Some endpoints ONLY accept App-Only Bearer Token and return `403 Unsupported Authentication` with a User Token. Known App-Only-only endpoints:
- `GET /2/usage/tweets`

### Secrets variable mapping

#### App-wide config: `~/.secrets/x-agent-manager/config`
| Variable | Purpose |
|---|---|
| `X_CLIENT_ID` | OAuth 2.0 client ID |
| `X_REDIRECT_URI` | OAuth callback URL |
| `X_SCOPES` | Requested OAuth scopes |
| `X_APP_BEARER_TOKEN` | App-Only Bearer Token (read-only / platform) |
| `EXPECTED_HOSTNAME` | Hostname validation |
| `AUTO_PUBLISH` | Auto-publish flag |
| `AUTO_SCHEDULE` | Auto-schedule flag |

#### Per-account tokens: `~/.secrets/x-agent-manager/<account>`
| Variable | Purpose |
|---|---|
| `X_ACCESS_TOKEN` | OAuth 2.0 User Access Token (2h TTL) |
| `X_REFRESH_TOKEN` | OAuth 2.0 Refresh Token |

#### Load secrets
```bash
source ~/.secrets/x-agent-manager/config       # App keys + App-Only Bearer
source ~/.secrets/x-agent-manager/<account>     # User tokens
```

Do NOT use `X_USER_ACCESS_TOKEN` or `X_BEARER_TOKEN` — these are not defined in secrets.

### OAuth 2.0 PKCE flow
1. Auth URL with `response_type=code`, `client_id`, `redirect_uri`, `state`, `code_challenge` (S256), scopes
2. User authorizes → receives `code` (valid 30 seconds)
3. Exchange for access token (2h TTL) + refresh token (with `offline.access` scope)
4. Refresh: `POST https://api.x.com/2/oauth2/token` with `grant_type=refresh_token`

### Scopes
`tweet.read` `tweet.write` `users.read` `follows.read` `follows.write` `like.read` `like.write` `bookmark.read` `dm.read` `media.write` `offline.access`

### Token refresh
```bash
curl -s -X POST "https://api.x.com/2/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token&refresh_token=$X_REFRESH_TOKEN&client_id=$X_CLIENT_ID"
```
Update `X_ACCESS_TOKEN` and `X_REFRESH_TOKEN` in the secrets file after refresh.

### Usage monitoring

**Requires App-Only Bearer Token** (`$X_APP_BEARER_TOKEN`), NOT User Token.

```bash
curl -s "https://api.x.com/2/usage/tweets" \
  -H "Authorization: Bearer $X_APP_BEARER_TOKEN"
```

| Field | Meaning |
|---|---|
| `project_cap` | Monthly usage budget cap (tweet cap) |
| `project_usage` | Tweets used this billing period |
| `cap_reset_day` | Day of month when usage resets |

**Credit balance is NOT available via API.** Check: https://console.x.com/

### 401/403 Troubleshooting

```bash
# 1. Check variable is not empty
echo "X_ACCESS_TOKEN len=${#X_ACCESS_TOKEN}"
echo "X_APP_BEARER_TOKEN len=${#X_APP_BEARER_TOKEN}"

# 2. Verify user token
curl -s "https://api.x.com/2/users/me" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
# Expected: {"data":{"id":"...","name":"...","username":"..."}}
```

| Symptom | Cause | Fix |
|---|---|---|
| Variable is empty (len=0) | Wrong variable name or secrets not loaded | Check `~/.secrets/x-agent-manager/` variable names, re-source |
| `401 Unauthorized` | Token expired (2h TTL) | Refresh: `POST /2/oauth2/token` with `grant_type=refresh_token` |
| `403 Unsupported Authentication` | Wrong auth type for endpoint | Switch between User Token and App-Only Bearer Token |
| `403 Forbidden` | Missing OAuth scope | Check required scopes for the endpoint |

## API Reference

Docs: https://docs.x.com/overview | LLM index: https://docs.x.com/llms.txt

### Posts

#### Create
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world"}'
# 201: {"data": {"id": "...", "text": "..."}}
```

#### Reply
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Reply", "reply": {"in_reply_to_tweet_id": "TWEET_ID"}}'
```

#### Quote
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "My take:", "quote_tweet_id": "TWEET_ID"}'
```

#### With media
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "With image", "media": {"media_ids": ["MEDIA_ID"]}}'
```

#### With poll
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Which?", "poll": {"options": ["A", "B"], "duration_minutes": 1440}}'
```

#### Delete
```bash
curl -s -X DELETE "https://api.x.com/2/tweets/$TWEET_ID" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### Get by ID
```bash
curl -s "https://api.x.com/2/tweets/$TWEET_ID?tweet.fields=created_at,public_metrics,author_id,entities" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### Search recent (7 days)
```bash
curl -s "https://api.x.com/2/tweets/search/recent?query=QUERY&max_results=10&tweet.fields=created_at,public_metrics,author_id" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### Search full archive
```bash
curl -s "https://api.x.com/2/tweets/search/all?query=QUERY&max_results=10&tweet.fields=created_at,public_metrics" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### Constraints
- `media`, `quote_tweet_id`, `poll`, `card_uri` are mutually exclusive
- `reply_settings`: `everyone` | `following` | `mentionedUsers` | `subscribers` | `verified`
- Text limit: 280 chars (standard), up to 25,000 (X Premium)

### Users

#### Authenticated user
```bash
curl -s "https://api.x.com/2/users/me?user.fields=public_metrics,description,created_at,verified_type" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### By username
```bash
curl -s "https://api.x.com/2/users/by/username/$USERNAME?user.fields=public_metrics,description" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### User's posts
```bash
curl -s "https://api.x.com/2/users/$USER_ID/tweets?max_results=10&tweet.fields=created_at,public_metrics" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### User's mentions
```bash
curl -s "https://api.x.com/2/users/$USER_ID/mentions?max_results=10&tweet.fields=created_at,public_metrics,author_id" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

### Follows

#### Follow / Unfollow
```bash
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/following" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
curl -s -X DELETE "https://api.x.com/2/users/$MY_USER_ID/following/$TARGET_USER_ID" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

#### Get followers / following
```bash
curl -s "https://api.x.com/2/users/$USER_ID/followers?max_results=100&user.fields=public_metrics" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
curl -s "https://api.x.com/2/users/$USER_ID/following?max_results=100&user.fields=public_metrics" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

### Likes

```bash
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/likes" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tweet_id": "TWEET_ID"}'
curl -s -X DELETE "https://api.x.com/2/users/$MY_USER_ID/likes/$TWEET_ID" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```

### Blocks & Mutes

```bash
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/blocking" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/muting" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
```

### Trends

```bash
curl -s "https://api.x.com/2/trends/by/woeid/$WOEID" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
# Japan: 23424856 | Tokyo: 1118370
```

### Key fields

#### tweet.fields
`id` `text` `created_at` `author_id` `public_metrics` `entities` `conversation_id` `referenced_tweets` `lang` `attachments` `note_tweet` `reply_settings`

#### user.fields
`id` `name` `username` `created_at` `description` `verified` `verified_type` `public_metrics` `profile_image_url` `location` `url` `pinned_tweet_id` `connection_status`

#### public_metrics (post)
`retweet_count` `reply_count` `like_count` `quote_count` `impression_count` `bookmark_count`

#### public_metrics (user)
`followers_count` `following_count` `tweet_count` `listed_count`

### Rate limits
- 15-minute windows
- Headers: `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset`
- Exceeded: HTTP 429 (error code 88)
- Use exponential backoff; prefer streaming over polling

### Pagination
```bash
curl -s "https://api.x.com/2/tweets/search/recent?query=QUERY&pagination_token=$NEXT_TOKEN" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
```
Use `meta.next_token` from response.
