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

SLEEP_INTERVAL=3600
TIMEOUT_MINUTES=20

# Codex CLI options used by session.sh
: "${CODEX_MODEL:=}"
: "${CODEX_USE_SEARCH:=1}"
: "${CODEX_FULL_AUTO:=1}"

# Optional: run a command before Codex starts (e.g., fetch external state).
: "${AGENT_PRE_CYCLE_CMD:=}"
