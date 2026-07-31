#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
LOG_DIR="$ROOT_DIR/logs"
REPORT_DIR="$ROOT_DIR/reports"
LOCK_FILE="$LOG_DIR/laura_webhook_ready_guard.lock"
LOG_FILE="$LOG_DIR/laura_webhook_ready_guard.log"
STATE_FILE="$REPORT_DIR/laura_webhook_ready_guard.state"
AUDIT_FILE="$REPORT_DIR/laura_webhook_ready_audit.jsonl"

mkdir -p "$LOG_DIR" "$REPORT_DIR"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ "${LAURA_WEBHOOK_READY_GUARD_ENABLED:-1}" != "1" ]]; then
  exit 0
fi

ALERT_STREAK="${LAURA_WEBHOOK_READY_ALERT_STREAK:-2}"
NOTIFY_RECOVERY="${LAURA_WEBHOOK_READY_NOTIFY_RECOVERY:-1}"
AUTO_HEAL="${LAURA_WEBHOOK_READY_AUTO_HEAL:-1}"
AUTO_HEAL_RETRIES="${LAURA_WEBHOOK_READY_AUTO_HEAL_RETRIES:-1}"
NOTIFY_AUTO_HEAL="${LAURA_WEBHOOK_READY_NOTIFY_AUTO_HEAL:-1}"
AUDIT_ENABLED="${LAURA_WEBHOOK_READY_AUDIT_ENABLED:-1}"
RESOLVER_ALERT_ENABLED="${LAURA_WEBHOOK_READY_RESOLVER_ALERT_ENABLED:-1}"
RESOLVER_ALERT_STREAK="${LAURA_WEBHOOK_READY_RESOLVER_ALERT_STREAK:-3}"

if ! [[ "$ALERT_STREAK" =~ ^[0-9]+$ ]]; then
  ALERT_STREAK=2
fi
if (( ALERT_STREAK < 1 )); then
  ALERT_STREAK=1
fi

if ! [[ "$AUTO_HEAL_RETRIES" =~ ^[0-9]+$ ]]; then
  AUTO_HEAL_RETRIES=1
fi
if (( AUTO_HEAL_RETRIES < 0 )); then
  AUTO_HEAL_RETRIES=0
fi

if ! [[ "$RESOLVER_ALERT_STREAK" =~ ^[0-9]+$ ]]; then
  RESOLVER_ALERT_STREAK=3
fi
if (( RESOLVER_ALERT_STREAK < 1 )); then
  RESOLVER_ALERT_STREAK=1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0
fi

# shellcheck disable=SC1090
if [[ -f "$STATE_FILE" ]]; then
  source "$STATE_FILE"
fi

fail_streak="${fail_streak:-0}"
alert_active="${alert_active:-0}"
last_status="${last_status:-unknown}"
last_callback_url="${last_callback_url:-unknown}"
last_failure_reason="${last_failure_reason:-unknown}"
resolver_fail_streak="${resolver_fail_streak:-0}"
resolver_alert_active="${resolver_alert_active:-0}"
last_resolver_source="${last_resolver_source:-unknown}"
last_dns_server="${last_dns_server:-unknown}"
last_unsigned_attempts="${last_unsigned_attempts:-0}"
last_signed_attempts="${last_signed_attempts:-0}"

run_readiness_check() {
  local output_file="/tmp/laura_webhook_ready_guard_tmp.out"
  if "$ROOT_DIR/scripts/laura_webhook_shopee_ready.sh" >"$output_file" 2>&1; then
    RUN_EXIT=0
  else
    RUN_EXIT=$?
  fi
  RUN_OUTPUT="$(cat "$output_file" 2>/dev/null || true)"
}

attempt_auto_heal() {
  {
    date -Is
    echo "[WARN] Executando auto-heal de webhook readiness"
  } >> "$LOG_FILE"

  nohup "$ROOT_DIR/scripts/laura_webhook_start.sh" >/dev/null 2>&1 &
  sleep 2
  nohup bash "$ROOT_DIR/scripts/laura_tunnel_permanent.sh" ensure >/dev/null 2>&1 &
  sleep 2
}

send_telegram() {
  local text="$1"
  if [[ -n "${LAURA_ALERT_TELEGRAM_BOT_TOKEN:-}" && -n "${LAURA_ALERT_TELEGRAM_CHAT_ID:-}" ]]; then
    curl -sS -X POST \
      "https://api.telegram.org/bot${LAURA_ALERT_TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${LAURA_ALERT_TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${text}" \
      >/dev/null || true
  fi
}

json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "$value"
}

RUN_EXIT=0
RUN_OUTPUT=""
run_readiness_check
auto_healed=0

if (( RUN_EXIT != 0 )) && [[ "$AUTO_HEAL" == "1" ]] && (( AUTO_HEAL_RETRIES > 0 )); then
  for _ in $(seq 1 "$AUTO_HEAL_RETRIES"); do
    attempt_auto_heal
    run_readiness_check
    if (( RUN_EXIT == 0 )); then
      auto_healed=1
      break
    fi
  done
fi

run_output="$RUN_OUTPUT"
run_exit=$RUN_EXIT

callback_url="$(printf '%s\n' "$run_output" | awk -F= '/^callback_url=/{print $2}' | tail -n 1)"
result_line="$(printf '%s\n' "$run_output" | awk -F= '/^result=/{print $2}' | tail -n 1)"
message_line="$(printf '%s\n' "$run_output" | awk -F= '/^message=/{print $2}' | tail -n 1)"
unsigned_code="$(printf '%s\n' "$run_output" | awk -F= '/^unsigned_code=/{print $2}' | tail -n 1)"
signed_code="$(printf '%s\n' "$run_output" | awk -F= '/^signed_code=/{print $2}' | tail -n 1)"
unsigned_latency_seconds="$(printf '%s\n' "$run_output" | awk -F= '/^unsigned_latency_seconds=/{print $2}' | tail -n 1)"
signed_latency_seconds="$(printf '%s\n' "$run_output" | awk -F= '/^signed_latency_seconds=/{print $2}' | tail -n 1)"
unsigned_attempts="$(printf '%s\n' "$run_output" | awk -F= '/^unsigned_attempts=/{print $2}' | tail -n 1)"
signed_attempts="$(printf '%s\n' "$run_output" | awk -F= '/^signed_attempts=/{print $2}' | tail -n 1)"
resolver_source="$(printf '%s\n' "$run_output" | awk -F= '/^resolver_source=/{print $2}' | tail -n 1)"
dns_server="$(printf '%s\n' "$run_output" | awk -F= '/^dns_server=/{print $2}' | tail -n 1)"

if [[ -z "$callback_url" ]]; then
  callback_url="unknown"
fi
if [[ -z "$unsigned_code" ]]; then
  unsigned_code="unknown"
fi
if [[ -z "$signed_code" ]]; then
  signed_code="unknown"
fi
if [[ -z "$unsigned_latency_seconds" ]]; then
  unsigned_latency_seconds="unknown"
fi
if [[ -z "$signed_latency_seconds" ]]; then
  signed_latency_seconds="unknown"
fi
if [[ -z "$resolver_source" ]]; then
  resolver_source="unknown"
fi
if [[ -z "$dns_server" ]]; then
  dns_server="unknown"
fi
if ! [[ "$unsigned_attempts" =~ ^[0-9]+$ ]]; then
  unsigned_attempts=0
fi
if ! [[ "$signed_attempts" =~ ^[0-9]+$ ]]; then
  signed_attempts=0
fi

resolver_prev_source="$last_resolver_source"
resolver_drift=0
resolver_drift_reason="none"

if [[ "$RESOLVER_ALERT_ENABLED" == "1" ]] && (( run_exit == 0 )); then
  if [[ "$resolver_prev_source" != "unknown" && "$resolver_source" != "unknown" && "$resolver_source" != "$resolver_prev_source" ]]; then
    resolver_drift=1
    resolver_drift_reason="resolver_source_changed"
  fi

  if (( resolver_drift == 1 )); then
    resolver_fail_streak=$((resolver_fail_streak + 1))
    {
      date -Is
      echo "[WARN] Resolver drift detectado (streak=${resolver_fail_streak}, previous=${resolver_prev_source}, current=${resolver_source}, dns_server=${dns_server})"
    } >> "$LOG_FILE"

    if (( resolver_fail_streak >= RESOLVER_ALERT_STREAK )) && [[ "$resolver_alert_active" != "1" ]]; then
      send_telegram "Laura webhook readiness: drift de resolver detectado (streak=${resolver_fail_streak}, previous=${resolver_prev_source}, current=${resolver_source}, dns_server=${dns_server})."
      resolver_alert_active=1
    fi
  else
    resolver_fail_streak=0
    if [[ "$resolver_alert_active" == "1" && "$NOTIFY_RECOVERY" == "1" ]]; then
      send_telegram "Laura webhook readiness: resolver normalizado (${resolver_source}, dns_server=${dns_server})."
    fi
    resolver_alert_active=0
  fi
fi

if (( run_exit == 0 )); then
  last_resolver_source="$resolver_source"
  last_dns_server="$dns_server"
  last_unsigned_attempts="$unsigned_attempts"
  last_signed_attempts="$signed_attempts"
fi

if (( run_exit == 0 )); then
  fail_streak=0
  last_status="ok"
  last_callback_url="$callback_url"
  last_failure_reason="none"

  {
    date -Is
    echo "[INFO] Webhook readiness OK (callback=${callback_url}, result=${result_line:-ready})"
    if (( auto_healed == 1 )); then
      echo "[INFO] Webhook readiness auto-healed antes do alerta"
    fi
  } >> "$LOG_FILE"

  if [[ "$alert_active" == "1" && "$NOTIFY_RECOVERY" == "1" ]]; then
    send_telegram "Laura webhook readiness recuperado. Callback atual: ${callback_url}."
  fi

  if (( auto_healed == 1 )) && [[ "$NOTIFY_AUTO_HEAL" == "1" ]]; then
    send_telegram "Laura webhook readiness auto-heal aplicado com sucesso. Callback atual: ${callback_url}."
  fi

  alert_active=0
else
  fail_streak=$((fail_streak + 1))
  last_status="fail"
  last_callback_url="$callback_url"
  last_failure_reason="${message_line:-unknown}"

  {
    date -Is
    echo "[WARN] Webhook readiness FAIL (streak=${fail_streak}, callback=${callback_url}, reason=${last_failure_reason})"
    echo "$run_output"
  } >> "$LOG_FILE"

  if (( fail_streak >= ALERT_STREAK )) && [[ "$alert_active" != "1" ]]; then
    send_telegram "Laura webhook readiness em falha (streak=${fail_streak}, reason=${last_failure_reason}). Callback atual: ${callback_url}."
    alert_active=1
  fi
fi

if [[ "$AUDIT_ENABLED" == "1" ]]; then
  ts="$(date -Is)"
  printf '{"timestamp":"%s","status":"%s","run_exit":%s,"auto_healed":%s,"fail_streak":%s,"alert_active":%s,"callback_url":"%s","result":"%s","reason":"%s","unsigned_code":"%s","signed_code":"%s","unsigned_latency_seconds":"%s","signed_latency_seconds":"%s","unsigned_attempts":%s,"signed_attempts":%s,"resolver_source":"%s","dns_server":"%s","resolver_drift":%s,"resolver_fail_streak":%s,"resolver_alert_active":%s,"resolver_drift_reason":"%s"}\n' \
    "$(json_escape "$ts")" \
    "$(json_escape "$last_status")" \
    "$run_exit" \
    "$auto_healed" \
    "$fail_streak" \
    "$alert_active" \
    "$(json_escape "$callback_url")" \
    "$(json_escape "${result_line:-unknown}")" \
    "$(json_escape "$last_failure_reason")" \
    "$(json_escape "$unsigned_code")" \
    "$(json_escape "$signed_code")" \
    "$(json_escape "$unsigned_latency_seconds")" \
    "$(json_escape "$signed_latency_seconds")" \
    "$unsigned_attempts" \
    "$signed_attempts" \
    "$(json_escape "$resolver_source")" \
    "$(json_escape "$dns_server")" \
    "$resolver_drift" \
    "$resolver_fail_streak" \
    "$resolver_alert_active" \
    "$(json_escape "$resolver_drift_reason")" \
    >> "$AUDIT_FILE"
fi

cat > "$STATE_FILE" <<EOF
fail_streak=$fail_streak
alert_active=$alert_active
last_status=$last_status
last_callback_url=$last_callback_url
last_failure_reason=$last_failure_reason
resolver_fail_streak=$resolver_fail_streak
resolver_alert_active=$resolver_alert_active
last_resolver_source=$last_resolver_source
last_dns_server=$last_dns_server
last_unsigned_attempts=$last_unsigned_attempts
last_signed_attempts=$last_signed_attempts
EOF
