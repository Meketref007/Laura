#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
REPORT_DIR="$ROOT_DIR/reports"
LOCK_FILE="$LOG_DIR/laura_webhook_tunnel_guard.lock"
LOG_FILE="$LOG_DIR/laura_webhook_tunnel_guard.log"
LATEST_URL_FILE="$REPORT_DIR/laura_webhook_tunnel_latest.txt"
LATEST_CALLBACK_FILE="$REPORT_DIR/laura_webhook_callback_latest.txt"

mkdir -p "$LOG_DIR" "$REPORT_DIR"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

PORT="${LAURA_WEBHOOK_PORT:-8765}"
CALLBACK_PATH="${LAURA_WEBHOOK_PATH:-/webhook/shopee}"

if [[ -z "$CALLBACK_PATH" ]]; then
  CALLBACK_PATH="/webhook/shopee"
fi
if [[ "$CALLBACK_PATH" != /* ]]; then
  CALLBACK_PATH="/$CALLBACK_PATH"
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0
fi

if pgrep -f "cloudflared tunnel --config .* --no-autoupdate run" >/dev/null 2>&1; then
  exit 0
fi

previous_url=""
if [[ -f "$LATEST_URL_FILE" ]]; then
  previous_url="$(head -n 1 "$LATEST_URL_FILE" || true)"
fi

{
  date -Is
  echo "[WARN] Tunnel down. Reiniciando tunnel permanente..."
} >> "$LOG_FILE"

nohup bash "$ROOT_DIR/scripts/laura_tunnel_permanent.sh" ensure >> "$LOG_FILE" 2>&1 &

sleep 3
latest_url="unknown"
if [[ -f "$LATEST_URL_FILE" ]]; then
  latest_url="$(head -n 1 "$LATEST_URL_FILE" || true)"
fi

latest_callback="unknown"
if [[ -f "$LATEST_CALLBACK_FILE" ]]; then
  latest_callback="$(head -n 1 "$LATEST_CALLBACK_FILE" || true)"
elif [[ "$latest_url" != "unknown" && -n "$latest_url" ]]; then
  latest_callback="${latest_url}${CALLBACK_PATH}"
fi

if [[ -n "$previous_url" && -n "$latest_url" && "$latest_url" != "unknown" && "$latest_url" != "$previous_url" ]]; then
  {
    date -Is
    echo "[WARN] Tunnel URL mudou: $previous_url -> $latest_url"
    echo "[WARN] Nova callback URL: $latest_callback"
  } >> "$LOG_FILE"
fi

if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  msg="Laura webhook tunnel foi reiniciado. Callback atual: ${latest_callback}."
  if [[ -n "$previous_url" && "$latest_url" != "unknown" && "$latest_url" != "$previous_url" ]]; then
    msg="${msg} URL mudou de ${previous_url} para ${latest_url}. Atualize o Live Call Back URL na Shopee."
  fi
  curl -sS -X POST \
    "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${msg}" \
    >/dev/null || true
fi
