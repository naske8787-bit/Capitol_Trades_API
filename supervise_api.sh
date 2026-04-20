#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"

LOG_FILE="api_server.log"
RESTART_DELAY="${RESTART_DELAY:-5}"
PYTHON_BIN="${PYTHON_BIN:-/home/codespace/.python/current/bin/python}"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "[$(timestamp)] API server supervisor started." >> "$LOG_FILE"

while true; do
  echo "[$(timestamp)] Launching API server..." >> "$LOG_FILE"
  "$PYTHON_BIN" -u run.py >> "$LOG_FILE" 2>&1
  exit_code=$?
  echo "[$(timestamp)] API server exited with code $exit_code. Restarting in ${RESTART_DELAY}s..." >> "$LOG_FILE"
  sleep "$RESTART_DELAY"
done
