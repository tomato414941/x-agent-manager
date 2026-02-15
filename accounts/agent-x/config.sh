SECRETS_FILE="${HOME}/.secrets/x-agent-manager"
if [ -f "$SECRETS_FILE" ]; then
  source "$SECRETS_FILE"
fi

SLEEP_INTERVAL=3600
TIMEOUT_MINUTES=20

# Codex CLI options used by session.sh
: "${CODEX_MODEL:=}"
: "${CODEX_USE_SEARCH:=1}"
: "${CODEX_FULL_AUTO:=1}"

# Optional: run a command before Codex starts (e.g., fetch external state).
: "${AGENT_PRE_CYCLE_CMD:=}"
