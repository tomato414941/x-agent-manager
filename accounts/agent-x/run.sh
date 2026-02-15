#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/workspace/drafts" "$SCRIPT_DIR/workspace/tools" "$SCRIPT_DIR/workspace/state" "$SCRIPT_DIR/workspace/memory" "$SCRIPT_DIR/workspace/human"

while true; do
  source "$SCRIPT_DIR/config.sh"
  bash "$SCRIPT_DIR/session.sh"
  sleep "${SLEEP_INTERVAL:-3600}"
done
