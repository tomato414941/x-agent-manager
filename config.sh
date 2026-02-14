SECRETS_FILE="${HOME}/.secrets/agent-x"
if [ -f "$SECRETS_FILE" ]; then
  source "$SECRETS_FILE"
fi

SLEEP_INTERVAL=3600
TIMEOUT_MINUTES=15

# Optional: run a pre-cycle command to let an external agent append queue items.
# Example: AGENT_PRE_CYCLE_CMD='codex exec --json "..."'
: "${AGENT_PRE_CYCLE_CMD:=}"
