---
name: x-api
description: X API v2 reference. Use for posting tweets, user lookup, search, follows, likes, OAuth tokens, media upload, and rate limits.
---

# X API v2

Reference and ready-to-use commands for the X API v2.

Docs: https://docs.x.com/overview | LLM index: https://docs.x.com/llms.txt

## Authentication

| Method | Use case | Header |
|---|---|---|
| OAuth 2.0 User (PKCE) | User actions (post, like, follow) | `Authorization: Bearer <user_access_token>` |
| OAuth 1.0a | Legacy user context | OAuth signature header |
| App-only Bearer | Read-only (search, lookup) | `Authorization: Bearer <app_bearer_token>` |

### Load secrets
```bash
source ~/.secrets/x-agent-manager/config    # API keys, bearer token
source ~/.secrets/x-agent-manager/<account>  # User tokens
```

### OAuth 2.0 PKCE flow
1. Auth URL with `response_type=code`, `client_id`, `redirect_uri`, `state`, `code_challenge` (S256), scopes
2. User authorizes → receives `code` (valid 30 seconds)
3. Exchange for access token (2h TTL) + refresh token (with `offline.access` scope)
4. Refresh: `POST https://api.x.com/2/oauth2/token` with `grant_type=refresh_token`

### Scopes
`tweet.read` `tweet.write` `users.read` `follows.read` `follows.write` `like.read` `like.write` `bookmark.read` `dm.read` `media.write` `offline.access`

## Posts

### Create
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello world"}'
# 201: {"data": {"id": "...", "text": "..."}}
```

### Reply
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Reply", "reply": {"in_reply_to_tweet_id": "TWEET_ID"}}'
```

### Quote
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "My take:", "quote_tweet_id": "TWEET_ID"}'
```

### With media
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "With image", "media": {"media_ids": ["MEDIA_ID"]}}'
```

### With poll
```bash
curl -s -X POST "https://api.x.com/2/tweets" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Which?", "poll": {"options": ["A", "B"], "duration_minutes": 1440}}'
```

### Delete
```bash
curl -s -X DELETE "https://api.x.com/2/tweets/$TWEET_ID" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN"
```

### Get by ID
```bash
curl -s "https://api.x.com/2/tweets/$TWEET_ID?tweet.fields=created_at,public_metrics,author_id,entities" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

### Search recent (7 days)
```bash
curl -s "https://api.x.com/2/tweets/search/recent?query=QUERY&max_results=10&tweet.fields=created_at,public_metrics,author_id" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

### Search full archive
```bash
curl -s "https://api.x.com/2/tweets/search/all?query=QUERY&max_results=10&tweet.fields=created_at,public_metrics" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

### Constraints
- `media`, `quote_tweet_id`, `poll`, `card_uri` are mutually exclusive
- `reply_settings`: `everyone` | `following` | `mentionedUsers` | `subscribers` | `verified`
- Text limit: 280 chars (standard), up to 25,000 (X Premium)

## Users

### Authenticated user
```bash
curl -s "https://api.x.com/2/users/me?user.fields=public_metrics,description,created_at,verified_type" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN"
```

### By username
```bash
curl -s "https://api.x.com/2/users/by/username/$USERNAME?user.fields=public_metrics,description" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

### User's posts
```bash
curl -s "https://api.x.com/2/users/$USER_ID/tweets?max_results=10&tweet.fields=created_at,public_metrics" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

### User's mentions
```bash
curl -s "https://api.x.com/2/users/$USER_ID/mentions?max_results=10&tweet.fields=created_at,public_metrics,author_id" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN"
```

## Follows

### Follow
```bash
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/following" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
```

### Unfollow
```bash
curl -s -X DELETE "https://api.x.com/2/users/$MY_USER_ID/following/$TARGET_USER_ID" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN"
```

### Get followers / following
```bash
curl -s "https://api.x.com/2/users/$USER_ID/followers?max_results=100&user.fields=public_metrics" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
curl -s "https://api.x.com/2/users/$USER_ID/following?max_results=100&user.fields=public_metrics" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

## Likes

### Like / Unlike
```bash
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/likes" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tweet_id": "TWEET_ID"}'
curl -s -X DELETE "https://api.x.com/2/users/$MY_USER_ID/likes/$TWEET_ID" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN"
```

## Blocks & Mutes

```bash
# Block
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/blocking" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
# Mute
curl -s -X POST "https://api.x.com/2/users/$MY_USER_ID/muting" \
  -H "Authorization: Bearer $X_USER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": "TARGET_USER_ID"}'
```

## Trends

```bash
curl -s "https://api.x.com/2/trends/by/woeid/$WOEID" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
# Japan: 23424856 | Tokyo: 1118370
```

## Key Fields

### tweet.fields
`id` `text` `created_at` `author_id` `public_metrics` `entities` `conversation_id` `referenced_tweets` `lang` `attachments` `note_tweet` `reply_settings`

### user.fields
`id` `name` `username` `created_at` `description` `verified` `verified_type` `public_metrics` `profile_image_url` `location` `url` `pinned_tweet_id` `connection_status`

### public_metrics (post)
`retweet_count` `reply_count` `like_count` `quote_count` `impression_count` `bookmark_count`

### public_metrics (user)
`followers_count` `following_count` `tweet_count` `listed_count`

## Rate Limits

- 15-minute windows
- Headers: `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset`
- Exceeded: HTTP 429 (error code 88)
- Use exponential backoff; prefer streaming over polling

## Pagination

```bash
curl -s "https://api.x.com/2/tweets/search/recent?query=QUERY&pagination_token=$NEXT_TOKEN" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```
Use `meta.next_token` from response.
