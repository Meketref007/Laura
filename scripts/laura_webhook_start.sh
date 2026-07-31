#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
LOCK_FILE="$LOG_DIR/laura_webhook.lock"
LOG_FILE="$LOG_DIR/laura_webhook.log"
PY_CMD="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PY_CMD" ]]; then
  PY_CMD="python3"
fi

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

HOST="${LAURA_WEBHOOK_HOST:-127.0.0.1}"
PORT="${LAURA_WEBHOOK_PORT:-8765}"
PUBLIC_BASE_URL="${LAURA_WEBHOOK_PUBLIC_BASE_URL:-https://agente-laura.myddns.me}"
CALLBACK_PATH="${LAURA_WEBHOOK_PATH:-/webhook/shopee}"
SECRET_KEY="${LAURA_WEBHOOK_SECRET:-}"
ALLOW_UNVERIFIED="${LAURA_WEBHOOK_ALLOW_UNVERIFIED_ACK:-1}"

if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] LAURA_WEBHOOK_PORT invalida: $PORT" >&2
  exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[WARN] webhook já está em execução (lock ativo: $LOCK_FILE)" >&2
  exit 0
fi

{
  date -Is
  echo "[INFO] Iniciando webhook Laura em $HOST:$PORT"
  echo "[INFO] Callback sugerida: ${PUBLIC_BASE_URL%/}${CALLBACK_PATH}"
  echo "[INFO] allow_unverified_ack=$ALLOW_UNVERIFIED"
} >> "$LOG_FILE"

if [[ -n "$SECRET_KEY" ]]; then
  exec "$PY_CMD" -m shopee_agent.cli webhook-start \
    --host "$HOST" \
    --port "$PORT" \
    --secret-key "$SECRET_KEY" \
    --public-base-url "$PUBLIC_BASE_URL" \
    --callback-path "$CALLBACK_PATH" \
    $([ "$ALLOW_UNVERIFIED" = "1" ] && echo "--allow-unverified-ack" || true) >> "$LOG_FILE" 2>&1
else
  exec "$PY_CMD" -m shopee_agent.cli webhook-start \
    --host "$HOST" \
    --port "$PORT" \
    --public-base-url "$PUBLIC_BASE_URL" \
    --callback-path "$CALLBACK_PATH" \
    $([ "$ALLOW_UNVERIFIED" = "1" ] && echo "--allow-unverified-ack" || true) >> "$LOG_FILE" 2>&1
fi
