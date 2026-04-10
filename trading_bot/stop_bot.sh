#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PID_FILE="bot.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file found. Bot may not be running."
  exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  rm -f "$PID_FILE"
  echo "Stopped bot with PID $PID."
else
  echo "Process $PID is not running. Removing stale PID file."
  rm -f "$PID_FILE"
fi