#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
REPORT_DIR="$ROOT_DIR/reports"
LOCK_FILE="$LOG_DIR/laura_webhook_tunnel.lock"
LOG_FILE="$LOG_DIR/laura_webhook_tunnel.log"
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
TARGET_URL="http://127.0.0.1:${PORT}"
CLOUDFLARED_BIN="${LAURA_CLOUDFLARED_BIN:-$ROOT_DIR/tools/cloudflared}"
CALLBACK_PATH="${LAURA_WEBHOOK_PATH:-/webhook/shopee}"

if [[ -z "$CALLBACK_PATH" ]]; then
  CALLBACK_PATH="/webhook/shopee"
fi
if [[ "$CALLBACK_PATH" != /* ]]; then
  CALLBACK_PATH="/$CALLBACK_PATH"
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] LAURA_WEBHOOK_PORT invalida: $PORT" >&2
  exit 1
fi

if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED_BIN="$(command -v cloudflared)"
  else
    echo "[ERROR] cloudflared nao encontrado. Defina LAURA_CLOUDFLARED_BIN ou instale em $ROOT_DIR/tools/cloudflared" >&2
    exit 1
  fi
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[WARN] tunnel ja esta em execucao (lock ativo: $LOCK_FILE)" >&2
  exit 0
fi

# Ensure local webhook is up before exposing via tunnel.
if ! curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
  nohup "$ROOT_DIR/scripts/laura_webhook_start.sh" >/dev/null 2>&1 &
  for _ in $(seq 1 10); do
    if curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

if ! curl -sSf "$TARGET_URL/health" >/dev/null 2>&1; then
  echo "[ERROR] webhook local indisponivel em $TARGET_URL" >&2
  exit 1
fi

{
  date -Is
  echo "[INFO] Iniciando tunnel cloudflared para $TARGET_URL"
  echo "[INFO] Binario: $CLOUDFLARED_BIN"
} >> "$LOG_FILE"

"$CLOUDFLARED_BIN" tunnel --url "$TARGET_URL" --no-autoupdate 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line" >> "$LOG_FILE"

  if [[ "$line" =~ https://[a-zA-Z0-9.-]+\.trycloudflare\.com ]]; then
    tunnel_url="${BASH_REMATCH[0]}"
    callback_url="${tunnel_url}${CALLBACK_PATH}"
    printf '%s\n' "$tunnel_url" > "$LATEST_URL_FILE"
    printf '%s\n' "$callback_url" > "$LATEST_CALLBACK_FILE"
    {
      date -Is
      echo "[INFO] Tunnel URL atual: $tunnel_url"
      echo "[INFO] Callback URL atual: $callback_url"
    } >> "$LOG_FILE"
  fi
done
