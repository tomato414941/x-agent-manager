#!/usr/bin/env bash
# Refresh X API OAuth2 access token using the stored refresh token.
# Reads current tokens from secrets file, calls the refresh endpoint,
# and overwrites the secrets file with the new token pair.
#
# cron example (every hour):
#   0 * * * * /home/dev/projects/x-agent-manager/scripts/refresh_token.sh /home/dev/projects/x-agent-manager/accounts/agent-x >> /home/dev/projects/x-agent-manager/accounts/agent-x/logs/refresh.log 2>&1
set -euo pipefail

ACCOUNT_DIR="${1:?usage: refresh_token.sh <account-dir>}"
ACCOUNT_DIR="$(cd "$ACCOUNT_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load secrets (same logic as config.sh)
SECRETS_ROOT="${HOME}/.secrets/x-agent-manager"
ACCOUNT_NAME="$(basename "$ACCOUNT_DIR")"

if [ -f "$SECRETS_ROOT" ]; then
  source "$SECRETS_ROOT"
fi
if [ -f "$SECRETS_ROOT/config" ]; then
  source "$SECRETS_ROOT/config"
fi
if [ -f "$SECRETS_ROOT/$ACCOUNT_NAME" ]; then
  source "$SECRETS_ROOT/$ACCOUNT_NAME"
fi

REFRESH_TOKEN="${X_REFRESH_TOKEN:-}"
CLIENT_ID="${X_CLIENT_ID:-}"

if [ -z "$REFRESH_TOKEN" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip: X_REFRESH_TOKEN not set"
  exit 0
fi
if [ -z "$CLIENT_ID" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip: X_CLIENT_ID not set"
  exit 0
fi

RESPONSE="$(curl -sS -X POST https://api.x.com/2/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token&refresh_token=${REFRESH_TOKEN}&client_id=${CLIENT_ID}")"

NEW_ACCESS="$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")"
NEW_REFRESH="$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('refresh_token',''))")"

if [ -z "$NEW_ACCESS" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) error: refresh failed"
  echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''), d.get('error_description',''))" 2>/dev/null || true
  exit 1
fi

# Determine secrets file path
if [ -f "$SECRETS_ROOT" ]; then
  SECRETS_FILE="$SECRETS_ROOT"
else
  SECRETS_FILE="$SECRETS_ROOT/$ACCOUNT_NAME"
fi

# Update tokens in-place (preserve other lines)
python3 - "$SECRETS_FILE" "$NEW_ACCESS" "$NEW_REFRESH" <<'PY'
import sys, pathlib

path, new_access, new_refresh = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
updates = {"X_ACCESS_TOKEN": new_access}
if new_refresh:
    updates["X_REFRESH_TOKEN"] = new_refresh

lines = path.read_text().splitlines() if path.exists() else []
out, written = [], set()
for line in lines:
    s = line.strip()
    if s.startswith("export "):
        s = s[len("export "):].lstrip()
    key = s.split("=", 1)[0].strip() if "=" in s else None
    if key and key in updates:
        out.append(f'export {key}="{updates[key]}"')
        written.add(key)
    else:
        out.append(line)
for key, val in updates.items():
    if key not in written:
        out.append(f'export {key}="{val}"')
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
PY

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ok: token refreshed"
