#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Missing LAURA_ALERT_TELEGRAM_BOT_TOKEN in .env" >&2
  exit 1
fi

if [[ -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Missing LAURA_ALERT_TELEGRAM_CHAT_ID in .env" >&2
  exit 1
fi

message="Laura alert channel test OK on $(hostname) at $(date -Is)"

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}"

echo
echo "Telegram alert test sent."
