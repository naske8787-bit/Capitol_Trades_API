#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PID_FILE="bot.pid"
LOG_FILE="bot.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Bot is running with PID $(cat "$PID_FILE")."
  echo "Last 20 log lines:"
  tail -20 "$LOG_FILE"
  exit 0
fi

echo "Bot is not running."
if [ -f "$LOG_FILE" ]; then
  echo "Last 20 log lines:"
  tail -20 "$LOG_FILE"
fi