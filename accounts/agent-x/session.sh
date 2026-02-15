#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$SCRIPT_DIR/logs"
SESSIONS_LOG="$LOGDIR/sessions.log"

source "$SCRIPT_DIR/config.sh"
mkdir -p "$LOGDIR" "$SCRIPT_DIR/workspace/drafts" "$SCRIPT_DIR/workspace/tools" "$SCRIPT_DIR/workspace/state" "$SCRIPT_DIR/workspace/memory" "$SCRIPT_DIR/workspace/human"

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
	  if [ -n "${AGENT_PRE_CYCLE_CMD:-}" ]; then
	    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pre_cycle_start"
	    bash -lc "$AGENT_PRE_CYCLE_CMD" >>"$LOG" 2>>"$LOG.err" || true
	    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) pre_cycle_end"
	  fi

	  SKIP_CODEX=0
	  CODEX_STATE_FILE="$SCRIPT_DIR/workspace/state/last_codex_run_epoch"
	  if [ "${AUTO_PUBLISH:-0}" = "1" ]; then
	    MIN_INTERVAL="${CODEX_MIN_INTERVAL_SECONDS:-43200}"
	    if [ "$MIN_INTERVAL" -gt 0 ]; then
	      LAST_EPOCH=0
	      if [ -f "$CODEX_STATE_FILE" ]; then
	        LAST_RAW="$(cat "$CODEX_STATE_FILE" 2>/dev/null || true)"
	        if echo "$LAST_RAW" | grep -Eq '^[0-9]+$'; then
	          LAST_EPOCH="$LAST_RAW"
	        fi
	      fi
	      NOW_EPOCH="$(date +%s)"
	      ELAPSED="$((NOW_EPOCH - LAST_EPOCH))"
	      if [ "$ELAPSED" -lt "$MIN_INTERVAL" ]; then
	        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) codex_skipped reason=min_interval elapsed_seconds=$ELAPSED min_interval_seconds=$MIN_INTERVAL"
	        EXIT_STATUS=0
	        SKIP_CODEX=1
	      fi
	    fi
	  fi

	  if [ "$SKIP_CODEX" = "0" ]; then
	    CODEX_PREFIX_ARGS=()
	    # Global options must come before the subcommand (e.g., `codex --search exec ...`).
	    if [ "${CODEX_USE_SEARCH:-0}" = "1" ]; then
	      CODEX_PREFIX_ARGS+=(--search)
	    fi

	    CODEX_ARGS=(exec --cd "$SCRIPT_DIR" --output-last-message "$LAST_MESSAGE")
	    # `--ephemeral` exists in newer Codex CLI versions; older versions error out.
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

	    if [ "${EXIT_STATUS:-1}" = "0" ]; then
	      date +%s >"$CODEX_STATE_FILE"
	    fi
	  fi
	
	  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) codex_exit code=$EXIT_STATUS log=$LOG last_message=$LAST_MESSAGE"
	} >>"$SESSIONS_LOG"

exit "${EXIT_STATUS:-0}"
