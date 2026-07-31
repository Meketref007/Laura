#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
ENABLED="${LAURA_SECURITY_REMINDER_ENABLED:-1}"

if ! [[ "$ENABLED" =~ ^[01]$ ]]; then
  ENABLED=1
fi

if [[ "$ENABLED" == "0" ]]; then
  echo "Laura security reminder disabled by LAURA_SECURITY_REMINDER_ENABLED=0"
  exit 0
fi

cd "$ROOT_DIR"
set -a
source "$ROOT_DIR/.env"
set +a

if [[ -z "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" || -z "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Telegram not configured; security reminder skipped."
  exit 0
fi

message="Laura Security Reminder\nHost: $(hostname)\nTime: $(date -Is)\n\nChecklist mensal:\n1) Rotacionar SHOPEE_PARTNER_KEY no Open Platform\n2) Revisar permissoes de .env/.env.bak\n3) Executar laura_self_test.sh\n4) Verificar backups e restore drill\n5) Conferir cron reconciled (laura_reconcile_cron.sh --check)"

curl -sS -X POST \
  "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${message}" \
  >/dev/null

echo "Laura security reminder sent."
