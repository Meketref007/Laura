#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/shopee/agente"
REPORT_DIR="$ROOT_DIR/reports"
LOG_DIR="$ROOT_DIR/logs"
CALLBACK_FILE="$REPORT_DIR/laura_webhook_callback_latest.txt"
GUARD_STATE_FILE="$REPORT_DIR/laura_webhook_ready_guard.state"
AUDIT_FILE="$REPORT_DIR/laura_webhook_ready_audit.jsonl"

cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.env"
  set +a
fi

CALLBACK_MAX_AGE_MINUTES="${LAURA_WEBHOOK_DOCTOR_CALLBACK_MAX_AGE_MINUTES:-120}"
AUDIT_MAX_AGE_MINUTES="${LAURA_WEBHOOK_DOCTOR_AUDIT_MAX_AGE_MINUTES:-30}"

if ! [[ "$CALLBACK_MAX_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  CALLBACK_MAX_AGE_MINUTES=120
fi
if ! [[ "$AUDIT_MAX_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
  AUDIT_MAX_AGE_MINUTES=30
fi

status_ok=1

callback_url="unknown"
if [[ -f "$CALLBACK_FILE" ]]; then
  callback_url="$(head -n 1 "$CALLBACK_FILE" | tr -d '[:space:]')"
fi
if [[ -z "$callback_url" ]]; then
  callback_url="unknown"
  status_ok=0
fi

callback_file_age_min="unknown"
callback_stale=0
if [[ -f "$CALLBACK_FILE" ]]; then
  callback_mtime_epoch="$(stat -c %Y "$CALLBACK_FILE" 2>/dev/null || true)"
  now_epoch="$(date +%s)"
  if [[ "$callback_mtime_epoch" =~ ^[0-9]+$ ]] && [[ "$now_epoch" =~ ^[0-9]+$ ]]; then
    callback_file_age_min=$(( (now_epoch - callback_mtime_epoch) / 60 ))
    if (( callback_file_age_min > CALLBACK_MAX_AGE_MINUTES )); then
      callback_stale=1
      status_ok=0
    fi
  fi
fi

ready_output="$("$ROOT_DIR/scripts/laura_webhook_shopee_ready.sh" 2>&1 || true)"
ready_result="$(printf '%s\n' "$ready_output" | awk -F= '/^result=/{print $2}' | tail -n 1)"
unsigned_code="$(printf '%s\n' "$ready_output" | awk -F= '/^unsigned_code=/{print $2}' | tail -n 1)"
signed_code="$(printf '%s\n' "$ready_output" | awk -F= '/^signed_code=/{print $2}' | tail -n 1)"
unsigned_latency="$(printf '%s\n' "$ready_output" | awk -F= '/^unsigned_latency_seconds=/{print $2}' | tail -n 1)"
signed_latency="$(printf '%s\n' "$ready_output" | awk -F= '/^signed_latency_seconds=/{print $2}' | tail -n 1)"
unsigned_attempts="$(printf '%s\n' "$ready_output" | awk -F= '/^unsigned_attempts=/{print $2}' | tail -n 1)"
signed_attempts="$(printf '%s\n' "$ready_output" | awk -F= '/^signed_attempts=/{print $2}' | tail -n 1)"
resolver_source="$(printf '%s\n' "$ready_output" | awk -F= '/^resolver_source=/{print $2}' | tail -n 1)"
dns_server="$(printf '%s\n' "$ready_output" | awk -F= '/^dns_server=/{print $2}' | tail -n 1)"
ready_message="$(printf '%s\n' "$ready_output" | awk -F= '/^message=/{print $2}' | tail -n 1)"

if [[ "$ready_result" != "ready_for_shopee_verify" ]]; then
  status_ok=0
fi

guard_fail_streak="unknown"
guard_alert_active="unknown"
guard_last_status="unknown"
guard_resolver_fail_streak="unknown"
guard_resolver_alert_active="unknown"
guard_last_resolver_source="unknown"
guard_last_dns_server="unknown"
guard_last_unsigned_attempts="unknown"
guard_last_signed_attempts="unknown"
if [[ -f "$GUARD_STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$GUARD_STATE_FILE"
  guard_fail_streak="${fail_streak:-unknown}"
  guard_alert_active="${alert_active:-unknown}"
  guard_last_status="${last_status:-unknown}"
  guard_resolver_fail_streak="${resolver_fail_streak:-unknown}"
  guard_resolver_alert_active="${resolver_alert_active:-unknown}"
  guard_last_resolver_source="${last_resolver_source:-unknown}"
  guard_last_dns_server="${last_dns_server:-unknown}"
  guard_last_unsigned_attempts="${last_unsigned_attempts:-unknown}"
  guard_last_signed_attempts="${last_signed_attempts:-unknown}"
fi

audit_last="none"
audit_last_age_min="unknown"
audit_stale=0
if [[ -f "$AUDIT_FILE" ]]; then
  audit_last="$(tail -n 1 "$AUDIT_FILE" 2>/dev/null || true)"
  if [[ -z "$audit_last" ]]; then
    audit_last="none"
  else
    audit_last_age_min="$(AUDIT_LAST_JSON="$audit_last" python3 - <<'PY'
import json
import os
from datetime import datetime, timezone

row = os.environ.get("AUDIT_LAST_JSON", "").strip()
if not row:
    print("unknown")
    raise SystemExit(0)

try:
    obj = json.loads(row)
    ts = str(obj.get("timestamp", "")).strip()
    if not ts:
        print("unknown")
        raise SystemExit(0)
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    age_min = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    print(age_min)
except Exception:
    print("unknown")
PY
)"
    if [[ "$audit_last_age_min" =~ ^[0-9]+$ ]] && (( audit_last_age_min > AUDIT_MAX_AGE_MINUTES )); then
      audit_stale=1
      status_ok=0
    fi
  fi
fi

if pgrep -f "cloudflared tunnel --url http://127.0.0.1:${LAURA_WEBHOOK_PORT:-8765}" >/dev/null 2>&1; then
  tunnel_process="running"
else
  tunnel_process="down"
  status_ok=0
fi

if ss -ltn | grep -q "127.0.0.1:${LAURA_WEBHOOK_PORT:-8765}"; then
  webhook_listener="listening"
else
  webhook_listener="down"
  status_ok=0
fi

echo "laura_webhook_doctor"
echo "status=$([[ $status_ok -eq 1 ]] && echo ok || echo attention)"
echo "callback_url=${callback_url}"
echo "callback_file_age_min=${callback_file_age_min}"
echo "callback_file_max_age_min=${CALLBACK_MAX_AGE_MINUTES}"
echo "callback_stale=${callback_stale}"
echo "tunnel_process=${tunnel_process}"
echo "webhook_listener=${webhook_listener}"
echo "ready_result=${ready_result:-unknown}"
echo "unsigned_code=${unsigned_code:-unknown}"
echo "signed_code=${signed_code:-unknown}"
echo "unsigned_latency_seconds=${unsigned_latency:-unknown}"
echo "signed_latency_seconds=${signed_latency:-unknown}"
echo "unsigned_attempts=${unsigned_attempts:-unknown}"
echo "signed_attempts=${signed_attempts:-unknown}"
echo "resolver_source=${resolver_source:-unknown}"
echo "dns_server=${dns_server:-unknown}"
echo "ready_message=${ready_message:-none}"
echo "guard_last_status=${guard_last_status}"
echo "guard_fail_streak=${guard_fail_streak}"
echo "guard_alert_active=${guard_alert_active}"
echo "guard_resolver_fail_streak=${guard_resolver_fail_streak}"
echo "guard_resolver_alert_active=${guard_resolver_alert_active}"
echo "guard_last_resolver_source=${guard_last_resolver_source}"
echo "guard_last_dns_server=${guard_last_dns_server}"
echo "guard_last_unsigned_attempts=${guard_last_unsigned_attempts}"
echo "guard_last_signed_attempts=${guard_last_signed_attempts}"
echo "audit_last_age_min=${audit_last_age_min}"
echo "audit_last_max_age_min=${AUDIT_MAX_AGE_MINUTES}"
echo "audit_stale=${audit_stale}"
echo "audit_last=${audit_last}"

if [[ $status_ok -eq 1 ]]; then
  exit 0
fi

exit 1
