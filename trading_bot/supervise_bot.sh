#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"

LOG_FILE="bot.log"
SUPERVISOR_LOG="supervisor.log"
RESTART_DELAY="${RESTART_DELAY:-10}"
PYTHON_BIN="${PYTHON_BIN:-python}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "[$(timestamp)] Supervisor started. Auto-restart is enabled." >> "$SUPERVISOR_LOG"

while true; do
  echo "[$(timestamp)] Launching trading bot..." >> "$SUPERVISOR_LOG"
  "$PYTHON_BIN" -u main.py >> "$LOG_FILE" 2>&1
  exit_code=$?
  echo "[$(timestamp)] Bot exited with code $exit_code. Restarting in ${RESTART_DELAY}s..." >> "$SUPERVISOR_LOG"
  sleep "$RESTART_DELAY"
done
