SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

SECRETS_ROOT="${HOME}/.secrets/x-agent-manager"
ACCOUNT_NAME="$(basename "$SCRIPT_DIR")"

# Backward compatible shared-file format.
if [ -f "$SECRETS_ROOT" ]; then
  source "$SECRETS_ROOT"
fi

# New multi-account format: app-level shared config + account-specific token file.
SECRETS_APP_FILE="${SECRETS_ROOT}/config"
SECRETS_ACCOUNT_FILE="${SECRETS_ROOT}/${ACCOUNT_NAME}"

if [ -f "$SECRETS_APP_FILE" ]; then
  source "$SECRETS_APP_FILE"
fi
if [ -f "$SECRETS_ACCOUNT_FILE" ]; then
  source "$SECRETS_ACCOUNT_FILE"
fi

export X_ACCOUNT_DIR="$ACCOUNT_NAME"
export X_SECRETS_ROOT="$SECRETS_ROOT"
export X_ACCOUNT_PATH="$SCRIPT_DIR"
export X_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

: "${SLEEP_INTERVAL:=3600}"
: "${TIMEOUT_MINUTES:=60}"

# Codex CLI options used by session.sh
: "${CODEX_MODEL:=}"
: "${CODEX_USE_SEARCH:=1}"
: "${CODEX_FULL_AUTO:=1}"
# Auto publishing is opt-in. Keep off until you are confident in guardrails.
: "${AUTO_PUBLISH:=0}"
: "${AUTO_SCHEDULE:=1}"
: "${SCHEDULE_TZ:=Asia/Tokyo}"
: "${SCHEDULE_SLOTS:=07:30,12:10,20:30}"
: "${SCHEDULE_BUFFER_MINUTES:=10}"
: "${MAX_POSTS_PER_DAY:=2}"
: "${MIN_POST_INTERVAL_MINUTES:=180}"
: "${MAX_LATE_MINUTES:=720}"
