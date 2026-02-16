---
name: x-developer
description: X Developer Platform operations. Use for X API authentication troubleshooting, token management, usage/credit monitoring, secrets configuration, and 401/403 error diagnosis.
---

# X Developer Platform Operations

## Authentication Types

| Method | Variable | Use case | Example endpoints |
|---|---|---|---|
| OAuth 2.0 User Token | `$X_ACCESS_TOKEN` | User actions (post, like, follow, DM) | `POST /2/tweets`, `GET /2/users/me` |
| App-Only Bearer Token | `$X_APP_BEARER_TOKEN` | Read-only, platform-level | `GET /2/usage/tweets`, `GET /2/tweets/search/recent` |
| OAuth 1.0a | API Key + Secret | Legacy user context | Rarely needed with v2 |

**Important**: Some endpoints ONLY accept App-Only Bearer Token and will return `403 Unsupported Authentication` with a User Token. Known App-Only-only endpoints:
- `GET /2/usage/tweets`

## Secrets Variable Mapping

### App-wide config: `~/.secrets/x-agent-manager/config`
| Variable | Purpose |
|---|---|
| `X_CLIENT_ID` | OAuth 2.0 client ID |
| `X_REDIRECT_URI` | OAuth callback URL |
| `X_SCOPES` | Requested OAuth scopes |
| `X_APP_BEARER_TOKEN` | App-Only Bearer Token (read-only / platform) |
| `EXPECTED_HOSTNAME` | Hostname validation |
| `AUTO_PUBLISH` | Auto-publish flag |
| `AUTO_SCHEDULE` | Auto-schedule flag |

### Per-account tokens: `~/.secrets/x-agent-manager/<account>`
| Variable | Purpose |
|---|---|
| `X_ACCESS_TOKEN` | OAuth 2.0 User Access Token (2h TTL) |
| `X_REFRESH_TOKEN` | OAuth 2.0 Refresh Token |

### Load secrets
```bash
source ~/.secrets/x-agent-manager/config       # App keys + App-Only Bearer
source ~/.secrets/x-agent-manager/<account>     # User tokens
```

### Common confusion: variable names
- `X_ACCESS_TOKEN` = User Access Token (the actual variable in secrets)
- `X_APP_BEARER_TOKEN` = App-Only Bearer Token (the actual variable in secrets)
- Do NOT use `X_USER_ACCESS_TOKEN` or `X_BEARER_TOKEN` — these are not defined in secrets

## Usage Monitoring

**Requires App-Only Bearer Token** (`$X_APP_BEARER_TOKEN`), NOT User Token.

```bash
curl -s "https://api.x.com/2/usage/tweets" \
  -H "Authorization: Bearer $X_APP_BEARER_TOKEN"
```

### Response fields
| Field | Meaning | NOT |
|---|---|---|
| `project_cap` | Monthly usage budget cap (tweet cap) | ~~Credit balance~~ |
| `project_usage` | Tweets used this billing period | |
| `cap_reset_day` | Day of month when usage resets | |

**Credit balance is NOT available via API.** Check the Developer Console: https://console.x.com/

## 401/403 Troubleshooting

### Step-by-step diagnosis

```bash
# 1. Check variable is not empty
echo "X_ACCESS_TOKEN len=${#X_ACCESS_TOKEN}"
echo "X_APP_BEARER_TOKEN len=${#X_APP_BEARER_TOKEN}"

# 2. Verify user token with /users/me
curl -s "https://api.x.com/2/users/me" \
  -H "Authorization: Bearer $X_ACCESS_TOKEN"
# Expected: {"data":{"id":"...","name":"...","username":"..."}}
```

### Decision tree

| Symptom | Cause | Fix |
|---|---|---|
| Variable is empty (len=0) | Wrong variable name or secrets not loaded | Check `~/.secrets/x-agent-manager/` variable names, re-source |
| `401 Unauthorized` | Token expired (2h TTL) | Refresh: `POST /2/oauth2/token` with `grant_type=refresh_token` |
| `403 Unsupported Authentication` | Wrong auth type for endpoint | Switch between User Token and App-Only Bearer Token |
| `403 Forbidden` | Missing OAuth scope | Check required scopes for the endpoint |

### Token refresh
```bash
curl -s -X POST "https://api.x.com/2/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token&refresh_token=$X_REFRESH_TOKEN&client_id=$X_CLIENT_ID"
```
Update `X_ACCESS_TOKEN` and `X_REFRESH_TOKEN` in the secrets file after refresh.
