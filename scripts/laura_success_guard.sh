#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/laura_healthcheck.log"
STATE_FILE="$LOG_DIR/laura_success_guard.state"
MAX_AGE_SECONDS="${LAURA_SUCCESS_GUARD_MAX_AGE_SECONDS:-14400}"

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

if [[ ! -f "$LOG_FILE" ]]; then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: log de health-check nao encontrado em ${LOG_FILE}."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: log not found: $LOG_FILE" >&2
  exit 1
fi

last_success_line_num="$(grep -n "\[INFO\] Laura health-check finished" "$LOG_FILE" | tail -n 1 | cut -d: -f1 || true)"
if [[ -z "$last_success_line_num" ]]; then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: nenhum sucesso de health-check encontrado no log."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: no success marker found in healthcheck log" >&2
  exit 1
fi

timestamp_line_num=$((last_success_line_num - 1))
if (( timestamp_line_num < 1 )); then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: formato inesperado no log para leitura de timestamp de sucesso."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: invalid success marker position in log" >&2
  exit 1
fi

last_ts_raw="$(sed -n "${timestamp_line_num}p" "$LOG_FILE" | tr -d '\r' | xargs)"
if [[ -z "$last_ts_raw" ]]; then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: timestamp vazio antes do ultimo sucesso no log."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: empty timestamp line before success marker" >&2
  exit 1
fi

if ! last_ts_epoch="$(date -d "$last_ts_raw" +%s 2>/dev/null)"; then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: nao foi possivel converter timestamp do log (${last_ts_raw})."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: could not parse success timestamp: $last_ts_raw" >&2
  exit 1
fi

now_ts="$(date +%s)"
age=$((now_ts - last_ts_epoch))

if (( age > MAX_AGE_SECONDS )); then
  if [[ ! -f "$STATE_FILE" ]]; then
    notify "Laura success guard: ultimo health-check bem-sucedido ha ${age}s (limite ${MAX_AGE_SECONDS}s)."
    echo "alerted" > "$STATE_FILE"
  fi
  echo "ERROR: last successful health-check is too old (${age}s)" >&2
  exit 1
fi

if [[ -f "$STATE_FILE" ]]; then
  rm -f "$STATE_FILE"
  notify "Laura success guard: operacao normalizada, sucesso recente de health-check detectado."
fi

echo "Laura success guard OK: last successful health-check ${age}s ago"
