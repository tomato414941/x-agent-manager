#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$SCRIPT_DIR/logs"
SESSIONS_LOG="$LOGDIR/sessions.log"

source "$SCRIPT_DIR/config.sh"
mkdir -p "$LOGDIR" "$SCRIPT_DIR/workspace"

HUMAN_MESSAGES="$SCRIPT_DIR/workspace/human/messages.md"
HUMAN_REQUESTS="$SCRIPT_DIR/workspace/human/requests.md"

if [ ! -f "$HUMAN_MESSAGES" ]; then
  : >"$HUMAN_MESSAGES"
fi
if [ ! -f "$HUMAN_REQUESTS" ]; then
  : >"$HUMAN_REQUESTS"
fi

TS="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/${TS}.log"
LAST_MESSAGE="$LOGDIR/${TS}.last_message.txt"

{
  cd "$SCRIPT_DIR"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) session_start"

  CODEX_PREFIX_ARGS=()
  if [ "${CODEX_USE_SEARCH:-0}" = "1" ]; then
    CODEX_PREFIX_ARGS+=(--search)
  fi

  CODEX_ARGS=(exec --cd "$SCRIPT_DIR" --output-last-message "$LAST_MESSAGE")
  if codex exec --help 2>/dev/null | grep -q -- '--ephemeral'; then
    CODEX_ARGS+=(--ephemeral)
  fi
  if [ "${CODEX_FULL_AUTO:-1}" = "1" ]; then
    CODEX_ARGS+=(--full-auto)
  else
    CODEX_ARGS+=(--sandbox workspace-write)
  fi

  if [ -n "${CODEX_MODEL:-}" ]; then
    CODEX_ARGS+=(--model "$CODEX_MODEL")
  fi

  CODEX_ARGS+=(-)

  if timeout "${TIMEOUT_MINUTES:-20}m" codex "${CODEX_PREFIX_ARGS[@]}" "${CODEX_ARGS[@]}" <"$SCRIPT_DIR/AGENT_PROMPT.md" >>"$LOG" 2>>"$LOG.err"; then
    EXIT_STATUS=0
  else
    EXIT_STATUS=$?
  fi

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) codex_exit code=$EXIT_STATUS log=$LOG last_message=$LAST_MESSAGE"
} >>"$SESSIONS_LOG"

exit "${EXIT_STATUS:-0}"
