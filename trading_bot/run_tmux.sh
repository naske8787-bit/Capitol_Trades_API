#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

SESSION_NAME="trading_bot"
LOG_FILE="bot.log"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed. Install tmux and try again."
  exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Session '$SESSION_NAME' already exists. Attach with: tmux attach -t $SESSION_NAME"
  exit 1
fi

# Start tmux session and run the bot
TMUX_CMD="cd \"$(pwd)\" && nohup python main.py > '$LOG_FILE' 2>&1"

tmux new-session -d -s "$SESSION_NAME" "$TMUX_CMD"
echo "Started bot in tmux session '$SESSION_NAME'."
echo "Attach with: tmux attach -t $SESSION_NAME"
echo "Logs: $LOG_FILE"