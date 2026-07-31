#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/laura_healthcheck.log"
STATE_FILE="$LOG_DIR/laura_watchdog.state"
MAX_AGE_SECONDS="${LAURA_WATCHDOG_MAX_AGE_SECONDS:-14400}"

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if ! [[ "$MAX_AGE_SECONDS" =~ ^[0-9]+$ ]]; then
  MAX_AGE_SECONDS=14400
fi

notify() {
  local message="$1"

  if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    curl -sS -X POST \
      "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${message}" \
      >/dev/null || true
  fi
}

mkdir -p "$LOG_DIR"

if [[ ! -f "$LOG_FILE" ]]; then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura watchdog: log do health-check nao encontrado em ${LOG_FILE}."
    echo "alerted" > "$STATE_FILE"
  fi
  exit 1
fi

now_ts=$(date +%s)
log_ts=$(stat -c %Y "$LOG_FILE")
age=$((now_ts - log_ts))

if (( age > MAX_AGE_SECONDS )); then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura watchdog: health-check sem atualizacao ha ${age}s (limite ${MAX_AGE_SECONDS}s)."
    echo "alerted" > "$STATE_FILE"
  fi
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura watchdog: operacao normalizada, health-check voltou a atualizar logs."
fi

echo "Laura watchdog OK: ultimo update ha ${age}s"
