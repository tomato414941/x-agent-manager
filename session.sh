#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$SCRIPT_DIR/logs"
SESSIONS_LOG="$LOGDIR/sessions.log"

source "$SCRIPT_DIR/config.sh"
mkdir -p "$LOGDIR" "$SCRIPT_DIR/workspace/state" "$SCRIPT_DIR/workspace/memory" "$SCRIPT_DIR/workspace/secrets"

LOG="$LOGDIR/$(date +%Y%m%d_%H%M%S).log"

{
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) session_start"
  if [ -n "${AGENT_PRE_CYCLE_CMD:-}" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pre_cycle_start"
    bash -lc "$AGENT_PRE_CYCLE_CMD" >>"$LOG" 2>>"$LOG.err" || true
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pre_cycle_end"
  fi

  if timeout "${TIMEOUT_MINUTES:-15}m" node "$SCRIPT_DIR/src/cli.js" run-cycle >>"$LOG" 2>>"$LOG.err"; then
    EXIT_STATUS=0
  else
    EXIT_STATUS=$?
  fi

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cycle_exit code=$EXIT_STATUS log=$LOG"
} >>"$SESSIONS_LOG"

exit "${EXIT_STATUS:-0}"
