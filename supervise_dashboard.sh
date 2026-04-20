#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/dashboard"

LOG_FILE="/tmp/dashboard.log"
RESTART_DELAY="${RESTART_DELAY:-5}"
PYTHON_BIN="${PYTHON_BIN:-/home/codespace/.python/current/bin/python}"
# Fixed token keeps the share URL stable across restarts
export DASHBOARD_VIEW_TOKEN="${DASHBOARD_VIEW_TOKEN:-mining-share-2026}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "[$(timestamp)] Dashboard supervisor started." >> "$LOG_FILE"

while true; do
  echo "[$(timestamp)] Launching Mining Dashboard on port 5051..." >> "$LOG_FILE"
  "$PYTHON_BIN" -u app.py >> "$LOG_FILE" 2>&1
  exit_code=$?
  echo "[$(timestamp)] Dashboard exited with code $exit_code. Restarting in ${RESTART_DELAY}s..." >> "$LOG_FILE"
  sleep "$RESTART_DELAY"
done
