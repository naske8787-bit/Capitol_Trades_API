#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

echo "=== HEALTH $(date -u +"%Y-%m-%dT%H:%M:%SZ") ==="

for s in trading_bot crypto_bot; do
  if tmux has-session -t "$s" 2>/dev/null; then
    echo "UP   tmux:$s"
  else
    echo "DOWN tmux:$s"
    fail=1
  fi
done

if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "capitol-api.service"; then
    api_state="$(systemctl is-active capitol-api || true)"
    echo "api: $api_state (systemd)"
    [[ "$api_state" == "active" ]] || fail=1
  elif tmux has-session -t api_server 2>/dev/null; then
    echo "api: active (tmux)"
  else
    echo "api: inactive"
    fail=1
  fi

  if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -qx "capitol-dashboard.service"; then
    dash_state="$(systemctl is-active capitol-dashboard || true)"
    echo "dashboard: $dash_state (systemd)"
    [[ "$dash_state" == "active" ]] || fail=1
  elif tmux has-session -t mining_dashboard 2>/dev/null; then
    echo "dashboard: active (tmux)"
  else
    echo "dashboard: inactive"
    fail=1
  fi
fi

api_code="$(curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health || echo 000)"
dash_code="$(curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:5051/ || echo 000)"

echo "API /health: $api_code"
echo "DASH /:      $dash_code"
[[ "$api_code" == "200" ]] || fail=1
[[ "$dash_code" == "200" || "$dash_code" == "301" || "$dash_code" == "302" ]] || fail=1

if [[ $fail -eq 0 ]]; then
  echo "HEALTH: PASS"
else
  echo "HEALTH: FAIL"
fi
exit $fail
